# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from desync_graph import compose, analyze, screen, reachable_stop


def topology():
    banks = ['cpu', 'fabric', 'power']
    return dict(banks=dict.fromkeys(banks), stop_bank='power', registers=[],
                phase_edges=[], gated_domains={}, edges=[dict(source=a, target=b, witnesses=[a + '->' + b])
                    for a in banks for b in banks])


class GraphTests(unittest.TestCase):
    def test_negative_only_bank_reverses_the_local_storage_link(self):
        p = topology()
        p['registers'] = [dict(bank=b, falling=b == 'fabric', transformed=True) for b in p['banks']]
        p['phase_edges'] = [dict(e, source_phase='fall' if e['source'] == 'fabric' else 'rise',
                                 target_phase='fall' if e['target'] == 'fabric' else 'rise', role='data') for e in p['edges']]
        g = compose(p, phase_aware=True)
        arcs = {(r['source'], r['target']): r['tokens'] for r in g['arcs']}
        self.assertEqual(arcs['fabric.s+', 'fabric.m+'], 0)
        self.assertEqual(arcs['fabric.s-', 'fabric.m-'], 1)
        self.assertTrue(reachable_stop(g, 'power.m-')['unique_rest_marking'])
        # A direct half-cycle cycle around a contracted FF has no bubble. The
        # MCU's CPU has no such path; an arbitrary bank selection must reject it.
        with self.assertRaisesRegex(ValueError, 'TOKENLESS_CYCLE'):
            analyze(compose(p, ['cpu'], phase_aware=True), 'power.m-')

    def test_exhaustive_stop_checks_every_reachable_marking_and_fails_closed(self):
        graph = compose(topology(), ['cpu'])
        result = reachable_stop(graph, 'power.m-')
        self.assertTrue(result['unique_rest_marking'])
        self.assertGreater(result['reachable_markings'], 1)
        self.assertGreater(result['maximum_firings_after_stop'], 0)
        self.assertFalse(result['control_wire_rest_proved'])
        self.assertEqual(result['rest_levels']['cpu.pulse'], 0)
        with self.assertRaisesRegex(ValueError, 'STATE_LIMIT'):
            reachable_stop(graph, 'power.m-', limit=1)

    def test_same_phase_cones_and_gate_hold_have_distinct_relations(self):
        p = topology()
        p['phase_edges'] = [dict(e, source_phase='rise', target_phase='rise', role='data') for e in p['edges']]
        p['phase_edges'] += [dict(source='power', source_phase='fall', target='cpu', target_phase='rise',
                                  role='gate', witnesses=['cpu/state']),
                             dict(source='power', source_phase='rise', target='power', target_phase='fall',
                                  role='data', witnesses=['power/enabled'])]
        g = compose(p, ['cpu'], phase_aware=True)
        arcs = {(r['source'], r['target']): r['tokens'] for r in g['arcs']}
        self.assertEqual(arcs['power.m-', 'cpu.rise'], 0)
        self.assertEqual(arcs['cpu.fall', 'power.m+'], 0)
        self.assertNotIn(('power.m+', 'cpu.fall'), arcs)
        self.assertTrue(g['transparent_cones'])
        self.assertTrue(reachable_stop(g, 'power.m-')['unique_rest_marking'])
        p['phase_edges'][-2]['source'] = '@external'
        with self.assertRaisesRegex(ValueError, 'EXTERNAL_GATE_QUALIFIER'):
            compose(p, ['cpu'], phase_aware=True)

    def test_macro_access_is_after_master_closes(self):
        p = topology(); p['macros'] = [dict(bank='fabric')]
        p['phase_edges'] = [dict(e, source_phase='rise', target_phase='rise', role='data') for e in p['edges']]
        p['phase_edges'].append(dict(source='fabric', source_phase='fall', target='fabric', target_phase='macro',
                                    role='macro_input', witnesses=['fabric/macro/A']))
        g = compose(p, ['cpu'], phase_aware=True)
        arcs = {(r['source'], r['target']): r['tokens'] for r in g['arcs']}
        self.assertEqual(arcs['fabric.m-', 'fabric.s+'], 0)
        self.assertFalse(any('fabric/macro/A' in c['witnesses'] for c in g['transparent_cones']))

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
        part.update(registers=[dict(transformed=True, falling=True, bank='power')],
                    gated_domains={'work': 'power.enable'},
                    phase_edges=[dict(source_phase='macro', target_phase='rise')])
        report = screen(part, ['cpu'])
        self.assertEqual(report['status'], 'incomplete')
        for obligation in ('opposite-phase', 'enable gating', 'macro access', 'FF setup/hold'):
            self.assertTrue(any(obligation in item for item in report['unresolved']))


if __name__ == '__main__':
    unittest.main()
