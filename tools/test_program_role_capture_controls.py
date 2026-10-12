# SPDX-License-Identifier: Apache-2.0
"""Focused fail-closed policy checks for composed program role/capture evidence."""
import copy
import re
import unittest

from check_program_role_capture_controls import (
    CAPTURES, PREFIX, assertion_sites, classify_result, instrument, mutation,
    resolve_node, role_monitors, skew)


def fixture_nodes(variant='bd'):
    top = 'Root'
    owner = dict(module='ProgramSource', rtl_path=top + '.source', children=[],
                 endpoints=[dict(id=n, rtl_path=top + '.source.' + n) for n in
                     ('owner_loader', 'reserved', 'eligible', 'cpu_presentation_permit')],
                 primitives=[dict(id=n, rtl_path=top + '.source.' + n,
                                  parameters={'WIDTH': '1', 'DELAY_FS': '1000000'})
                             for n in ('owned', 'armed_phase', 'eligibility')])
    returned = dict(module='ProgramReturn', rtl_path=top + '.returned', children=[],
                    endpoints=[dict(id=n, rtl_path=top + '.returned.' + n) for n in ('eligible', 'idle')],
                    primitives=[])
    for n in set(CAPTURES[variant]) | set(CAPTURES[variant].values()):
        returned['primitives'].append(dict(id=n, rtl_path=top + '.returned.' + n,
            parameters={'WIDTH': '32' if n == 'payload' else '1', 'DELAY_FS': '1000000'}))
    return owner, returned


BENCH = '''module Testbench;
timeunit 1ns; timeprecision 1ps;
initial begin
  #25;
  if(existing_bad) $fatal(1,"EXISTING_ASSERTION");
  $display("RISCAY_SOC_PASS");
end
endmodule
'''


