# SPDX-License-Identifier: Apache-2.0
"""Pure proof-adapter controls and an explicit bounded actual-netlist campaign."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_program_address as proof


def small_graph():
    prefix = 'ca_child_program_access.ca_child_command_bridge'
    address, received, image = list(range(100, 132)), list(range(200, 212)), list(range(300, 312))
    bound = dict(top='FourPhaseSoc', prefix=prefix, alias=prefix + '.packed_1_probe',
                 endpoint='FourPhaseSoc.' + prefix + '.packed_1_probe', count_width=12,
                 zero_lsb=49, zero_width=20, packed_width=69)
    nets = {prefix + '.in_bits_address': address,
            prefix + '.in_bits_mask': ['0'] * 4, prefix + '.in_bits_data': ['0'] * 32,
            prefix + '.in_bits_write': ['0'], bound['alias']: ['0'] * 37 + address,
            'ca_child_program_access.io_request_bits_address': address,
            '_ca_child_control_reply_bridge_out_bits_state_received': received,
            'fabric_controlState_imageLength': image}
    cells = {'mux': dict(type='$mux', parameters={'WIDTH': '00000000000000000000000000100000'},
                        port_directions={'A': 'input', 'B': 'input', 'S': 'input', 'Y': 'output'},
                        connections={'A': ['0'] * 32, 'B': received + ['0'] * 20, 'S': [400], 'Y': address}),
             'state': dict(type='$adff', parameters={}, port_directions={'D': 'input', 'Q': 'output'},
                           connections={'D': ['0'] * 25, 'Q': received + image + [400]})}
    module = dict(ports={}, cells=cells, netnames={n: dict(bits=b) for n, b in nets.items()})
    return dict(modules={'FourPhaseSoc': module}), bound


class ConeControls(unittest.TestCase):
    def test_state_is_unconstrained_and_exact_cells_are_preserved(self):
        database, bound = small_graph()
        cone, scope = proof.extract_cone(database, bound)
        self.assertEqual(scope['state_assumptions'], [])
        self.assertEqual(scope['boundary_bits'], 13)
        self.assertEqual(cone['modules'][proof.TOP]['cells'], {'mux': database['modules']['FourPhaseSoc']['cells']['mux']})
        self.assertEqual(len(cone['modules'][proof.TOP]['ports']['upper']['bits']), 20)

    def test_state_reset_does_not_constrain_cutpoint(self):
        database, bound = small_graph()
        first = proof.extract_cone(database, bound)
        database['modules']['FourPhaseSoc']['cells']['state']['parameters']['ARST_VALUE'] = '1' * 25
        self.assertEqual(proof.extract_cone(database, bound), first)

    def test_ambiguous_driver_rejected(self):
        database, bound = small_graph()
        cells = database['modules']['FourPhaseSoc']['cells']
        cells['duplicate'] = copy.deepcopy(cells['mux'])
        with self.assertRaisesRegex(ValueError, 'MULTIPLE_DRIVERS'):
            proof.extract_cone(database, bound)

    def test_unknown_cell_not_assumed_zero(self):
        database, bound = small_graph()
        database['modules']['FourPhaseSoc']['cells']['mux']['type'] = '$unsupported'
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_LOGIC'):
            proof.extract_cone(database, bound)

    def test_unknown_state_not_cut_silently(self):
        database, bound = small_graph()
        database['modules']['FourPhaseSoc']['cells']['state']['type'] = 'UnknownState'
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_LOGIC'):
            proof.extract_cone(database, bound)

    def test_combinational_cycle_rejected(self):
        database, bound = small_graph()
        cell = database['modules']['FourPhaseSoc']['cells']['mux']
        cell['connections']['A'] = cell['connections']['Y']
        with self.assertRaisesRegex(ValueError, 'COMBINATIONAL_CYCLE'):
            proof.extract_cone(database, bound)

    def test_undefined_constant_rejected(self):
        database, bound = small_graph()
        database['modules']['FourPhaseSoc']['cells']['mux']['connections']['A'][14] = 'x'
        with self.assertRaisesRegex(ValueError, 'UNDEFINED_CONSTANT'):
            proof.extract_cone(database, bound)

    def test_undriven_input_rejected(self):
        database, bound = small_graph()
        database['modules']['FourPhaseSoc']['cells']['mux']['connections']['S'] = [999]
        with self.assertRaisesRegex(ValueError, 'UNDRIVEN_BIT'):
            proof.extract_cone(database, bound)

    def test_packed_alias_changed_rejected(self):
        database, bound = small_graph()
        database['modules']['FourPhaseSoc']['netnames'][bound['alias']]['bits'][49] = 999
        with self.assertRaisesRegex(ValueError, 'PACKED_ALIAS'):
            proof.extract_cone(database, bound)

    def test_access_alias_changed_rejected(self):
        database, bound = small_graph()
        database['modules']['FourPhaseSoc']['netnames']['ca_child_program_access.io_request_bits_address']['bits'] = [999] * 32
        with self.assertRaisesRegex(ValueError, 'ACCESS_ALIAS'):
            proof.extract_cone(database, bound)

    def test_capacity_source_width_changed_rejected(self):
        database, bound = small_graph()
        database['modules']['FourPhaseSoc']['netnames']['fabric_controlState_imageLength']['bits'].append(999)
        with self.assertRaisesRegex(ValueError, 'NET_SHAPE'):
            proof.extract_cone(database, bound)

    def test_signedness_and_comparator_parameters_are_not_rewritten(self):
        database, bound = small_graph()
        cells = database['modules']['FourPhaseSoc']['cells']
        cells['cmp'] = dict(type='$lt', parameters=dict(A_SIGNED='1', B_SIGNED='1', A_WIDTH='1100', B_WIDTH='1100', Y_WIDTH='1'),
                           port_directions={'A': 'input', 'B': 'input', 'Y': 'output'},
                           connections={'A': list(range(200, 212)), 'B': list(range(300, 312)), 'Y': [401]})
        cells['mux']['connections']['S'] = [401]
        cone, _ = proof.extract_cone(database, bound)
        self.assertEqual(cone['modules'][proof.TOP]['cells']['cmp'], cells['cmp'])

    def test_resource_cap_is_fail_closed(self):
        database, bound = small_graph()
        with patch.object(proof, 'MAX_CELLS', 0), self.assertRaisesRegex(ValueError, 'CELL_LIMIT'):
            proof.extract_cone(database, bound)

    def test_top_input_resource_cap_is_fail_closed(self):
        database, bound = small_graph()
        module = database['modules']['FourPhaseSoc']
        module['ports']['input'] = dict(direction='input', bits=module['cells'].pop('state')['connections']['Q'])
        with patch.object(proof, 'MAX_BOUNDARY_BITS', 0), self.assertRaisesRegex(ValueError, 'BOUNDARY_LIMIT'):
            proof.extract_cone(database, bound)


class BindingControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        prefix = 'FourPhaseSoc.ca_child_program_access.ca_child_command_bridge'
        fields = [('mask', 0, 4), ('data', 4, 32), ('write', 36, 1), ('address', 37, 32)]
        self.bridge = dict(module='DecoupledToFourPhase', rtl_path=prefix,
            channels=[dict(id='in', protocol='decoupled-v1', role='input', data='in_data',
                layout=[dict(field='bits.' + name, lsb=lsb, width=width, signed=False,
                             source='~|DecoupledToFourPhase>in.bits.' + name) for name, lsb, width in fields])],
            endpoints=[dict(id='in_data', width=69, source='~|DecoupledToFourPhase>in.bits',
                            rtl_path=prefix + '.ca_p_7_in_data', probe='input_probe')])
        self.manifest = dict(top='FourPhaseSoc', design=dict(children=[dict(id='program_access', contract=dict(
            module='ProgramAccess', rtl_path='FourPhaseSoc.ca_child_program_access',
            children=[dict(id='command_bridge', contract=self.bridge)]))]))
        self.reference = self.directory / 'ref_FourPhaseSoc.sv'
        self.reference.write_text('`define ref_FourPhaseSoc_input_probe ' + prefix.split('.', 1)[1] + '.packed_1_probe\n')
        self.inventory = dict(schema='riscay-gf180-sram-v1', macro='gf180mcu_ocd_ip_sram__sram1024x8m8wm1',
            program_bytes=2048, working_ram_bytes=1024,
            instances=[dict(path='FourPhaseSoc.fabric_program_macros_' + str(i), bank='program', index=i) for i in range(2)] +
                      [dict(path='FourPhaseSoc.fabric_ram_macros_0', bank='ram', index=0)])
        (self.directory / 'sram.json').write_text(json.dumps(self.inventory))

    def bind(self):
        return proof.binding(self.directory, self.manifest, 2048)

    def test_exact_schema_and_capacity(self):
        self.assertEqual(self.bind()['zero_lsb'], 49)
        self.assertEqual(self.bind()['zero_width'], 20)

    def test_layout_width(self):
        self.bridge['channels'][0]['layout'][3]['width'] = 31
        with self.assertRaisesRegex(ValueError, 'LAYOUT'): self.bind()

    def test_layout_signedness(self):
        self.bridge['channels'][0]['layout'][3]['signed'] = True
        with self.assertRaisesRegex(ValueError, 'LAYOUT'): self.bind()

    def test_layout_source(self):
        self.bridge['channels'][0]['layout'][3]['source'] = '~|Wrong>in.bits.address'
        with self.assertRaisesRegex(ValueError, 'LAYOUT'): self.bind()

    def test_bridge_protocol_identity(self):
        self.bridge['module'] = 'DecoupledToClick'
        with self.assertRaisesRegex(ValueError, 'BRIDGE_IDENTITY'): self.bind()

    def test_endpoint_width(self):
        self.bridge['endpoints'][0]['width'] = 68
        with self.assertRaisesRegex(ValueError, 'ENDPOINT_SCHEMA'): self.bind()

    def test_resolved_endpoint_identity(self):
        self.bridge['endpoints'][0]['rtl_path'] += '_wrong'
        with self.assertRaisesRegex(ValueError, 'RESOLVED_ENDPOINT'): self.bind()

    def test_duplicate_probe_definition(self):
        self.reference.write_text(self.reference.read_text() * 2)
        with self.assertRaisesRegex(ValueError, 'PROBE_ALIAS'): self.bind()

    def test_probe_wrong_owner(self):
        self.reference.write_text(self.reference.read_text().replace('ca_child_program_access', 'ca_child_ram_access'))
        with self.assertRaisesRegex(ValueError, 'PROBE_ALIAS'): self.bind()

    def test_capacity_not_inferred_from_observed_width(self):
        with self.assertRaisesRegex(ValueError, 'CAPACITY'):
            proof.binding(self.directory, self.manifest, 1024)

    def source_fixture(self):
        graph = self.directory / 'reset-crossings'
        graph.mkdir()
        (self.directory / 'contract.json').write_text(json.dumps(dict(manifest=self.manifest)))
        (self.directory / 'filelist.f').write_text('source.sv\n')
        (self.directory / 'source.sv').write_text('module source; endmodule\n')
        for name in ('netlist.json', 'converted.v', 'graph.ys'):
            (graph / name).write_text('fixture ' + name)
        record = dict(top='FourPhaseSoc', sources={'source.sv': proof.sha(self.directory / 'source.sv')},
            tools={}, sram_capacities=dict(program=2048),
            sram_blackbox_sha256=proof.sha(proof.ROOT / 'soc/src/main/resources/riscay/sram/gf180mcu_ocd_ip_sram__sram1024x8m8wm1.blackbox.v'))
        for file, key in ((self.directory / 'filelist.f', 'filelist_sha256'),
                          (self.directory / 'contract.json', 'contract_sha256'),
                          (self.directory / 'sram.json', 'sram_inventory_sha256'),
                          (graph / 'netlist.json', 'netlist_sha256'),
                          (graph / 'converted.v', 'converted_sha256'),
                          (graph / 'graph.ys', 'script_sha256')):
            record[key] = proof.sha(file)
        (graph / 'report.json').write_text(json.dumps(dict(status='pass', violations=[], inputs=record)))
        return self.bind()

    def test_source_netlist_contract_and_capacity_bytes_are_bound(self):
        bound = self.source_fixture()
        proof.source_inputs(self.directory, bound)
        for name in ('source.sv', 'reset-crossings/netlist.json', 'contract.json', 'sram.json',
                     'reset-crossings/converted.v', 'reset-crossings/graph.ys'):
            path = self.directory / name
            original = path.read_bytes()
            try:
                path.write_bytes(original + b' mutation')
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'):
                    proof.source_inputs(self.directory, bound)
            finally:
                path.write_bytes(original)

    def test_reference_changes_after_receipt_rejected(self):
        bound = self.source_fixture()
        inputs = proof.source_inputs(self.directory, bound)
        self.reference.write_text(self.reference.read_text() + '// changed\n')
        with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'): proof.rehash(inputs)

    def test_binding_cannot_borrow_unrelated_persisted_contract(self):
        bound = self.source_fixture()
        bound['endpoint'] += '_wrong'
        with self.assertRaisesRegex(ValueError, 'PERSISTED_CONTRACT_BINDING'):
            proof.source_inputs(self.directory, bound)

    def test_fresh_attempts_preserve_failures(self):
        target = proof.next_attempt(self.directory / 'attempts')
        target.mkdir()
        (target / 'receipt.json').write_text('failed evidence')
        self.assertEqual(proof.next_attempt(self.directory / 'attempts').name, 'attempt-0002')
        self.assertEqual((target / 'receipt.json').read_text(), 'failed evidence')


class ProbeControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def persist(self, record):
        path = Path(self.temp.name) / 'proof.json'
        body = {k: v for k, v in record.items() if k not in ('proof_record', 'proof_record_sha256')}
        path.write_text(json.dumps(body))
        record.update(proof_record=str(path), proof_record_sha256=proof.sha(path))
        return record

    def source_and_proof(self):
        _, bound = small_graph()
        source = f'''task check; begin
end endtask
if (ones_7 !== 69'h1fffffffffffffffff || zeros_7 !== 69'h1fffffffffffffffff) $fatal(1, "INACTIVE_ENDPOINT:{bound['endpoint']}");
'''
        record = dict(status='PASS_UNIVERSAL_COMBINATIONAL_ZERO', binding=bound, inputs_sha256={}, physical_qualification=False)
        return source, self.persist(record)

    def test_only_one_polarity_mask_changes_and_every_check_asserts_four_state_zero(self):
        source, record = self.source_and_proof()
        result = proof.program_address_probe(source, record)
        self.assertIn("ones_7 !== 69'h1ffffffffffff", result)
        self.assertIn("zeros_7 !== 69'h1fffffffffffffffff", result)
        self.assertIn("[68:49] !== 20'h0", result)
        self.assertEqual(result.count('PROGRAM_ADDRESS_UPPER_NOT_ZERO'), 1)

    def test_failed_proof_not_masked(self):
        source, record = self.source_and_proof()
        record['status'] = 'FAIL_OR_INCOMPLETE'
        self.persist(record)
        with self.assertRaisesRegex(ValueError, 'PROOF_STATUS'):
            proof.program_address_probe(source, record)

    def test_repeated_or_partial_mask_rejected(self):
        source, record = self.source_and_proof()
        source = proof.program_address_probe(source, record)
        with self.assertRaisesRegex(ValueError, 'CONSTANT_COVERAGE_SHAPE'):
            proof.program_address_probe(source, record)

    def test_other_endpoint_not_masked(self):
        source, record = self.source_and_proof()
        record['binding']['endpoint'] += '_wrong'
        with self.assertRaisesRegex(ValueError, 'PROOF_RECORD_BINDING'):
            proof.program_address_probe(source, record)

    def test_mutated_persisted_record_rejected(self):
        source, record = self.source_and_proof()
        Path(record['proof_record']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'PROOF_RECORD_HASH'):
            proof.program_address_probe(source, record)

    def test_changed_proof_input_rejected(self):
        source, record = self.source_and_proof()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'graph.json'
            path.write_text('original')
            record['inputs_sha256'][str(path)] = proof.sha(path)
            self.persist(record)
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'):
                proof.program_address_probe(source, record)


def driver(module, bit):
    found = [(name, cell) for name, cell in module['cells'].items()
             if any(direction == 'output' and bit in cell['connections'][port]
                    for port, direction in cell['port_directions'].items())]
    assert len(found) == 1
    return found[0]


def actual_controls(exports, output):
    """Four original graphs and eight real graph faults; no mutant RTL compile."""
    exports, output = Path(exports).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    records, baseline_hashes = [], {str(Path(__file__).resolve()): proof.sha(__file__)}
    for flavor in ('portable-r1', 'physical-r1'):
        for variant in ('bd', 'click'):
            directory = exports / flavor / variant
            manifest = proof.load(directory / 'contract.json')['manifest']
            bound = proof.binding(directory, manifest, 2048)
            original = proof.load(directory / 'reset-crossings/netlist.json')
            inputs = proof.source_inputs(directory, bound)
            baseline_hashes.update(inputs)
            for fault in ('baseline', 'loader_upper_wire', 'cpu_range_mux_bypass'):
                database = copy.deepcopy(original)
                module = database['modules'][bound['top']]
                address = module['netnames'][bound['prefix'] + '.in_bits_address']['bits']
                root_name, root = driver(module, address[12])
                assert root['type'] == '$mux' and root['connections']['Y'] == address
                mutation = None
                if fault == 'loader_upper_wire':
                    assert root['connections']['B'][12:] == ['0'] * 20
                    root['connections']['B'][12] = '1'
                    mutation = dict(cell=root_name, pin='B', bit=12, before='0', after='1')
                elif fault == 'cpu_range_mux_bypass':
                    name, cell = driver(module, root['connections']['A'][12])
                    assert cell['type'] == '$mux' and cell['connections']['B'] == ['0'] * 32
                    mutation = dict(cell=name, pin='S', before=cell['connections']['S'], after=['0'])
                    cell['connections']['S'] = ['0']
                cone, scope = proof.extract_cone(database, bound)
                case_output = output / (flavor + '-' + variant + '-' + fault)
                record = dict(flavor=flavor, variant=variant, fault=fault, mutation=mutation,
                              scope=scope, evidence_directory=str(case_output))
                try:
                    result = proof.sat_prove(cone, case_output, inputs)
                    record['result'] = result
                    assert fault == 'baseline', 'MUTANT_UNEXPECTEDLY_PROVED'
                    record['status'] = 'PASS_UNIVERSAL_COMBINATIONAL_ZERO'
                except ValueError as error:
                    assert fault != 'baseline', str(error)
                    result = proof.load(case_output / 'receipt.json')
                    text = (case_output / 'yosys.log').read_text()
                    assert result['exit_code'] != 0 and result['timed_out'] is False
                    assert 'ERROR: Called with -verify and proof did fail!' in text
                    assert 'SAT proof finished - model found: FAIL!' in text
                    record['result'] = result
                    record['status'] = 'EXPECTED_SAT_COUNTEREXAMPLE'
                records.append(record)
    proof.rehash(baseline_hashes)
    assert sum(r['status'] == 'PASS_UNIVERSAL_COMBINATIONAL_ZERO' for r in records) == 4
    assert sum(r['status'] == 'EXPECTED_SAT_COUNTEREXAMPLE' for r in records) == 8
    result = dict(status='PASS_ACTUAL_NETLIST_CONTROLS', original_graphs_unchanged=True,
                  originals=4, exact_counterexamples=8, cases=records,
                  inputs_sha256=baseline_hashes, runner_sha256=proof.sha(__file__),
                  executed_evidence_sha256={str(p): proof.sha(p) for p in sorted(output.rglob('*')) if p.is_file()},
                  mutant_scope='Actual elaborated graph cell mutations; no full mutant RTL elaboration.',
                  physical_qualification=False)
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'originals', 'exact_counterexamples')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--actual-exports', type=Path)
    parser.add_argument('--out', type=Path)
    args, rest = parser.parse_known_args()
    if args.actual_exports:
        if args.out is None:
            parser.error('--out is required for actual graph controls')
        actual_controls(args.actual_exports, args.out)
    else:
        unittest.main(argv=[__file__, *rest])
