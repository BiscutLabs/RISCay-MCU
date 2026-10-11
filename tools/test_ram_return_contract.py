# SPDX-License-Identifier: Apache-2.0
"""Closed RAM-return policy negatives; optional --sources also checks actual RTL."""
import argparse
import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from check_ram_return_contract import (CAPTURES, PORTS, expression, policy, validate_export,
                                       validate_ram_return, validate_ram_return_rtl, ram_return_bindings,
                                       local_probe_name, global_probe_name)
from check_ram_return_capture_controls import CAMPAIGNS, source_oracles
from check_admission_controls import replace_pin


def fixture(variant):
    """Small explicit netlist spelling for parser tests, independent of CIRCT names."""
    spec = policy(variant); module = 'ClickRamReturn' if variant == 'click' else 'FourPhaseRamReturn'
    node = dict(module=module, rtl_path=module, reset_domain='root', capacity=1, children=[],
                endpoints=[], channels=[], primitives=[], timing=copy.deepcopy(spec['timings']))
    for name, width in spec['widths'].items():
        probe = 'ca_p_' + str(len(name)) + '_' + name
        node['endpoints'].append(dict(id=name, width=width, probe=probe, rtl_path=module + '.' + probe))
    for name, role, width in (('word', 'input', 32), ('publication', 'output', 1)):
        node['channels'].append(dict(id=name, role=role, protocol='two-phase-bundled-v1' if variant == 'click' else 'four-phase-bundled-v1',
            reset_domain='root', **{f: name + '_' + f for f in ('request', 'data', 'acknowledge')},
            layout=[dict(field='bits', lsb=0, width=width, signed=False, source='~|' + module + '>' + name + '.bits')]))
    width_text = lambda w: '' if w == 1 else '[' + str(w - 1) + ':0] '
    rtl = ['module ' + module + '(\n' + ',\n'.join(d + ' ' + width_text(w) + n for n, (d, w) in PORTS.items()) + '\n);']
    for name, c in spec['cells'].items():
        width = int(c['parameters'].get('WIDTH', 1)); pins = dict(c['pins'])
        if not name.endswith('_marker'):
            rtl.append('wire ' + width_text(width) + 'Q_' + name + ';'); pins['q'] = 'Q_' + name
        widths = {n: 1 for n in pins}
        if c['model'].endswith('ControlGate_v1'): widths.update(a=width, b=width, q=width)
        elif c['model'].endswith('EventRegister_v1'): widths.update(d=width, q=width)
        elif c['model'].endswith('TimingMarker_v1'): widths['values'] = width
        elif c['model'].endswith('AsymmetricC_v1'): widths.update(common=1, rising=int(c['parameters']['RISING']), falling=1)
        node['primitives'].append(dict(id=name, model=c['model'], parameters=copy.deepcopy(c['parameters']), reset=c['reset'],
            reset_domain='root', rtl_path=module + '.i_' + name, resource='chiselasync/sv/' + c['model'] + '.sv', version=1,
            view='constraint-marker' if name.endswith('_marker') else 'behavioral',
            ports=[dict(name=n, width=w, direction='output' if n == 'q' else 'input') for n, w in widths.items()]))
        rtl.append(c['model'] + ' #(\n' + ',\n'.join('.' + n + '(' + v + ')' for n, v in c['parameters'].items()) +
                   '\n) i_' + name + ' (\n' + ',\n'.join('.' + n + '(' + v + ')' for n, v in pins.items()) + '\n);')
    for name, value in spec['outputs'].items(): rtl.append('assign ' + name + ' = ' + value + ';')
    refs = []
    for e in node['endpoints']:
        wire = 'e_' + e['id']; rtl.append('wire ' + width_text(e['width']) + wire + ' = ' + spec['endpoints'][e['id']] + ';')
        refs.append('`define ref_' + module + '_' + e['probe'] + ' ' + wire)
    return node, '\n'.join(rtl + ['endmodule']), '\n'.join(refs)


