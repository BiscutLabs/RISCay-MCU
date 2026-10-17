# SPDX-License-Identifier: Apache-2.0
"""Negative graph and arithmetic controls for the isolated A7b candidate."""
from copy import deepcopy
import unittest

from experiment_elapsed_guard import SC, narrow_chain, module_verilog, sensitivity, propose_count


def fixture():
    def cell(kind, **pins):
        return dict(type=SC + kind, connections={p: [b] for p, b in pins.items()},
                    parameters={}, port_directions={p: 'output' if p in ('Z', 'ZN') else 'input' for p in pins})
    return dict(ports={p: dict(direction='output' if p == 'q' else 'input', bits=[b])
                       for p, b in dict(reset=1, a=2, q=9).items()}, cells={
        'u0': cell('inv_1', I=1, ZN=3), 'u1': cell('and2_1', A1=2, A2=3, Z=4),
        'u2': cell('dlyd_1', I=4, Z=5), 'u3': cell('dlyd_1', I=5, Z=6),
        'u4': cell('dlyd_1', I=6, Z=7), 'u5': cell('dlyd_1', I=7, Z=9)})


def case(data=10., request=50., setup=1.):
    return dict(aperture=dict(setup_ns=setup), summary=dict(lanes=[dict(lane=0, maximum_input_data_lag_ns=request-data-setup)]),
                results={'data': {'rows': {f'data:0:max:{e}': dict(delay_ns=data) for e in ('rise', 'fall')}},
                         'request-0': {'rows': {'capture:0:min:rise': dict(delay_ns=request)}}})


class ChainControls(unittest.TestCase):
    def test_only_interior_delays_removed(self):
        original = fixture(); before = deepcopy(original)
        after, ordered, removed = narrow_chain(original, 2)
        self.assertEqual(original, before)
        self.assertEqual(ordered, ['u2', 'u3', 'u4', 'u5'])
        self.assertEqual(removed, ['u3', 'u4'])
        self.assertEqual(after['cells']['u5']['connections'], dict(I=[5], Z=[9]))
        self.assertEqual(after['cells']['u0'], original['cells']['u0'])
        self.assertEqual(after['cells']['u1'], original['cells']['u1'])
        text = module_verilog('guard', after)
        self.assertIn('dlyd_1 u5(.I(a7_n5), .Z(q))', text)
        self.assertNotIn('dlyd_1 u3', text)

    def test_terminal_cell_survives_single_delay(self):
        after, _, removed = narrow_chain(fixture(), 1)
        self.assertEqual(removed, ['u2', 'u3', 'u4'])
        self.assertEqual(after['cells']['u5']['connections'], dict(I=[4], Z=[9]))

    def test_no_op_preserves_graph(self):
        after, _, removed = narrow_chain(fixture(), 4)
        self.assertEqual(after, fixture()); self.assertEqual(removed, [])

    def test_invalid_count(self):
        for count in (0, -1, 5, 1.5, True):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'A7_CHAIN_COUNT'):
                narrow_chain(fixture(), count)

    def test_reset_mask_is_not_removable(self):
        bad = fixture(); bad['cells']['u1']['connections']['A2'] = [2]
        with self.assertRaisesRegex(ValueError, 'A7_RESET_AND_ENDPOINT'):
            narrow_chain(bad, 2)

    def test_branch_rejected(self):
        bad = fixture(); bad['cells']['u4']['connections']['I'] = [5]
        with self.assertRaisesRegex(ValueError, 'A7_CHAIN_BRANCH_OR_CYCLE'):
            narrow_chain(bad, 2)

    def test_cycle_rejected(self):
        bad = fixture(); bad['cells']['u4']['connections']['Z'] = [5]
        with self.assertRaisesRegex(ValueError, 'A7_CHAIN_BRANCH_OR_CYCLE'):
            narrow_chain(bad, 2)

    def test_terminal_not_output_rejected(self):
        bad = fixture(); bad['ports']['q']['bits'] = [7]
        with self.assertRaisesRegex(ValueError, 'A7_CHAIN_TERMINUS'):
            narrow_chain(bad, 2)

    def test_added_logic_rejected(self):
        bad = fixture(); bad['cells']['other'] = deepcopy(bad['cells']['u0'])
        with self.assertRaisesRegex(ValueError, 'A7_CHAIN_RECIPE'):
            narrow_chain(bad, 2)

    def test_mismatch_penalizes_both_paths(self):
        self.assertEqual(sensitivity(case(), .1)['slack_ns'], 33.)
        self.assertLess(sensitivity(case(request=12.), .1)['slack_ns'], 0.)

    def test_same_corner_count_not_cross_corner_extrema(self):
        # Both corners have the same data/request ratio. Combining slow data
        # with fast request would incorrectly demand the original full chain.
        count, rows = propose_count({'fast': case(), 'slow': case(100., 500., 10.)}, 100, 0.)
        self.assertEqual(count, 22); self.assertEqual([r['count'] for r in rows], [22, 22])

    def test_late_data_changes_proposal(self):
        low, _ = propose_count({'fast': case()}, 100, .15)
        high, _ = propose_count({'fast': case(data=20.)}, 100, .15)
        self.assertGreater(high, low)


if __name__ == '__main__':
    unittest.main()
