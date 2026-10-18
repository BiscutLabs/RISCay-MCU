# SPDX-License-Identifier: Apache-2.0
"""Controls for the engineering policy and selective physical recipe changes."""
import math
import unittest
from copy import deepcopy

import size_ordering_guards as g


class PolicyTests(unittest.TestCase):
    def test_rearm_uses_complete_measured_phase_slew_bounds(self):
        text='\n'.join(f'GUARD_PHASE_Q_SLEW\t{mode}\t{edge}\t{value}'
                       for mode,value in (('min',.15),('max',.3)) for edge in ('rise','fall'))
        self.assertEqual(g.phase_slews(text)['fall'],dict(min=.15,max=.3))
        for bad in (text.rsplit('\n',1)[0],text+'\n'+text.splitlines()[0],
                    text.replace('\t0.3','\t0.1'),text.replace('\t0.3','\tnan')):
            with self.assertRaises(ValueError):g.phase_slews(bad)

    def test_two_sided_derate_is_not_single_data_multiplier(self):
        self.assertAlmostEqual(g.conservative_margin(20,10,.5),3.5)
        self.assertLess(g.conservative_margin(20,10,.5),20-1.2*10-.5)

    def test_floor_cannot_be_reduced_or_nonfinite(self):
        for bad in (0,.15,-.2,1,math.nan):
            with self.assertRaises(ValueError):g.conservative_margin(20,10,derate=bad)
        for bad in (math.nan,math.inf,-1):
            with self.assertRaises(ValueError):g.conservative_margin(bad,10)

    def test_25_cell_pilot_sensitivity_is_below_residual_floor(self):
        self.assertLess(.508,g.RESIDUAL_NS)
        self.assertGreaterEqual(g.DERATE,.2)

    def test_only_explicit_candidates_change(self):
        base=dict(instance='Soc.a',owner='Soc.stage',owner_module='FourPhaseStage',
                  primitive_id='output_delay',stages=27,disposition='measure-canonical-stage')
        custom=dict(base,instance='Soc.b',disposition='retain-custom-obligation')
        request=dict(base,instance='Soc.c',primitive_id='request_delay',stages=10)
        rows=g.candidate_counts([base,custom,request])
        self.assertEqual([(r['instance'],r['stages'],r['previous_stages']) for r in rows],[('Soc.a',8,27)])
        self.assertEqual(base['stages'],27)

    def test_family_removes_numeric_specialization_only(self):
        self.assertEqual(g.family('ClickStage_125'),'ClickStage')
        self.assertEqual(g.family('ClickStage_foo'),'ClickStage_foo')


if __name__=='__main__':unittest.main()