class RamReturnContractTests(unittest.TestCase):
    def test_both_complete_native_contracts(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant); result = validate_ram_return_rtl(node, rtl, refs)
            self.assertEqual(result['schema'], 'riscay-reset-boundary-v1')
            self.assertEqual(set(result['captures']), set(CAPTURES[variant]))
            application = {s['id'] for s in result['state'] if s['lifetime'] == 'application'}
            self.assertEqual(application, {'permission', 'application_target', 'application_phase'} if variant == 'click' else
                {'permission', 'application_seen'} | {'application_' + name + suffix for name in ('offer', 'request') for suffix in ('', '_na', '_nb', '_or')})
            self.assertTrue(result['publication']['dynamic'])
            self.assertEqual(result['application_port']['payload_lifetime'], 'power-on')

    def test_unknown_or_clocked_owner_and_hidden_children(self):
        for variant in CAPTURES:
            node, _, _ = fixture(variant)
            for name in ('ClockedRamReturn', 'ClickRamReturnAdapter', 'FourPhaseRamReturn_bad'):
                bad = copy.deepcopy(node); bad['module'] = name
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_OWNER'): validate_ram_return(bad)
            node['children'].append(dict(id='hidden'))
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_INVENTORY'): validate_ram_return(node)

    def test_hierarchical_bindings_cover_all_pins_and_endpoints(self):
        for variant in CAPTURES:
            node, _, _ = fixture(variant); top = node['module']; node['rtl_path'] = 'Soc.ca_child_ram_return'
            for item in node['endpoints'] + node['primitives']:
                item['rtl_path'] = item['rtl_path'].replace(top + '.', node['rtl_path'] + '.', 1)
            for item in node['endpoints']: item['probe'] = global_probe_name(node, item['id'])
            pairs = ram_return_bindings(node)
            expected = policy(variant)
            self.assertEqual(len(pairs), sum(len(c['pins']) for c in expected['cells'].values()) +
                             len(expected['endpoints']) + len(expected['outputs']))
            self.assertTrue(all(left.startswith(node['rtl_path'] + '.') for left, _ in pairs))
            self.assertFalse(any(re.search(r'\bQ_\w+', right) for _, right in pairs))

    def test_resolved_hierarchy_suffix_and_consistent_domain(self):
        node, rtl, refs = fixture('click'); old = node['module']; node['module'] += '_2'; node['rtl_path'] = 'Soc.ca_child_ram_return'
        node['reset_domain'] = 'persistent'
        rtl = rtl.replace(old, node['module']); refs = refs.replace(old, node['module'])
        for item in node['primitives']:
            item['rtl_path'] = item['rtl_path'].replace(old + '.', node['rtl_path'] + '.', 1)
            item['reset_domain'] = node['reset_domain']
        for channel in node['channels']:
            channel['reset_domain'] = node['reset_domain']; channel['layout'][0]['source'] = channel['layout'][0]['source'].replace(old, node['module'])
        for item in node['endpoints']:
            item['rtl_path'] = node['rtl_path'] + '.e_' + item['id']; item['probe'] = global_probe_name(node, item['id'])
        record = validate_ram_return_rtl(node, rtl, refs, resolved=True)
        self.assertEqual(record['por'], node['rtl_path'] + '.reset')
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_ENDPOINT_PATH'): validate_ram_return(node)
        bad = copy.deepcopy(node); bad['endpoints'][0]['rtl_path'] = 'Other.e_word_request'
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_ENDPOINT_PATH'): validate_ram_return(bad, resolved=True)
        bad = copy.deepcopy(node); bad['endpoints'][0]['rtl_path'] = node['rtl_path'] + '.response_ack'
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RESOLVED_PROBE_BINDING'):
            validate_ram_return_rtl(bad, rtl, refs, resolved=True)
        bad = copy.deepcopy(node); bad['primitives'][0]['reset_domain'] = 'application'
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RESET'): validate_ram_return(bad, resolved=True)

    def test_nested_global_probes_are_distinct_from_local_rtl_anchors(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant); old = node['rtl_path']
            node['rtl_path'] = 'Chip.ca_child_soc.ca_child_ram_return'
            for item in node['endpoints'] + node['primitives']:
                item['rtl_path'] = item['rtl_path'].replace(old + '.', node['rtl_path'] + '.', 1)
            for e in node['endpoints']: e['probe'] = global_probe_name(node, e['id'])
            first = node['endpoints'][0]
            self.assertEqual(first['probe'], 'ca_p_3_soc_10_ram_return_12_word_request')
            self.assertEqual(first['rtl_path'], node['rtl_path'] + '.ca_p_12_word_request')
            validate_ram_return(node); validate_ram_return(node, resolved=True)
            validate_ram_return_rtl(node, rtl, refs)
            for e in node['endpoints']: e['rtl_path'] = node['rtl_path'] + '.e_' + e['id']
            validate_ram_return_rtl(node, rtl, refs, resolved=True)
            forwarded_refs = refs
            for e in node['endpoints']:
                forwarded_refs = forwarded_refs.replace('ref_' + node['module'] + '_' + local_probe_name(e['id']) + ' ',
                    'ref_' + node['module'] + '_' + e['probe'] + ' ')
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_PROBES'):
                validate_ram_return_rtl(node, rtl, forwarded_refs, resolved=True)
            for wrong in ('ca_p_12_word_request', 'ca_p_3_soc_10_other_name_12_word_request',
                          'ca_p_3_soc_11_ram_return_12_word_request', 'ca_p_10_ram_return_12_word_request'):
                bad = copy.deepcopy(node); bad['endpoints'][0]['probe'] = wrong
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_ENDPOINT_PATH'):
                    validate_ram_return(bad, resolved=True)

    def test_original_local_probe_path_cannot_use_forwarded_global_name(self):
        node, _, _ = fixture('bd'); old = node['rtl_path']; node['rtl_path'] = 'Soc.ca_child_ram_return'
        for item in node['endpoints'] + node['primitives']:
            item['rtl_path'] = item['rtl_path'].replace(old + '.', node['rtl_path'] + '.', 1)
        for e in node['endpoints']: e['probe'] = global_probe_name(node, e['id'])
        node['endpoints'][0]['rtl_path'] = node['rtl_path'] + '.' + node['endpoints'][0]['probe']
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_ENDPOINT_PATH'): validate_ram_return(node)

    def test_every_primitive_is_required_and_no_extra_state_is_allowed(self):
        for variant in CAPTURES:
            node, _, _ = fixture(variant)
            for i in range(len(node['primitives'])):
                bad = copy.deepcopy(node); bad['primitives'].pop(i)
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CELLS'): validate_ram_return(bad)
            bad = copy.deepcopy(node); extra = copy.deepcopy(node['primitives'][0]); extra['id'] = 'hidden'; bad['primitives'].append(extra)
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CELLS'): validate_ram_return(bad)

    def test_every_reset_domain_and_pin_is_closed(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            for i, c in enumerate(node['primitives']):
                with self.subTest(variant=variant, cell=c['id']):
                    bad = copy.deepcopy(node); bad['primitives'][i]['reset'] = 'wrong'
                    with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RESET:'): validate_ram_return(bad)
                    changed = replace_pin(rtl, 'i_' + c['id'], 'reset', "1'h0")
                    with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_BINDING:'): validate_ram_return_rtl(node, changed, refs)

    def test_each_register_trigger_data_and_q_binding_is_checked(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            for name in CAPTURES[variant]:
                for pin in ('trigger', 'd', 'q'):
                    changed = replace_pin(rtl, 'i_' + name, pin, "1'h0")
                    with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_(BINDING|Q_DRIVER)'):
                        validate_ram_return_rtl(node, changed, refs)

    def test_timing_metadata_and_fixed_guard_parameters_cannot_drift(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            for i in range(len(node['timing'])):
                bad = copy.deepcopy(node); bad['timing'][i]['kind'] = 'ignored'
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_TIMING'): validate_ram_return(bad)
            for i, c in enumerate(node['primitives']):
                for parameter in c['parameters']:
                    bad = copy.deepcopy(node); bad['primitives'][i]['parameters'][parameter] = '999'
                    with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CELL_POLICY'): validate_ram_return(bad)

    def test_endpoint_inventory_aliases_and_widths_are_closed(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            for i, e in enumerate(node['endpoints']):
                bad = copy.deepcopy(node); bad['endpoints'][i]['width'] += 1
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_ENDPOINTS'): validate_ram_return(bad)
                changed = refs.replace(' ' + 'e_' + e['id'] + '\n', ' response_ack\n') if i < len(node['endpoints']) - 1 else refs.rsplit(' ', 1)[0] + ' response_ack'
                if e['id'] == 'response_acknowledge': continue
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_PROBE_(BINDING|WIDTH)'):
                    validate_ram_return_rtl(node, rtl, changed)

    def test_payload_error_and_publication_bindings_cannot_be_narrowed_or_constant_masked(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            for name in ('publication_bits', 'response_bits_data', 'response_bits_error'):
                changed = re.sub(r'assign ' + name + r' = [^;]+;', 'assign ' + name + " = 1'h1;", rtl)
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_'): validate_ram_return_rtl(node, changed, refs)
            changed = rtl.replace("assign response_bits_error = 1'h0;", "wire literal_alias=1'h0;\nassign response_bits_error=literal_alias;")
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_ERROR_LITERAL'): validate_ram_return_rtl(node, changed, refs)
            changed = rtl.replace('wire [31:0] Q_payload;', 'wire [30:0] Q_payload;')
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_Q_DRIVER'): validate_ram_return_rtl(node, changed, refs)

    def test_every_control_input_is_closed(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            for name, c in policy(variant)['cells'].items():
                for pin, value in c['pins'].items():
                    if pin == 'reset': continue
                    replacement = "1'h1" if value == "1'h0" else "1'h0"
                    with self.subTest(variant=variant, cell=name, pin=pin):
                        changed = replace_pin(rtl, 'i_' + name, pin, replacement)
                        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_BINDING'): validate_ram_return_rtl(node, changed, refs)

    def test_extra_writers_clocked_state_and_unknown_constructs_are_rejected(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            for extra in ("reg hidden; always @(posedge reset) hidden<=eligible;", "initial begin force response_req=1'b0; end",
                          'logic hidden;', 'wire hidden=eligible;', 'assign response_req=eligible;',
                          'assign Q_payload=32\'h0;', 'assign reset=1\'h0;',
                          'ChiselAsyncEventRegister_v1 #(.WIDTH(1)) hidden(.reset(reset),.q(hidden));'):
                with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_'):
                    validate_ram_return_rtl(node, rtl.replace('endmodule', extra + '\nendmodule'), refs)

    def test_duplicate_pins_endpoints_and_instances_are_rejected(self):
        for variant in CAPTURES:
            node, rtl, refs = fixture(variant)
            bad = copy.deepcopy(node); bad['endpoints'].append(copy.deepcopy(bad['endpoints'][0]))
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_ENDPOINT_DUPLICATE'): validate_ram_return(bad)
            changed = rtl.replace('.reset(reset)', '.reset(reset),.reset(reset)', 1)
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_PIN_DUPLICATE'): validate_ram_return_rtl(node, changed, refs)
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_PROBE_DUPLICATE'): validate_ram_return_rtl(node, rtl, refs + '\n' + refs.splitlines()[0])

    def test_native_click_schema_cannot_be_replaced_by_return_to_zero(self):
        node, _, _ = fixture('click')
        for c in node['channels']: c['protocol'] = 'four-phase-bundled-v1'
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CHANNEL_SCHEMA'): validate_ram_return(node)

    def test_expression_precedence_aliases_and_invalid_syntax(self):
        self.assertNotEqual(expression('a&b==c'), expression('(a&b)==c'))
        self.assertEqual(expression('(a&b)&c'), expression('a&(b&c)'))
        self.assertNotEqual(expression('a?b:c'), expression('a?c:b'))
        for text in ('a&&b', 'a+b', 'a;assign b=c', 'a[0]+b', '1', 'a(b)', '$random'):
            with self.assertRaises(ValueError): expression(text)

    def test_intermediate_alias_width_cannot_truncate(self):
        node, rtl, refs = fixture('click')
        rtl = rtl.replace('e_response_data =', 'e_response_data =')
        changed = rtl.replace('wire [32:0] e_response_data', 'wire [31:0] e_response_data')
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_PROBE_WIDTH'): validate_ram_return_rtl(node, changed, refs)
        changed = rtl.replace('.d(Q_data_delay[31:0])', '.d(truncated)')
        changed = changed.replace('endmodule', 'wire [30:0] truncated=Q_data_delay[31:0];\nendmodule')
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_RTL_WIRE_WIDTH'): validate_ram_return_rtl(node, changed, refs)


class RamCaptureCohortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.sources = {}
        for variant, labels in CAMPAIGNS.items():
            self.sources[variant] = {}
            for label in sorted(labels):
                p = Path(self.temp.name) / variant / label; (p / 'export').mkdir(parents=True)
                (p / 'export/contract.json').write_text('{}'); self.sources[variant][label] = str(p)
                for seed in range(1, 25):
                    case = p / f'seed-{seed}'; case.mkdir()
                    (case / 'result.json').write_text(json.dumps(dict(status='PASS', seed=str(seed), varied_cells=1, activity=[
                        'CA_ACTIVITY channel=word delivered=1', 'CA_ACTIVITY channel=publication delivered=1'])))
                    delay = '10000000' if seed == 2 else '1000000'
                    delays = dict(seed=str(seed), algorithm='java.util.Random; 1=min,2=max', pins_fs={}, cells_fs={'Top.gate': delay})
                    bench = 'defparam dut.gate.DELAY_FS=' + delay + ';\n$display("CA_TEST_PASS seed=' + str(seed) + '");'
                    for filename, content in (('simulation.log', 'CA_TEST_PASS'), ('compile.log', ''), ('delays.json', json.dumps(delays)), ('testbench.sv', bench)):
                        (case / filename).write_text(content)

    def validator(self, directory):
        variant = directory.parents[1].name
        return dict(owner='ClickRamReturn' if variant == 'click' else 'FourPhaseRamReturn', export_sha256={'rtl': variant},
                    delay_policy={'Top.gate': dict(fixed_fs=None, minimum_fs=1000000, maximum_fs=10000000)})

    def check(self): return source_oracles(self.sources, validate=self.validator)

    def test_complete_40_by_24_cohort(self):
        selected, _, _ = self.check(); self.assertEqual(sum(map(len, selected.values())), 40)

    def test_missing_or_extra_fixture(self):
        self.sources['bd'].pop('offer-bound')
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_FIXTURES'): self.check()

    def test_duplicate_fixture_path(self):
        self.sources['bd']['offer-bound'] = self.sources['bd']['stalls']
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_DUPLICATE_SOURCE'): self.check()

    def test_missing_seed_file(self):
        (Path(self.sources['click']['stalls']) / 'seed-24/testbench.sv').unlink()
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_SEED_FILES'): self.check()

    def test_extra_seed(self):
        (Path(self.sources['bd']['stalls']) / 'seed-25').mkdir()
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_SEED_INVENTORY'): self.check()

    def test_failed_result_or_mismatched_seed(self):
        p = Path(self.sources['bd']['stalls']) / 'seed-24/result.json'; original = json.loads(p.read_text())
        for change in (dict(status='FAIL'), dict(seed='23')):
            p.write_text(json.dumps(dict(original, **change)))
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_SEED_PASS'): self.check()

    def test_empty_activity_or_simulator_failure(self):
        p = Path(self.sources['click']['stalls']) / 'seed-24/simulation.log'
        p.write_text('CA_TEST_PASS\nFATAL: other failure')
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_SEED_LOG'): self.check()
        p.write_text('CA_TEST_PASS'); p = p.with_name('result.json'); r = json.loads(p.read_text()); r['activity'] = []
        p.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_SEED_ACTIVITY'): self.check()

    def test_mixed_export_cohort(self):
        def different(path):
            record = self.validator(path)
            if path.parent.name == 'offer-bound': record['export_sha256'] = {'rtl': 'changed'}
            return record
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_EXPORT_COHORT'):
            source_oracles(self.sources, validate=different)

    def test_delay_table_and_actual_testbench_must_agree(self):
        case = Path(self.sources['bd']['stalls']) / 'seed-2'; bench = case / 'testbench.sv'
        bench.write_text(bench.read_text().replace('10000000', '1000000'))
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_ORACLE_DELAYS'): self.check()
        delay = case / 'delays.json'; record = json.loads(delay.read_text()); record['cells_fs']['Top.gate'] = '1000000'
        delay.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CAPTURE_DELAY_VALUE'): self.check()


def actual_suite(sources):
    class ActualRamReturnExportTests(unittest.TestCase):
        def test_all_actual_exports_close(self):
            for variant, fixtures in sources.items():
                for label, source in fixtures.items():
                    with self.subTest(variant=variant, fixture=label): validate_export(Path(source) / 'export')

        def test_every_actual_input_pin_rewire_and_extra_writer_is_rejected(self):
            for variant, fixtures in sources.items():
                p = Path(fixtures['stalls']) / 'export'; node = json.loads((p / 'contract.json').read_text())['manifest']['design']
                rtl = (p / (node['module'] + '.sv')).read_text(); refs = (p / ('ref_' + node['module'] + '.sv')).read_text()
                for cell in node['primitives']:
                    for port in cell['ports']:
                        if port['direction'] != 'input': continue
                        replacement = "1'h1" if port['name'] in ('b', 'falling') else "1'h0"
                        changed = replace_pin(rtl, cell['rtl_path'].split('.')[1], port['name'], replacement)
                        with self.subTest(variant=variant, cell=cell['id'], pin=port['name']):
                            with self.assertRaises(ValueError): validate_ram_return_rtl(node, changed, refs)
                for extra in ('reg hidden;', "assign response_req=1'b0;", 'wire extra=eligible;'):
                    with self.assertRaises(ValueError): validate_ram_return_rtl(node, rtl.replace('endmodule', extra + '\nendmodule'), refs)
    return unittest.defaultTestLoader.loadTestsFromTestCase(ActualRamReturnExportTests)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--sources', type=Path); args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    if args.sources: suite.addTests(actual_suite(json.loads(args.sources.read_text())))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
