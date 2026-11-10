# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from desync_partition import partition


def fixture():
    def ff(clock, data, q, falling=False):
        return dict(type='$dff', parameters={'CLK_POLARITY': '0' if falling else '1'},
                    connections=dict(CLK=[clock], D=[data], Q=[q]),
                    port_directions=dict(CLK='input', D='input', Q='output'))
    ports = {name: dict(direction='input', bits=[bit]) for name, bit in
             [('serviceClock', 1), ('workClock', 2), ('input', 3)]}
    wires = {name: dict(bits=p['bits']) for name, p in ports.items()}
    wires.update(enable=dict(bits=[7]), cpuQ=dict(bits=[5]), fabricQ=dict(bits=[6]))
    module = dict(ports=ports, netnames=wires, cells={
        'cpu': ff(2, 6, 5), 'fabric': ff(2, 5, 6), 'power': ff(1, 3, 7, True)})
    policy = dict(top='chip', banks=['cpu', 'fabric', 'power'], stop_bank='power',
                  clock_roots={'serviceClock': 'service', 'workClock': 'work'},
                  retained_domains=['lf', 'host_event'], gated_domains={'work': 'enable'},
                  rules=[dict(prefix=b, bank=b) for b in ['cpu', 'fabric', 'power']])
    return dict(modules={'chip': module}), policy


class PartitionTests(unittest.TestCase):
    def test_falling_gate_uses_the_existing_previous_register(self):
        n, p = fixture(); c = n['modules']['chip']['cells']
        previous = deepcopy(c['power'])
        previous['parameters']['CLK_POLARITY'] = '1'
        previous['connections'] = dict(CLK=[1], D=[7], Q=[8])
        c['powerPrevious'] = previous
        n['modules']['chip']['netnames']['previous'] = dict(bits=[8])
        p['falling_gate_conditions'] = {'work': 'previous'}
        c['fabric']['parameters']['CLK_POLARITY'] = '0'
        result = partition(n, p)
        self.assertEqual(result['gate_bindings']['work']['previous'], 'powerPrevious')
        self.assertTrue(any(e['role'] == 'falling_gate' and e['source_phase'] == 'rise' and
                            e['target_phase'] == 'fall' for e in result['phase_edges']))
        # Choosing current enabled instead of its history looks plausible in a
        # graph but inserts/drops a falling capture when the work gate changes.
        for mutate, diagnostic in [
            (lambda n, p: p['falling_gate_conditions'].update(work='enable'), 'HISTORY_RELATION'),
            (lambda n, p: n['modules']['chip']['cells']['powerPrevious']['connections'].update(D=[3]), 'HISTORY_RELATION'),
            (lambda n, p: p['gated_domains'].update(work='missing'), 'GATE_CONDITION'),
        ]:
            bad, policy = deepcopy(n), deepcopy(p); mutate(bad, policy)
            with self.subTest(diagnostic=diagnostic), self.assertRaisesRegex(ValueError, diagnostic):
                partition(bad, policy)

    def test_unregistered_stateful_generic_cell_is_not_combinational(self):
        for kind in ('$sr', '$fsm', '$anyseq', '$future_state'):
            netlist, policy = fixture()
            netlist['modules']['chip']['cells']['cpu']['type'] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'UNSUPPORTED_CELL'):
                partition(netlist, policy)

    def test_gate_dependency_keeps_source_polarity_and_receiving_registers(self):
        netlist, policy = fixture()
        result = partition(netlist, policy)
        gates = [e for e in result['phase_edges'] if e['role'] == 'gate']
        self.assertEqual({e['target'] for e in gates}, {'cpu', 'fabric'})
        self.assertTrue(all(e['source'] == 'power' and e['source_phase'] == 'fall' for e in gates))
        self.assertFalse(any('power' in e['witnesses'] for e in gates))
        self.assertEqual(sum(b['bits'] for b in result['banks'].values()),
                         sum(r['bits'] for r in result['registers']))

    def test_hierarchical_aliases_are_net_connections_not_name_guesses(self):
        netlist, policy = fixture()
        root = netlist['modules']['chip']
        original = root['cells'].pop('cpu')
        sub = dict(ports=dict(clock=dict(bits=[10], direction='input'), d=dict(bits=[11], direction='input'),
                             q=dict(bits=[12], direction='output')), netnames={},
                   cells={'state': dict(original, connections=dict(CLK=[10], D=[11], Q=[12]))})
        netlist['modules']['child'] = sub
        root['cells']['cpu'] = dict(type='child', connections=dict(clock=[2], d=[6], q=[5]))
        result = partition(netlist, policy)
        self.assertIn('cpu/state', [r['path'] for r in result['registers']])
        self.assertTrue(any(e['source'] == 'fabric' and e['target'] == 'cpu' for e in result['edges']))

    def test_event_clock_inversion_remains_an_external_frontier(self):
        netlist, policy = fixture()
        root = netlist['modules']['chip']
        policy['clock_roots']['input'] = 'host_event'
        root['cells']['invert'] = dict(type='$not', connections=dict(A=[3], Y=[9]),
                                      port_directions=dict(A='input', Y='output'))
        root['cells']['power']['connections']['CLK'] = [9]
        result = partition(netlist, policy)
        event = next(r for r in result['registers'] if r['path'] == 'power')
        self.assertFalse(event['transformed'])
        self.assertEqual(event['domain'], 'host_event')
        self.assertTrue(any(e['source'] == '@host_event' for e in result['external']))

    def test_unassigned_unknown_clock_and_undriven_data_fail(self):
        for mutate, diagnostic in [
            (lambda n, p: p['rules'].pop(0), 'UNASSIGNED_REGISTER'),
            (lambda n, p: n['modules']['chip']['cells']['cpu']['connections'].update(CLK=[99]), 'UNCLASSIFIED_CLOCK'),
            (lambda n, p: n['modules']['chip']['cells']['cpu']['connections'].update(D=[99]), 'UNDRIVEN_INPUT'),
            (lambda n, p: p['gated_domains'].update(work='missing'), 'GATE_CONDITION'),
        ]:
            n, p = fixture(); mutate(n, p)
            with self.subTest(diagnostic=diagnostic), self.assertRaisesRegex(ValueError, diagnostic):
                partition(n, p)

    def test_conflicting_root_and_duplicate_driver_fail(self):
        netlist, policy = fixture()
        netlist['modules']['chip']['netnames']['aliasClock'] = dict(bits=[1])
        policy['clock_roots']['aliasClock'] = 'other'
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_CLOCK_ROOTS'):
            partition(netlist, policy)
        netlist, policy = fixture()
        netlist['modules']['chip']['cells']['cpu2'] = deepcopy(netlist['modules']['chip']['cells']['cpu'])
        with self.assertRaisesRegex(ValueError, 'MULTIPLE_STORAGE_DRIVERS'):
            partition(netlist, policy)


if __name__ == '__main__':
    unittest.main()
