# SPDX-License-Identifier: Apache-2.0
"""Cost-clock classification follows Liberty semantics and actual connectivity."""
import unittest

from gf180_netgraph import periodic_loads
from gf180_physical import SC


class ClockLoadAccounting(unittest.TestCase):
    def test_inverted_clock_pin_is_counted_after_real_clock_buffering(self):
        flop = SC + 'dffnq_1'
        latch = SC + 'latq_1'
        library = {
            SC + 'inv_1': 'pin(I) { direction : input; capacitance : 0.9; }',
            flop: 'pin(CLKN) { clock : true; capacitance : 0.25; }',
            latch: 'pin(E) { clock : true; capacitance : 0.35; }',
        }
        modules = {'RiscayMcuDigital': {
            'ports': {},
            'netnames': {n: {'bits': [b]} for n, b in (
                ('serviceClock', 1), ('watchdogClock', 2), ('sda', 3),
                ('soc/gate_io_clockOut', 4))},
            'cells': {
                'invert': {'type': SC + 'inv_1', 'connections': {'I': [4], 'ZN': [5]}},
                'negative': {'type': flop, 'connections': {'CLKN': [5]}},
                'host': {'type': flop, 'connections': {'CLKN': [3]}},
                'native': {'type': latch, 'connections': {'E': [6]}},
            },
        }}
        loads = periodic_loads(modules, library)
        self.assertEqual(loads['work'], {'storage_cells': 1, 'clock_input_pf': 0.25})
        self.assertEqual(loads['host'], {'storage_cells': 1, 'clock_input_pf': 0.25})
        self.assertEqual(loads['native_or_other'], {'storage_cells': 1, 'clock_input_pf': 0.35})
        # A source reconnection must change the classification, not the total.
        modules['RiscayMcuDigital']['cells']['invert']['connections']['I'] = [1]
        rewired = periodic_loads(modules, library)
        self.assertEqual(rewired['work']['storage_cells'], 0)
        self.assertEqual(rewired['service'], loads['work'])
        self.assertEqual(sum(v['clock_input_pf'] for v in loads.values()),
                         sum(v['clock_input_pf'] for v in rewired.values()))


if __name__ == '__main__':
    unittest.main()
