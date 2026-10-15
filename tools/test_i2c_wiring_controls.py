# SPDX-License-Identifier: Apache-2.0
"""Independent negative controls for exact-fault attribution and run provenance."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import check_i2c_wiring_controls as controls
from check_export import i2c_path_bindings
from test_i2c_export import fixture


class I2cWiringControlsTest(unittest.TestCase):
    def test_actual_probe_aliases_resolve_without_changing_the_manifest(self):
        manifest = dict(top='I2cPublication', design=dict(rtl_path='I2cPublication', endpoints=[
            dict(id='in_request', probe='ca_p_10_in_request', rtl_path='I2cPublication.ca_p_10_in_request')]))
        refs = {'ca_p_10_in_request': 'in_req'}
        resolved = controls.resolved_node(manifest, refs)
        self.assertEqual(resolved['endpoints'][0]['rtl_path'], 'I2cPublication.in_req')
        self.assertEqual(manifest['design']['endpoints'][0]['rtl_path'], 'I2cPublication.ca_p_10_in_request')
        for bad in ({}, {**refs, 'extra': 'unused'}):
            with self.assertRaisesRegex(AssertionError, 'I2C_PROBE_SET'):
                controls.resolved_node(manifest, bad)
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory)/'probe.sv'
            probe.write_text('module ContractProbe;\ntask check;\n'
                'if (I2cPublication.in_req !== I2cPublication.cell.a) $fatal(1,"DATA_PATH_BINDING_MISMATCH");\nendtask\nendmodule\n')
            pair = [(resolved['endpoints'][0]['rtl_path'], 'I2cPublication.cell.a')]
            self.assertEqual(controls.fault_site(probe, 'I2cPublication.cell.a', pair)['line'], 3)
            with self.assertRaisesRegex(AssertionError, 'I2C_FAULT_ASSERTION_SITE'):
                controls.fault_site(probe, 'I2cPublication.cell.a',
                    [(manifest['design']['endpoints'][0]['rtl_path'], 'I2cPublication.cell.a')])

    def test_every_old_and_new_fault_resolves_its_actual_pin_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory)/'contract_probe.sv'
            for click in (False, True):
                bindings = i2c_path_bindings(fixture(click))
                source = 'module ContractProbe;\ntask check; begin\n'+''.join(
                    f'if ({a} !== {b}) $fatal(1, "DATA_PATH_BINDING_MISMATCH");\n' for a, b in bindings)
                source += 'end endtask\nendmodule\n'
                probe.write_text(source)
                pins = ['Top.request_delay.a', 'Top.observation.trigger', 'Top.data_delay.a']
                for prefix in (('capture_gate',) if click else ('frame_publish', 'snapshot_publish')):
                    pins += ['Top.'+prefix+'_or.a', 'Top.'+prefix+'_or.b', 'Top.'+prefix+'.a']
                sites = [controls.fault_site(probe, pin, bindings) for pin in pins]
                self.assertEqual(len(set(x['line'] for x in sites)), len(pins))
                for pin, site in zip(pins, sites):
                    self.assertEqual(site['mutated_pin'], pin)
                    self.assertIn(pin, site['comparison'])
                    self.assertEqual(site['scope'], 'ContractProbe.check')
                for bad in (source.replace('task check;', 'task unrelated;'),
                            source.replace('module ContractProbe;', 'module Other;'),
                            source.replace('Top.request_delay.a', 'Top.request_delay.b'),
                            source.replace('end endtask', source.splitlines()[sites[0]['line']-1]+'\nend endtask')):
                    probe.write_text(bad)
                    with self.assertRaises(AssertionError):
                        controls.fault_site(probe, pins[0], bindings)
                probe.write_text(source)
                with self.assertRaisesRegex(AssertionError, 'I2C_FAULT_PIN_COMPARISON'):
                    controls.fault_site(probe, 'Top.unrelated.a', bindings)

    def test_positive_classifier_requires_one_full_pass_and_no_error(self):
        result = dict(exit_code=0, timed_out=False)
        good = 'CONTRACT_PROBES_PASS:123\n'
        self.assertIsNone(controls.classify_simulation(result, good, Path('.'), 123))
        for bad in ('', good+good, good.replace('123', '122'),
                    good+'ERROR: silent failure\n', good+'TIMEOUT\n', good+'DEADLINE\n',
                    good+'FATAL: test.sv:9: unrelated\n'):
            with self.assertRaises(AssertionError):
                controls.classify_simulation(result, bad, Path('.'), 123)
        for bad in (dict(exit_code=1, timed_out=False), dict(exit_code=0, timed_out=True)):
            with self.assertRaises(AssertionError):
                controls.classify_simulation(bad, good, Path('.'), 123)

    def test_negative_classifier_rejects_unrelated_fatal_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            expected = dict(file=str((folder/'contract_probe.sv').resolve()), line=31,
                            diagnostic='DATA_PATH_BINDING_MISMATCH', scope='ContractProbe.check')
            result = dict(exit_code=1, timed_out=False)
            good = 'FATAL: contract_probe.sv:31: DATA_PATH_BINDING_MISMATCH\n       Time: 1000 Scope: ContractProbe.check\n'
            observed = controls.classify_simulation(result, good, folder, 123, expected)
            self.assertEqual(observed['time'], 1000)
            self.assertEqual(observed['file'], expected['file'])
            changes = [good.replace(':31:', ':32:'), good.replace('contract_probe.sv', 'other.sv'),
                       good.replace('contract_probe.sv', '../contract_probe.sv'),
                       good.replace('DATA_PATH_BINDING_MISMATCH', 'INACTIVE_ENDPOINT'),
                       good.replace('ContractProbe.check', 'ContractProbe.other'),
                       good.splitlines()[0]+'\n', good+good,
                       'DATA_PATH_BINDING_MISMATCH\n', good+'ERROR: unrelated\n',
                       good+'TIMEOUT\n', good+'CONTRACT_PROBES_PASS:123\n']
            for bad in changes:
                with self.assertRaises(AssertionError):
                    controls.classify_simulation(result, bad, folder, 123, expected)
            for bad in (dict(exit_code=0, timed_out=False), dict(exit_code=1, timed_out=True)):
                with self.assertRaises(AssertionError):
                    controls.classify_simulation(bad, good, folder, 123, expected)

    @staticmethod
    def files(folder):
        rtl = folder/'I2cPublication.sv'
        rtl.write_text('''module Pin(input a, output q); assign q=a; endmodule
module I2cPublication;
reg source=0; wire q;
Pin actual_pin (
  .a (source),
  .q (q)
  );
endmodule
''')
        probe = folder/'contract_probe.sv'
        probe.write_text('''module ContractProbe;
task check; begin
if (I2cPublication.source !== I2cPublication.actual_pin.a) $fatal(1,"DATA_PATH_BINDING_MISMATCH");
end endtask
initial begin
  I2cPublication.source=1; #1; check;
  $display("CONTRACT_PROBES_PASS:1"); $finish;
end
endmodule
''')
        (folder/'filelist.f').write_text('I2cPublication.sv\n')
        (folder/'contract.json').write_text('{}\n')
        return rtl, probe

    def test_compiler_inventory_requires_exact_mutated_source_and_tracks_every_input(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            rtl, probe = self.files(folder)
            baseline = controls.compile_inputs(folder, [rtl], probe, rtl)
            self.assertEqual(set(baseline['source_sha256']), {str(rtl.resolve()), str(probe.resolve())})
            for inputs in ([], [rtl, rtl], [rtl, probe]):
                with self.assertRaises(AssertionError):
                    controls.compile_inputs(folder, inputs, probe, rtl)
            for changed in (rtl, probe, folder/'filelist.f', folder/'contract.json'):
                original = changed.read_bytes()
                changed.write_bytes(original+b'\n')
                with self.assertRaisesRegex(AssertionError, 'I2C_COMPILER_INPUT_CHANGED'):
                    controls.unchanged_inputs(baseline, folder, [rtl], probe, rtl, 'control')
                changed.write_bytes(original)
            with tempfile.TemporaryDirectory() as other:
                outside = Path(other)/'extra.sv'
                outside.write_text('module Extra; endmodule\n')
                with self.assertRaisesRegex(AssertionError, 'I2C_COMPILE_SOURCE_OUTSIDE_CASE'):
                    controls.compile_inputs(folder, [rtl, outside], probe, rtl)

    def test_real_compile_and_simulation_bind_the_fault_and_all_identity_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            for mutate in (False, True):
                folder = Path(directory)/str(mutate)
                folder.mkdir()
                rtl, probe = self.files(folder)
                expected = None
                if mutate:
                    rtl.write_text(controls.mutate_pin(rtl.read_text(), 'actual_pin', 'a'))
                    expected = controls.fault_site(probe, 'I2cPublication.actual_pin.a',
                        [('I2cPublication.source', 'I2cPublication.actual_pin.a')])
                commands, record = [], {}
                controls.execute_case(folder, 1, expected, controls.digest(probe), commands, record)
                self.assertEqual(record['status'], 'PASS')
                self.assertEqual(record['precompile'], record['postcompile'])
                self.assertEqual(record['precompile'], record['postsimulation'])
                self.assertEqual(record['binary_before_execution_sha256'], record['binary_after_execution_sha256'])
                self.assertEqual(len(commands), 2)
                self.assertEqual(bool(record['fatal_site']), mutate)
                self.assertEqual(json.loads((folder/'case-receipt.json').read_text()), record)

    def test_compile_simulation_and_binary_tampering_fail_and_keep_receipts(self):
        actual_run = controls.run
        with tempfile.TemporaryDirectory() as directory:
            for fault in ('compile-source', 'simulation-probe', 'simulation-binary'):
                folder = Path(directory)/fault
                folder.mkdir()
                rtl, probe = self.files(folder)
                record = {}
                def corrupted(command, where, log, commands):
                    result = actual_run(command, where, log, commands)
                    if fault == 'compile-source' and command[0] == 'iverilog':
                        rtl.write_bytes(rtl.read_bytes()+b'\n')
                    if command[0] == 'vvp':
                        changed = probe if fault == 'simulation-probe' else where/'wiring-control.vvp'
                        changed.write_bytes(changed.read_bytes()+b'\n')
                    return result
                with patch.object(controls, 'run', side_effect=corrupted):
                    with self.assertRaisesRegex(AssertionError, 'I2C_COMPILER_INPUT_CHANGED|I2C_EXECUTED_BINARY_CHANGED'):
                        controls.execute_case(folder, 1, None, controls.digest(probe), [], record)
                self.assertEqual(record['status'], 'FAIL')
                self.assertIn('precompile', record)
                self.assertEqual(json.loads((folder/'case-receipt.json').read_text()), record)

    def test_timeout_output_is_preserved_and_never_counts_as_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            error = subprocess.TimeoutExpired(['vvp'], 600, output=b'CONTRACT_PROBES_PASS:1\n', stderr=b'partial stderr')
            with patch.object(controls.subprocess, 'run', side_effect=error):
                result, output = controls.run(['vvp'], folder, 'timeout.log', [])
            self.assertTrue(result['timed_out'])
            self.assertEqual((folder/'timeout.log').read_text(), output)
            self.assertIn('partial stderr', output)
            with self.assertRaisesRegex(AssertionError, 'I2C_SIMULATION_TIMEOUT'):
                controls.classify_simulation(result, output, folder, 1)
