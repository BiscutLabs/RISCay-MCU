# SPDX-License-Identifier: Apache-2.0
import copy
import unittest

from gf180_physical import SC, SRAM
from report_clock_owners import ROOTS, inventory


def cell(kind, **pins):
    return dict(type=SC + kind, connections={p: [b] for p, b in pins.items()},
                port_directions={p: 'output' if p in ('Q', 'Z', 'ZN') else 'input' for p in pins})


class ClockOwnerInventory(unittest.TestCase):
    def setUp(self):
        self.aliases = {name: [i] for i, name in enumerate(ROOTS)}
        self.cells = {'soc/repair': cell('buf_4', I=1, Z=10),
                      'soc/reg': cell('dffrnq_1', CLK=10, Q=11, D=12),
                      'soc/ca_child_native/reg': cell('dffrnq_1', CLK=20, Q=21, D=22),
                      'soc/ca_child_receipt/reg': cell('dffrnq_1', CLK=0, Q=31, D=32)}
        self.aliases['soc/fabric_application_0'] = [11]
        # A consumer alias must never reattribute the native producer.
        self.aliases['soc/fabric_native_view'] = [21]
        self.aliases['soc/fabric_receipt_view'] = [31]
        self.pins = {SC + 'dffrnq_1': {'CLK': 0.003}, SC + 'buf_4': {}}

    def test_counts_follow_real_roots_and_local_ownership(self):
        r = inventory(self.cells, self.aliases, self.pins)
        self.assertEqual(r['periodic_sinks'], 2)
        self.assertEqual(r['owners']['Services']['work'], 1)
        self.assertEqual(r['owners']['soc/ca_child_receipt']['service'], 1)
        self.assertNotIn('soc/ca_child_native', r['owners'])
        self.assertEqual([x['path'] for x in r['other_clock_sinks']], ['soc/ca_child_native/reg'])
        self.assertEqual(sum(sum(v.values()) for v in r['owners'].values()),
                         sum(r['clock_domains'].values()))

    def test_repair_output_buffers_do_not_lose_original_owner(self):
        original = copy.deepcopy(self.cells)
        self.cells['soc/reg']['connections']['Q'] = [99]
        self.cells['soc/output_repair'] = cell('buf_4', I=99, Z=11)
        r = inventory(self.cells, self.aliases, self.pins, original, self.aliases)
        self.assertEqual(r['owners']['Services']['work'], 1)
        self.cells['soc/added_register'] = cell('dffrnq_1', CLK=10, Q=101, D=12)
        with self.assertRaisesRegex(ValueError, 'ADDED_SEQUENTIAL_CELL'):
            inventory(self.cells, self.aliases, self.pins, original, self.aliases)

    def test_sram_and_host_event_are_separate_from_periodic_storage(self):
        self.cells['soc/fabric_ram_macro'] = dict(type=SRAM,
            connections={'CLK': [10], 'Q': [41]}, port_directions={'CLK': 'input', 'Q': 'output'})
        self.cells['soc/start'] = cell('dffrnq_1', CLK=3, Q=51, D=52)
        self.pins[SRAM] = {'CLK': 0.29}
        r = inventory(self.cells, self.aliases, self.pins)
        self.assertEqual(r['periodic_macro_pins'], 1)
        self.assertEqual(r['periodic_sinks'], 3)
        self.assertEqual(r['clock_domains']['host_event'], 1)
        self.assertEqual(r['owners']['Services']['work'], 2)

    def test_clock_root_collision_is_rejected(self):
        self.aliases['watchdogClock'] = self.aliases['serviceClock']
        with self.assertRaisesRegex(ValueError, 'ROOT_ALIAS'):
            inventory(self.cells, self.aliases, self.pins)

    def test_library_gaps_fail_and_new_unrecognized_clock_paths_are_visible(self):
        del self.pins[SC + 'dffrnq_1']
        with self.assertRaisesRegex(ValueError, 'MISSING_LIBRARY_CELL'):
            inventory(self.cells, self.aliases, self.pins)
        self.pins[SC + 'dffrnq_1'] = {'CLK': 0.003}
        self.cells['soc/repair']['type'] = SC + 'and2_1'
        self.pins[SC + 'and2_1'] = {}
        r = inventory(self.cells, self.aliases, self.pins)
        self.assertIn('soc/reg', [x['path'] for x in r['other_clock_sinks']])


if __name__ == '__main__':
    unittest.main()
