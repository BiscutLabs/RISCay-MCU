# SPDX-License-Identifier: Apache-2.0
"""Exercise executed-probe provenance with a real Icarus compile and run."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from check_export import MappingProbeAttestation, activity_diagnostics


class MappingProbeAttestationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='riscay-attestation-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'filelist.f').write_text('design.sv\n')
        (self.root / 'design.sv').write_text('module Design; endmodule\n')
        (self.root / 'contract_probe.sv').write_text(
            'module ContractProbe; initial begin $display("CONTRACT_PROBES_PASS:7"); $finish; end endmodule\n')
        self.attestation = MappingProbeAttestation(self.root)

    def compile(self):
        result = self.attestation.run(subprocess.run,
            ['iverilog', '-g2012', '-s', 'Design', '-s', 'ContractProbe', '-o', 'contract_probe.vvp',
             'design.sv', 'contract_probe.sv'], cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def simulate(self):
        result = self.attestation.run(subprocess.run, ['vvp', 'contract_probe.vvp'],
            cwd=self.root, capture_output=True, text=True, timeout=30)
        (self.root / 'contract_simulation.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        return result

    def receipt(self):
        return dict(status='PASS', semantic_sha256='test-semantic', mapping_checks=7,
                    source_sha256=self.attestation.sources())

    def test_real_executed_pass(self):
        self.compile()
        self.assertEqual(self.simulate().returncode, 0)
        record = self.attestation.finish(self.receipt())
        self.assertEqual(record['probe_sha256'], self.attestation.digest('contract_probe.sv'))
        self.assertEqual(record['compiled_vvp_sha256'], self.attestation.digest('contract_probe.vvp'))
        self.assertEqual(record['simulation_log_sha256'], self.attestation.digest('contract_simulation.log'))
        self.assertEqual(json.loads((self.root / 'mapping-probe-attestation.json').read_text()), record)

    def test_edited_inputs_or_binary_before_execution(self):
        for name in ('contract_probe.sv', 'design.sv', 'contract_probe.vvp'):
            with self.subTest(name=name):
                self.compile()
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                with self.assertRaisesRegex(ValueError, 'CHANGED_BEFORE_EXECUTION'):
                    self.simulate()
                path.write_bytes(original)

    def test_edited_artifacts_after_execution(self):
        self.compile()
        self.simulate()
        for name in ('contract_probe.sv', 'design.sv', 'contract_probe.vvp', 'contract_simulation.log'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                with self.assertRaisesRegex(ValueError, 'CHANGED_AFTER_EXECUTION|SIMULATION_LOG'):
                    self.attestation.finish(self.receipt())
                path.write_bytes(original)

    def test_recompile_invalidates_old_execution(self):
        self.compile()
        self.simulate()
        self.compile()
        with self.assertRaisesRegex(ValueError, 'NO_EXECUTED_PASS'):
            self.attestation.finish(self.receipt())

    def test_auxiliary_validation_bindings_are_attested_and_cannot_change(self):
        binding = self.root / 'verification/assert/layers-Target-Assert.sv'
        binding.parent.mkdir(parents=True)
        original = b'bind Target TargetAssert assertions ();\n'
        binding.write_bytes(original)
        self.compile()
        binding.write_bytes(original + b'// changed before execution\n')
        with self.assertRaisesRegex(ValueError, 'CHANGED_BEFORE_EXECUTION'):
            self.simulate()
        binding.write_bytes(original)
        self.assertEqual(self.simulate().returncode, 0)
        record = self.attestation.finish(self.receipt())
        self.assertEqual(record['validation_auxiliary_sha256'], {
            'verification/assert/layers-Target-Assert.sv': self.attestation.digest(binding)})
        binding.unlink()
        with self.assertRaisesRegex(ValueError, 'CHANGED_AFTER_EXECUTION'):
            self.attestation.finish(self.receipt())

    def test_uncompiled_binary_is_rejected(self):
        (self.root / 'contract_probe.vvp').write_text('not compiled by this invocation')
        with self.assertRaisesRegex(ValueError, 'CHANGED_BEFORE_EXECUTION'):
            self.simulate()

    def test_wrong_count_source_receipt_and_status(self):
        self.compile()
        self.simulate()
        for field, value, diagnostic in (('mapping_checks', 8, 'SIMULATION_LOG'),
                ('source_sha256', {}, 'SOURCE_RECEIPT'), ('status', 'RUNNING', 'NO_EXECUTED_PASS')):
            with self.subTest(field=field):
                receipt = self.receipt()
                receipt[field] = value
                with self.assertRaisesRegex(ValueError, diagnostic):
                    self.attestation.finish(receipt)

    def test_real_failed_simulation_is_not_a_pass(self):
        path = self.root / 'contract_probe.sv'
        path.write_text(path.read_text().replace('$finish;', '$fatal(1,"UNRELATED_FAILURE");'))
        self.compile()
        self.assertNotEqual(self.simulate().returncode, 0)
        with self.assertRaisesRegex(ValueError, 'NO_EXECUTED_PASS'):
            self.attestation.finish(self.receipt())

    def test_wrong_compile_output_cannot_borrow_old_binary(self):
        self.compile()
        self.simulate()
        path = self.root / 'contract_probe.sv'
        path.write_text(path.read_text().replace('$finish;', '$fatal(1,"NEW_FAILURE");'))
        with self.assertRaisesRegex(ValueError, 'COMPILE_COMMAND'):
            self.attestation.run(subprocess.run,
                ['iverilog', '-g2012', '-s', 'Design', '-s', 'ContractProbe', '-o', 'other.vvp',
                 'design.sv', 'contract_probe.sv'], cwd=self.root, capture_output=True, text=True, timeout=30)
        with self.assertRaisesRegex(ValueError, 'CHANGED_BEFORE_EXECUTION'):
            self.simulate()

    def test_wrong_source_inventory_is_rejected(self):
        self.compile()
        for inputs in (['contract_probe.sv'], ['design.sv'],
                       ['design.sv', 'contract_probe.sv', 'extra.sv']):
            with self.subTest(inputs=inputs), self.assertRaisesRegex(ValueError, 'COMPILE_COMMAND'):
                self.attestation.run(subprocess.run,
                    ['iverilog', '-g2012', '-s', 'ContractProbe', '-o', 'contract_probe.vvp', *inputs],
                    cwd=self.root, capture_output=True, text=True, timeout=30)

    def test_activity_diagnostics_preserve_oracles_and_show_all_gaps(self):
        original = '''module ContractProbe;
reg [1:0] ones_0=0, zeros_0=3;
reg ones_1=0, zeros_1=0;
initial begin
if (ones_0 !== 2'h3 || zeros_0 !== 2'h3) $fatal(1, "INACTIVE_ENDPOINT:first");
if (ones_1 !== 1'h0 || zeros_1 !== 1'h1) $fatal(1, "INACTIVE_ENDPOINT:literal_zero");
$display("CONTRACT_PROBES_PASS:7"); $finish;
end endmodule
'''
        extended = activity_diagnostics(original)
        self.assertEqual(extended.count('$fatal('), original.count('$fatal('))
        for line in original.splitlines():
            self.assertIn(line, extended)
        for passed in (False, True):
            probe = extended.replace('ones_0=0', 'ones_0=3').replace('zeros_1=0', 'zeros_1=1') if passed else extended
            (self.root / 'contract_probe.sv').write_text(probe)
            self.compile()
            result = self.simulate()
            if passed:
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertNotIn('ACTIVITY_GAP:', result.stdout)
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('ACTIVITY_GAP:first:', result.stdout)
                self.assertIn('ACTIVITY_GAP:literal_zero:', result.stdout)
                self.assertIn('INACTIVE_ENDPOINT:first', result.stdout)
                self.assertNotIn('CONTRACT_PROBES_PASS:', result.stdout)


if __name__ == '__main__':
    unittest.main()
