# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path
from check_pdn_ir import (load_powers, perimeter_sources, read_voltages,
                          combine_voltage_maps, spatial_bins, positive, validate_solver_log)


def cell(name,kind,x0=0,x1=10):
    return dict(instance=name,kind=kind,x0=x0,y0=0,x1=x1,y1=10,area_um2=(x1-x0)*10)


class PdnIrChecks(unittest.TestCase):
    def test_load_conservation_and_macro_current(self):
        records=[cell('a','logic'),cell('b','logic',10,30),cell('ram','macro')]
        powers=load_powers(records,3.3,1,.2)
        self.assertAlmostEqual(sum(powers.values()),3.3*.0012)
        self.assertAlmostEqual(powers['b'],2*powers['a'])
        self.assertAlmostEqual(powers['ram'],.00066)

    def test_perimeter_does_not_clamp_interior(self):
        rects=[dict(shape='RING',x0=0,y0=y,x1=20,y1=y+2) for y in (0,18)]
        rects.append(dict(shape='STRIPE',x0=0,y0=9,x1=20,y1=11))
        points=perimeter_sources(rects)
        self.assertIn((1.,10.,2),points)
        self.assertIn((19.,10.,2),points)
        self.assertNotIn((10.,10.,2),points)
        with self.assertRaisesRegex(ValueError,'TWO_HORIZONTAL'):
            perimeter_sources(rects[1:])

    def test_both_supplies_required_and_local_conservative_combination(self):
        records=[cell('a','logic'),cell('b','macro')]
        values=combine_voltage_maps(records,{'a':3.28,'b':3.25},{'a':.01,'b':.02},3.3)
        self.assertAlmostEqual(values[1]['drop_v'],.07)
        with self.assertRaisesRegex(ValueError,'MISSING_SUPPLY'):
            combine_voltage_maps(records,{'a':3.28},{'a':.01,'b':.02},3.3)

    def test_nonfinite_voltage_rejected_and_duplicate_terminals_extrema(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'nodes.csv'
            path.write_text('Instance,Voltage\na,3.2\na,3.1\n')
            self.assertEqual(read_voltages(path,3.3),{'a':3.1})
            path.write_text('Instance,Voltage\na,nan\n')
            with self.assertRaisesRegex(ValueError,'INVALID_NODE'):
                read_voltages(path,3.3)
        for value in (float('nan'),float('inf'),0,-1):
            with self.assertRaises(ValueError):positive(value)

    def test_density_uses_overlap_and_worst_drop(self):
        records=[{**cell('a','logic',5,15),'drop_v':.01},
                 {**cell('ram','macro',15,20),'drop_v':.04}]
        bins=sorted(spatial_bins(records,[0,0,20,10],10),key=lambda b:b['x0'])
        self.assertEqual([b['logic_density'] for b in bins],[.5,.5])
        self.assertEqual([b['macro_density'] for b in bins],[0,.5])
        self.assertEqual([b['drop_v'] for b in bins],[.01,.04])

    def test_solver_must_use_requested_load_on_both_rails(self):
        good='Source nodes: 4\nTotal power : 4.29e-03 W\n'*2
        self.assertEqual(validate_solver_log(good,.00429),{'VDD':4,'VSS':4})
        with self.assertRaisesRegex(ValueError,'LOAD_MISMATCH'):
            validate_solver_log(good,.00858)
        with self.assertRaisesRegex(ValueError,'MISSING_SOLVER'):
            validate_solver_log('Source nodes: 4\nTotal power : 4.29e-03 W\n',.00429)


if __name__=='__main__':unittest.main()
