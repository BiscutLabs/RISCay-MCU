# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from desync_graph import compose, analyze, screen


def topology():
    banks = ['cpu', 'fabric', 'power']
    return dict(banks=dict.fromkeys(banks), stop_bank='power', registers=[],
                phase_edges=[], gated_domains={}, edges=[dict(source=a, target=b, witnesses=[a + '->' + b])
                    for a in banks for b in banks])


class GraphTests(unittest.TestCase):
    def test_latch_pairs_and_one_ff_bank_keep_a_token_and_bubble(self):
        for flops in ([], ['cpu']):
            part = topology()
            result = analyze(compose(part, flops), 'power.m-')
            self.assertTrue(result['live'] and result['one_safe'])
            self.assertFalse(result['handshake_rest_proved'])
            self.assertIsNone(result['cycle_time_ns'])
            if flops:
                self.assertTrue(compose(part, flops)['aperture_obligations'])

    def test_adjacent_flop_banks_reject_tokenless_cycle(self):
        with self.assertRaisesRegex(ValueError, 'TOKENLESS_CYCLE'):
            analyze(compose(topology(), ['cpu', 'fabric']), 'power.m-')

    def test_removed_token_and_disconnected_stop_are_detected(self):
        marked = compose(topology())
        for row in marked['arcs']:
            if row['source'] == 'cpu.m+' and row['target'] == 'cpu.m-':
                row['tokens'] = 0
        with self.assertRaisesRegex(ValueError, 'TOKENLESS_CYCLE'):
            analyze(marked, 'power.m-')
        part = topology()
        part['edges'] = [e for e in part['edges'] if e['source'] == e['target']]
        with self.assertRaisesRegex(ValueError, 'NOT_STRONGLY_CONNECTED'):
            analyze(compose(part), 'power.m-')

    def test_unknown_bank_missing_witness_and_duplicate_place_fail(self):
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_FLOP_BANK'):
            compose(topology(), ['missing'])
        part = topology(); part['edges'][0]['witnesses'] = []
        with self.assertRaisesRegex(ValueError, 'UNWITNESSED_DEPENDENCY'):
            compose(part)
        marked = compose(topology()); marked['arcs'].append(deepcopy(marked['arcs'][0]))
        with self.assertRaisesRegex(ValueError, 'INVALID_MARKED_GRAPH'):
            analyze(marked, 'power.m-')

    def test_mixed_edge_projection_never_qualifies_the_mcu(self):
        part = topology()
        part.update(registers=[dict(transformed=True, falling=True)],
                    gated_domains={'work': 'power.enable'},
                    phase_edges=[dict(source_phase='macro', target_phase='rise')])
        report = screen(part, ['cpu'])
        self.assertEqual(report['status'], 'incomplete')
        for obligation in ('opposite-phase', 'enable gating', 'macro access', 'FF setup/hold'):
            self.assertTrue(any(obligation in item for item in report['unresolved']))


if __name__ == '__main__':
    unittest.main()