class RoleCapturePolicyTests(unittest.TestCase):
    def test_original_oracle_and_time_units_preserved(self):
        owner, returned = fixture_nodes()
        result = instrument(BENCH, owner, returned, 'bd', 'roles')
        original = result[:result.index('\nmodule ProgramRoleCaptureChecks;')]
        original = original.replace('ProgramRoleCaptureChecks program_role_checks();\n', '')
        original = original.replace('program_role_checks.finish_checks();\n', '')
        self.assertEqual(original, BENCH)
        self.assertEqual(result.count('timeunit 1fs; timeprecision 1fs;'), 1)
        self.assertIn('#25;', result)
        self.assertIn('$fatal(1,"EXISTING_ASSERTION");', result)

    def test_monitor_tracks_driver_role_at_actual_acceptance(self):
        owner, returned = fixture_nodes('click')
        result = role_monitors(owner, returned, 'click')
        self.assertIn('posedge Testbench.observedWorkClock', result)
        self.assertIn('!Testbench.reset && Testbench.wordAccepted', result)
        self.assertIn('role_loader=Testbench.loaderWordPending;', result)
        self.assertNotRegex(result, r'role_loader=Testbench\.dut\.')
        self.assertIn('posedge Testbench.systemReset', result)
        self.assertIn('role_cancelled=1;', result)
        self.assertIn('Testbench.dut.source.armed_phase.q[0] === Testbench.dut.source.reserved', result)
        self.assertIn('Testbench.dut.source.owner_loader !== role_loader', result)

    def test_each_register_uses_its_own_reset_and_checks_actual_q(self):
        for variant in CAPTURES:
            owner, returned = fixture_nodes(variant)
            text = role_monitors(owner, returned, variant)
            for name in CAPTURES[variant]:
                path = 'Testbench.dut.returned.' + name
                with self.subTest(variant=variant, register=name):
                    self.assertIn(f'posedge {path}.reset', text)
                    self.assertIn(f'if({path}.reset === 1\'b0)', text)
                    self.assertIn(f'if({path}.q !== data)', text)
                    self.assertIn(f'if((^{path}.d) === 1\'bx)', text)
                    self.assertIn(f'q_{name}_reset==reset_epoch', text)
                    self.assertIn(f'q_{name}_capture==capture_epoch', text)
                    self.assertNotIn(f'posedge {path}.trigger) if(!Testbench.systemReset)', text)

    def test_permission_expectation_is_sampled_before_delta_and_own_reset_invalidates_it(self):
        owner, returned = fixture_nodes()
        text = role_monitors(owner, returned, 'bd')
        section = text[text.rindex('always @(posedge Testbench.dut.returned.permission.trigger) if'):]
        self.assertLess(section.index('expected_permission='), section.index('#1;'))
        self.assertLess(section.index('permission_reset_epoch=q_permission_reset;'), section.index('#1;'))
        self.assertIn("Testbench.dut.returned.permission.reset === 1'b0 && q_permission_reset==permission_reset_epoch", section)
        self.assertIn('captured_permission !== expected_permission', section)

    def test_skew_changes_only_variable_cells_and_preserves_guard_overrides(self):
        owner, returned = fixture_nodes()
        returned['primitives'].append(dict(id='output_guard', rtl_path='Root.returned.guard',
                                          parameters={'DELAY_FS': '200000000'}))
        owner['primitives'].append(dict(id='data_delay', rtl_path='Root.source.data',
                                       parameters={'DELAY_FS': '10000000'}))
        original = BENCH.replace('initial begin',
            'defparam dut.returned.guard.DELAY_FS=200000000;\n'
            'defparam dut.source.data.DELAY_FS=10000000;\n'
            'defparam dut.source.eligibility.DELAY_FS=9000000;\ninitial begin')
        result, changes = skew(original, owner, returned, 'source-slow-return-fast')
        self.assertIn('defparam dut.returned.guard.DELAY_FS=200000000;', result)
        self.assertIn('defparam dut.source.data.DELAY_FS=10000000;', result)
        self.assertEqual(changes['dut.source.eligibility.DELAY_FS'], dict(before='9000000', after='10000000'))
        self.assertEqual(changes['dut.returned.payload.DELAY_FS']['after'], '1000000')
        self.assertLess(result.index('timeunit 1ns'), result.index('defparam'))
        self.assertEqual(skew(original, owner, returned, 'original'), (original, {}))

    def test_unknown_profile_and_duplicate_delays_rejected(self):
        owner, returned = fixture_nodes()
        with self.assertRaises(ValueError):
            skew(BENCH, owner, returned, 'best-case-only')
        delay = 'defparam dut.source.eligibility.DELAY_FS=1000000;\n'
        with self.assertRaises(ValueError):
            skew(BENCH.replace('initial begin', delay + delay + 'initial begin'), owner, returned, 'source-slow-return-fast')

    def test_reference_resolution_requires_exact_owner(self):
        node = dict(rtl_path='Root.returned', endpoints=[dict(id='eligible', probe='probe')], children=[])
        resolved = resolve_node(node, 'Root', {'ref_Root_probe': 'returned.actual'})
        self.assertEqual(resolved['endpoints'][0]['rtl_path'], 'Root.returned.actual')
        self.assertNotIn('rtl_path', node['endpoints'][0])
        for refs in ({}, {'ref_Root_probe': 'source.actual'}):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                resolve_node(node, 'Root', refs)

    def test_actual_fatal_line_and_appended_module_scope_are_bound(self):
        owner, returned = fixture_nodes()
        test = instrument(BENCH, owner, returned, 'bd', 'roles')
        sites = assertion_sites(test, [PREFIX + '_SETUP:payload'])
        self.assertEqual(len(sites), 1)
        site = sites[0]
        self.assertIn('$fatal(1,"' + site['message'] + '")', test.splitlines()[site['line'] - 1])
        self.assertEqual(site['scope'], 'Testbench.program_role_checks')
        log = f"FATAL: testbench.sv:{site['line']}: {site['message']}\n       Time: 9  Scope: {site['scope']}\n"
        self.assertEqual(len(classify_result({'exit_code': 0}, {'exit_code': 1}, log, sites)), 1)
        for bad in (log.replace('testbench.sv:', 'other.sv:'), log.replace(site['scope'], 'Testbench'),
                    log.replace(site['message'], 'UNRELATED'), log + 'RISCAY_SOC_PASS\n',
                    log + log.replace(site['message'], 'UNRELATED'), site['message'],
                    log + 'SOC_DEADLINE\n'):
            with self.subTest(log=bad), self.assertRaises(ValueError):
                classify_result({'exit_code': 0}, {'exit_code': 1}, bad, sites)

    def test_positive_compile_exit_pass_marker_and_timeout_required(self):
        self.assertEqual(classify_result({'exit_code': 0}, {'exit_code': 0}, 'RISCAY_SOC_PASS\n'), [])
        for compiled, simulated, log in (
            ({'exit_code': 1}, {'exit_code': 0}, 'RISCAY_SOC_PASS\n'),
            ({'exit_code': 0}, {'exit_code': 1}, 'RISCAY_SOC_PASS\n'),
            ({'exit_code': 0}, {'exit_code': 0, 'timed_out': True}, 'RISCAY_SOC_PASS\n'),
            ({'exit_code': 0}, {'exit_code': 0}, ''),
            ({'exit_code': 0}, {'exit_code': 0}, 'RISCAY_SOC_PASS\nRISCAY_SOC_PASS\n'),
            ({'exit_code': 0}, {'exit_code': 0}, 'RISCAY_SOC_PASS\nFATAL: other.sv:1: TARGET\n')):
            with self.subTest(log=log), self.assertRaises(ValueError):
                classify_result(compiled, simulated, log)

    def test_mutations_are_actual_register_pins_with_exact_diagnostics(self):
        node = dict(module='ProgramReturn', primitives=[dict(id='permission', rtl_path='Root.returned.capture',
                                                          parameters={'WIDTH': '1'})])
        rtl = '''module ProgramReturn(input reset, input fire, input data, output value);
ChiselAsyncEventRegister_v1 capture (
  .reset(reset),
  .trigger(fire),
  .d(data),
  .q(value)
);
endmodule
'''
        changed, expected = mutation(rtl, node, 'permission', 'role-data')
        self.assertEqual(expected, PREFIX + '_PERMISSION_DATA')
        self.assertIn(".d(1'b1)", changed)
        self.assertIn('.trigger(fire)', changed)
        for kind, diagnostic in (('setup', 'SETUP'), ('hold', 'HOLD'), ('high', 'PULSE_HIGH'),
                                 ('low', 'PULSE_LOW'), ('skew', 'SKEW')):
            changed, expected = mutation(rtl, node, 'permission', kind)
            self.assertNotEqual(changed, rtl)
            self.assertEqual(expected, PREFIX + '_' + diagnostic + ':permission')
        changed, expected = mutation(rtl, node, 'permission', 'legal-skew')
        self.assertIsNone(expected)
        self.assertIn('assign #100000 role_test_clock = fire;', changed)


if __name__ == '__main__':
    unittest.main()
