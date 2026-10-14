# SPDX-License-Identifier: Apache-2.0
"""Fail-closed cohort, real-port resolution and exact-fatal evidence controls."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from check_elapsed_capture_controls import (FIXTURES, PROFILES, aliases, exact_fatal,
    fixture_seeds, resolve, sha, source_oracles, source_port, validate_cohort_identity, validate_delays, validate_identity)


class ElapsedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.sources = {v: {} for v in FIXTURES}; self.names = {}
        for variant, names in FIXTURES.items():
            for name in names:
                source = self.root / (variant + '-' + name); (source / 'export').mkdir(parents=True)
                (source / 'export/contract.json').write_text('{}')
                self.sources[variant][name] = str(source); self.names[source.resolve()] = (variant, name)
                for seed in fixture_seeds(name):
                    folder = source / ('seed-' + str(seed)); folder.mkdir()
                    (folder / 'testbench.sv').write_text('// independent original')
                    (folder / 'simulation.log').write_text('CA_TEST_PASS seed=' + str(seed))
                    (folder / 'result.json').write_text(json.dumps(dict(status='PASS', seed=str(seed))))
        fake = patch('check_elapsed_capture_controls.fixture_name', side_effect=lambda p: self.names[p])
        fake.start(); self.addCleanup(fake.stop)

    def test_complete_inventory(self):
        selected, oracles = source_oracles(self.sources)
        self.assertEqual(len(selected), 27)
        self.assertEqual(sum(map(len, oracles.values())), 159)
        self.assertEqual(len(PROFILES), 6)
        self.assertEqual({p[0] for p in PROFILES}, {'min', 'max'})

    def test_missing_fixture(self):
        del self.sources['bd']['por-command-fall']
        with self.assertRaisesRegex(ValueError, 'FIXTURE_INVENTORY:bd'):
            source_oracles(self.sources)

    def test_missing_random_seed(self):
        (Path(self.sources['click']['nibbles-normal']) / 'seed-16/testbench.sv').unlink()
        with self.assertRaisesRegex(ValueError, 'ORACLE_INVENTORY'):
            source_oracles(self.sources)

    def test_failed_source_result(self):
        p = Path(self.sources['bd']['por-nibble-3']) / 'seed-19/result.json'
        p.write_text(json.dumps(dict(status='FAIL', seed='19')))
        with self.assertRaisesRegex(ValueError, 'SOURCE_NOT_PASS'):
            source_oracles(self.sources)

    def test_display_only_pass_does_not_hide_source_failure(self):
        p = Path(self.sources['click']['early-next']) / 'seed-1/simulation.log'
        p.write_text('CA_TEST_PASS\nFATAL: testbench.sv:17: unrelated')
        with self.assertRaisesRegex(ValueError, 'SOURCE_LOG_NOT_PASS'):
            source_oracles(self.sources)

    def test_wrong_fixture_identity(self):
        source = Path(self.sources['bd']['por-nibble-1'])
        self.names[source] = ('bd', 'por-nibble-2')
        with self.assertRaisesRegex(ValueError, 'FIXTURE_IDENTITY'):
            source_oracles(self.sources)

    def test_extra_seed_is_rejected(self):
        p = Path(self.sources['click']['por-phase-zero']) / 'seed-20'; p.mkdir()
        (p / 'testbench.sv').write_text('// extra')
        with self.assertRaisesRegex(ValueError, 'ORACLE_INVENTORY'):
            source_oracles(self.sources)


class ElapsedBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.node = dict(module='Owner', rtl_path='Top.owner', channels=[dict(id='out', layout=[
            dict(field='bits.commandPhase', source='~|Owner>out.bits.commandPhase', width=1, signed=False)])])
        self.port = dict(source='~|Owner>out.bits.commandPhase', width=1, signed=False, clock=False, direction='output')
        self.write_abi()
        (self.root / 'Owner.sv').write_text('module Owner(output out_bits_commandPhase); endmodule\n')

    def write_abi(self):
        (self.root / 'ports.json').write_text(json.dumps(dict(nodes=[dict(rtl_path='Top.owner', ports=[self.port])])))

    def test_flattened_actual_port_does_not_require_uncompiled_metadata_anchor(self):
        self.assertEqual(source_port(self.root, self.node, 'out', 'bits.commandPhase', 1), 'out_bits_commandPhase')

    def test_forged_layout_source_is_rejected(self):
        self.node['channels'][0]['layout'][0]['source'] = '~|Other>out.bits.commandPhase'
        with self.assertRaisesRegex(ValueError, 'LAYOUT_SOURCE'):
            source_port(self.root, self.node, 'out', 'bits.commandPhase', 1)

    def test_abi_width_must_match(self):
        self.port['width'] = 2; self.write_abi()
        with self.assertRaisesRegex(ValueError, 'ABI_SHAPE'):
            source_port(self.root, self.node, 'out', 'bits.commandPhase', 1)

    def test_actual_declared_width_must_match(self):
        (self.root / 'Owner.sv').write_text('module Owner(output [1:0] out_bits_commandPhase); endmodule\n')
        with self.assertRaisesRegex(ValueError, 'ACTUAL_PORT_SHAPE'):
            source_port(self.root, self.node, 'out', 'bits.commandPhase', 1)

    def test_alias_resolution_retains_bit_selection_and_rejects_cycles(self):
        drivers = aliases('wire [1:0] h; wire a=h[0]; assign command_ack=a;')
        self.assertEqual(resolve('command_ack', drivers), 'h[0]')
        with self.assertRaisesRegex(ValueError, 'ALIAS_CYCLE'):
            resolve('a', {'a': 'b', 'b': 'a'})

    def test_same_name_twice_is_not_an_alias(self):
        with self.assertRaisesRegex(ValueError, 'MULTIPLE_DRIVER'):
            aliases('wire x=a; assign x=b;')


class ElapsedFatalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name)
        (self.case / 'testbench.sv').write_text('module Testbench;\ninitial $fatal(1,"ELAPSED_HISTORY_Q_VALUE");\nendmodule\n')
        (self.case / 'sim.vvp').write_text('compiled binary identity')
        self.log = 'FATAL: testbench.sv:2: ELAPSED_HISTORY_Q_VALUE\n       Time: 100 Scope: Testbench.eh_require_q\n'
        self.record()

    def record(self):
        (self.case / 'simulation.log').write_text(self.log)
        self.evidence = dict(compile=dict(exit_code=0), simulation=dict(exit_code=1, log_sha256=sha(self.case / 'simulation.log')),
                             binary_sha256=sha(self.case / 'sim.vvp'), sources_sha256={'testbench.sv': sha(self.case / 'testbench.sv')})

    def verify(self):
        return exact_fatal(self.case, 'ELAPSED_HISTORY_Q_VALUE', self.evidence)

    def test_exact_first_fatal_and_hashes(self):
        self.assertEqual(self.verify()['line'], 2)

    def test_matching_display_is_not_a_fatal(self):
        self.log = 'ELAPSED_HISTORY_Q_VALUE\n'; self.record()
        with self.assertRaisesRegex(ValueError, 'CONTROL_NO_FATAL'):
            self.verify()

    def test_unrelated_first_failure_is_rejected(self):
        self.log = 'FATAL: testbench.sv:1: unrelated\n       Time: 99 Scope: Testbench\n' + self.log; self.record()
        with self.assertRaisesRegex(ValueError, 'CONTROL_WRONG_FIRST_FATAL'):
            self.verify()

    def test_matching_message_at_another_site_is_rejected(self):
        self.log = self.log.replace('sv:2:', 'sv:3:'); self.record()
        with self.assertRaisesRegex(ValueError, 'CONTROL_WRONG_FIRST_FATAL'):
            self.verify()

    def test_matching_message_in_another_scope_is_rejected(self):
        self.log = self.log.replace('Testbench.eh_require_q', 'Testbench.unrelated'); self.record()
        with self.assertRaisesRegex(ValueError, 'CONTROL_WRONG_FATAL_SCOPE'):
            self.verify()

    def test_later_unrelated_failure_is_rejected(self):
        self.log += 'FATAL: testbench.sv:3: unrelated\n       Time: 101 Scope: Testbench\n'; self.record()
        with self.assertRaisesRegex(ValueError, 'CONTROL_MULTIPLE_FATALS'):
            self.verify()

    def test_source_binary_and_log_are_bound(self):
        for name in ('testbench.sv', 'sim.vvp', 'simulation.log'):
            with self.subTest(name=name):
                path = self.case / name; old = path.read_bytes(); path.write_bytes(old + b'changed')
                with self.assertRaisesRegex(ValueError, 'CONTROL_(SOURCE|EXECUTION)_CHANGED'):
                    self.verify()
                path.write_bytes(old)


class ElapsedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'Elapsed.scala'; source.write_text('original source')
        os.utime(source, (1, 1))
        self.log = self.root / 'generation.log'
        self.log.write_text('AsyncElapsedLoopSpec:\nAll tests passed.\n')
        self.document = dict(schema='riscay-elapsed-capture-sources-v1', source_identity=dict(
            files={'Elapsed.scala': sha(source)}, generation_log=dict(path=str(self.log), sha256=sha(self.log))))
        for name, value in (('ROOT', self.root), ('IDENTITY_FILES', ('Elapsed.scala',))):
            mocked = patch('check_elapsed_capture_controls.' + name, value)
            mocked.start(); self.addCleanup(mocked.stop)

    def test_current_source_and_generation_hashes(self):
        validate_identity(self.document)

    def test_changed_source(self):
        (self.root / 'Elapsed.scala').write_text('new source')
        with self.assertRaisesRegex(ValueError, 'SOURCE_IDENTITY_CHANGED'):
            validate_identity(self.document)

    def test_changed_generation_log(self):
        self.log.write_text('other generation')
        with self.assertRaisesRegex(ValueError, 'GENERATION_LOG_CHANGED'):
            validate_identity(self.document)

    def test_failed_generation_cannot_be_attested_by_rehashing(self):
        self.log.write_text('AsyncElapsedLoopSpec:\n*** FAILED\nAll tests passed.\n')
        self.document['source_identity']['generation_log']['sha256'] = sha(self.log)
        with self.assertRaisesRegex(ValueError, 'GENERATION_NOT_PASS'):
            validate_identity(self.document)


class ElapsedDelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.folder = self.root / 'seed-1'; self.folder.mkdir()
        self.node = dict(primitives=[dict(id='history', rtl_path='Top.history', parameters={'DELAY_FS': '1000000'})],
                         timing=[], children=[])
        self.delay = dict(seed='1', algorithm='java.util.Random; 1=min,2=max', pins_fs={}, cells_fs={'Top.history': '1000000'})
        (self.folder / 'delays.json').write_text(json.dumps(self.delay))
        (self.folder / 'testbench.sv').write_text('defparam dut.history.DELAY_FS=1000000;\n')

    def test_actual_defparam_matches_declared_seed(self):
        validate_delays(self.root, {'node': self.node})

    def test_metadata_only_delay_change_rejected(self):
        self.delay['cells_fs']['Top.history'] = '10000000'
        (self.folder / 'delays.json').write_text(json.dumps(self.delay))
        with self.assertRaisesRegex(ValueError, 'SEED_DELAY_BINDING'):
            validate_delays(self.root, {'node': self.node})

    def test_seed_one_must_be_minimum(self):
        self.delay['cells_fs']['Top.history'] = '10000000'
        (self.folder / 'delays.json').write_text(json.dumps(self.delay))
        (self.folder / 'testbench.sv').write_text('defparam dut.history.DELAY_FS=10000000;\n')
        with self.assertRaisesRegex(ValueError, 'SEED_DELAY_RANGE'):
            validate_delays(self.root, {'node': self.node})


class ElapsedCohortIdentityTests(unittest.TestCase):
    def setUp(self):
        self.document = dict(source_identity=dict(generation_log=dict(path='generation.log'),
            generation_window=dict(start_unix=100, end_unix=200)))
        self.times = {'generation.log': SimpleNamespace(st_birthtime=100, st_mtime=200),
                      'fresh': SimpleNamespace(st_birthtime=110), 'stale': SimpleNamespace(st_birthtime=90)}
        times = self.times
        mocked = patch.object(Path, 'stat', lambda p, *args, **kwargs: times[p.name])
        mocked.start(); self.addCleanup(mocked.stop)

    def test_explicit_manifest_accepts_same_generation(self):
        validate_cohort_identity(self.document, {'bd-normal': Path('fresh')})

    def test_stale_source_with_fresh_log_and_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'STALE_COHORT_SOURCE'):
            validate_cohort_identity(self.document, {'bd-normal': Path('stale')})

    def test_forged_recorded_window_is_rejected(self):
        self.document['source_identity']['generation_window']['start_unix'] = 80
        with self.assertRaisesRegex(ValueError, 'GENERATION_WINDOW_CHANGED'):
            validate_cohort_identity(self.document, {'bd-normal': Path('stale')})


if __name__ == '__main__':
    unittest.main()
