# SPDX-License-Identifier: Apache-2.0
"""Geometric conservation and reporting failures, independent of OpenROAD."""
import random
import unittest
import argparse

from report_routability import Instance, congestion_summary, density_bins, drc_boxes, export_script, owner, overlap, region_argument, region_summary


class RoutabilityReportTests(unittest.TestCase):
    def test_density_conserves_clipped_area_across_bin_boundaries(self):
        rng = random.Random(42)
        instances = []
        for i in range(100):
            x, y = rng.uniform(-20, 120), rng.uniform(-20, 120)
            instances.append(Instance(str(i), 'cell', 'logic', 'R0', (x, y, x+rng.uniform(1, 20), y+rng.uniform(1, 20))))
        core = (0, 0, 100, 100)
        for size in (7, 25, 100, 200):
            bins = density_bins(instances, core, size)
            self.assertAlmostEqual(sum(b['area_um2'].get('logic', 0) for b in bins), sum(overlap(i.box, core) for i in instances))
            self.assertAlmostEqual(sum(b['region_area_um2'] for b in bins), 10000)

    def test_macro_area_is_removed_from_density_denominator(self):
        instances = [Instance('mem', 'sram', 'macro', 'R0', (0, 0, 50, 100)), Instance('soc/ca_child_core/gate', 'gate', 'logic', 'R0', (50, 0, 75, 100))]
        summary = region_summary(instances, (0, 0, 100, 100))
        self.assertEqual(summary['footprint_density'], .75)
        self.assertEqual(summary['standard_cell_density'], .5)
        bins = density_bins(instances, (0, 0, 100, 100), 50)
        self.assertTrue(all(b['standard_cell_density'] is None for b in bins if b['ix'] == 0))
        self.assertTrue(all(b['standard_cell_density'] == .5 for b in bins if b['ix'] == 1))

    def test_spatial_ownership_uses_overlap_not_global_counts(self):
        a = Instance('soc/ca_child_core/gate', 'cell', 'logic', 'R0', (0, 0, 10, 10))
        b = Instance('soc/ca_child_i2c/gate', 'cell', 'logic', 'R0', (100, 100, 200, 200))
        self.assertEqual(region_summary([a, b], (5, 0, 15, 10))['owners'], [dict(owner='soc/ca_child_core', overlap_area_um2=50, intersecting_instances=1)])
        anonymous = Instance('soc/$abc$1/gate', 'cell', 'logic', 'R0', (0, 0, 1, 1))
        self.assertIn('unresolved', owner(anonymous))

    def test_congestion_keeps_layers_and_zero_capacity_overflow(self):
        rows = [dict(layer='M2', capacity=10, usage=5), dict(layer='M2', capacity=0, usage=2), dict(layer='M3', capacity=4, usage=6)]
        result = congestion_summary(rows)
        self.assertEqual(result['M2']['zero_capacity_with_demand'], 1)
        self.assertEqual(result['M2']['overflow'], 2)
        self.assertEqual(result['M3']['max_usage_ratio'], 1.5)
        self.assertEqual(result['M3']['overflow_gcells'], 1)
        with self.assertRaisesRegex(ValueError, 'GCELL_CONGESTION_MISSING'):
            congestion_summary([dict(layer='M2', capacity=10, usage=0)])
        with self.assertRaisesRegex(ValueError, 'INVALID_GCELL_VALUE'):
            congestion_summary([dict(layer='M2', capacity=10, usage=float('nan'))])

    def test_drc_parser_and_export_are_read_only(self):
        self.assertEqual(drc_boxes('bbox = (1360.6600, 1965.7400) - (1360.9400, 1966.0200) on Layer Metal2'), [dict(box_um=[1360.66, 1965.74, 1360.94, 1966.02], layer='Metal2')])
        script = export_script('/input.odb', '/output.tsv', True, True)
        self.assertIn('getCapacity', script)
        self.assertIn('getBBox', script)
        for command in ('write_db', 'setUsage', 'setCapacity', 'global_route', 'detailed_route'):
            self.assertNotIn(command, script)

    def test_explicit_regions_require_finite_positive_area(self):
        self.assertEqual(region_argument('left,450,1500,750,1800'), ('left', (450, 1500, 750, 1800)))
        for value in ('left,1,1,0,3', 'left,0,0,nan,1', ',0,0,1,1', 'left,0,0,1'):
            with self.assertRaises(argparse.ArgumentTypeError):
                region_argument(value)


if __name__ == '__main__':
    unittest.main()
