# SPDX-License-Identifier: Apache-2.0
import copy
import unittest

from reset_bridge_proof import Cone
from reset_coordinator_proof import helper, receipt, register, transition, work_clock


class ResetCoordinatorTest(unittest.TestCase):
    def fixture(self):
        cell = dict(type='$adff', parameters=dict(ARST_VALUE='0', ARST_POLARITY='1',
                    CLK_POLARITY='1', WIDTH='1'),
                    port_directions=dict(D='input', Q='output', ARST='input', CLK='input'),
                    connections=dict(D=[5], Q=[6], ARST=[2], CLK=[3]))
        return dict(cells=dict(ack=cell), netnames=dict(closed=dict(bits=[6])))

    def test_receipt_requires_actual_edge_and_exact_control(self):
        baseline = self.fixture()
        self.assertEqual(receipt(Cone(baseline), 'closed', [3], [2], [5]), ('ack', [6]))
        for field, replacement in (('D', [7]), ('CLK', [4]), ('ARST', [4])):
            changed = copy.deepcopy(baseline)
            changed['cells']['ack']['connections'][field] = replacement
            with self.assertRaisesRegex(ValueError, 'RDC_COORDINATOR_(RECEIPT|REGISTER)_closed'):
                receipt(Cone(changed), 'closed', [3], [2], [5])
        changed = copy.deepcopy(baseline)
        changed['netnames']['closed']['bits'] = [5]
        with self.assertRaisesRegex(ValueError, 'RDC_BRIDGE_REGISTER_closed'):
            receipt(Cone(changed), 'closed', [3], [2], [5])

    def test_receipt_cannot_start_acknowledged_or_use_wrong_polarity(self):
        for parameter, replacement in (('ARST_VALUE', '1'), ('ARST_POLARITY', '0'),
                                       ('CLK_POLARITY', '0')):
            changed = self.fixture()
            changed['cells']['ack']['parameters'][parameter] = replacement
            with self.assertRaisesRegex(ValueError, 'RDC_COORDINATOR_REGISTER_closed'):
                register(Cone(changed), 'closed', [3], [2], 1, 0)

    def test_inline_and_ordinary_clock_aliases_require_actual_gate_equation(self):
        for alias in ('workClock', 'gate_io_clockOut', 'fabric_clock'):
            module = dict(netnames={name: dict(bits=[bit]) for name, bit in
                          [('serviceClock', 2), ('gate_enabled', 3), (alias, 4)]},
                          cells=dict(gate=dict(type='$and', parameters={},
                          port_directions=dict(A='input', B='input', Y='output'),
                          connections=dict(A=[2], B=[3], Y=[4]))))
            self.assertEqual(work_clock(Cone(module)), [4])
            changed = copy.deepcopy(module)
            changed['cells']['gate']['type'] = '$or'
            with self.assertRaisesRegex(ValueError, 'RDC_COORDINATOR_WORK_CLOCK_EQUATION'):
                work_clock(Cone(changed))
            changed = copy.deepcopy(module)
            other = 'workClock' if alias != 'workClock' else 'fabric_clock'
            changed['netnames'][other] = dict(bits=[5])
            with self.assertRaisesRegex(ValueError, 'RDC_COORDINATOR_WORK_CLOCK_ALIASES'):
                work_clock(Cone(changed))

    def test_anonymous_helper_requires_its_complete_truth_table(self):
        cell = lambda kind, output: dict(type=kind, parameters={},
            port_directions=dict(A='input', B='input', Y='output'),
            connections=dict(A=[2], B=[3], Y=[output]))
        module = dict(netnames={'resetBoundary_': dict(bits=[4]),
                               'resetBoundary__4': dict(bits=[5])},
                      cells=dict(correct=cell('$and', 4), wrong=cell('$or', 5)))
        rows = [({2: a, 3: b}, a and b) for a in range(2) for b in range(2)]
        self.assertEqual(helper(Cone(module), rows, 'TEST_JOIN'), [4])
        changed = copy.deepcopy(module)
        changed['cells']['correct']['type'] = '$or'
        with self.assertRaisesRegex(ValueError, 'RDC_COORDINATOR_TEST_JOIN'):
            helper(Cone(changed), rows, 'TEST_JOIN')
        changed = copy.deepcopy(module)
        changed['cells']['wrong']['type'] = '$and'
        with self.assertRaisesRegex(ValueError, 'RDC_COORDINATOR_TEST_JOIN'):
            helper(Cone(changed), rows, 'TEST_JOIN')

    def test_closing_retains_native_producers_until_receipts_arrive(self):
        state = transition(1, 1, 0, 0, 0, 0, 1, 0, 1, 0)
        self.assertEqual(state, dict(state=1, stopped=1, nativeHeld=0, coreHeld=0, rebasing=0, count=0))
        state = transition(1, 1, 0, 0, 0, 0, 1, 1, 1, 0)
        self.assertEqual(state, dict(state=2, stopped=1, nativeHeld=1, coreHeld=1, rebasing=1, count=0))

    def test_hold_restarts_and_core_stays_held_until_withdrawal(self):
        blocked = transition(2, 1, 1, 1, 1, 63, 0, 1, 1, 0)
        self.assertEqual((blocked['count'], blocked['nativeHeld'], blocked['rebasing']), (0, 1, 1))
        released = transition(2, 1, 1, 1, 1, 63, 0, 1, 0, 0)
        self.assertEqual(released, dict(state=3, stopped=1, nativeHeld=0, coreHeld=1, rebasing=0, count=0))
        waiting = transition(3, 1, 0, 1, 0, 63, 0, 1, 1, 0)
        self.assertEqual((waiting['state'], waiting['stopped'], waiting['coreHeld']), (3, 1, 1))
        reopened = transition(3, 1, 0, 1, 0, 63, 0, 1, 1, 1)
        self.assertEqual((reopened['state'], reopened['stopped'], reopened['coreHeld']), (0, 0, 0))

    def test_retrigger_wins_over_reopening_without_early_native_reset(self):
        retry = transition(3, 1, 0, 1, 0, 63, 1, 1, 1, 1)
        self.assertEqual(retry, dict(state=1, stopped=1, nativeHeld=0, coreHeld=1, rebasing=0, count=0))


if __name__ == '__main__':
    unittest.main()
