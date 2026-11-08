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


    def measured(self, **values):
        row=dict(instance='Soc.guard',owner='Soc.stage',owner_module='FourPhaseStage',
                 primitive_id='request_delay',stages=28,disposition='measure-canonical-stage',
                 original_parameters=dict(WIDTH=1,OP=0,RESET_VALUE=0,DELAY_FS=100000000))
        case=dict(earliest_ns=100.,latest_ns=73.16666666666667,aperture_ns=0.,
                  cell_min_ns=2.684,cell_max_ns=2.7,electrical_pass=True)
        case.update(values)
        obligation=dict(id='setup',kind='relative-ordering',basis='loaded source/capture leaves',edges=['rise'],
                        cases=[dict(case,corner=c,slew_ns=s,edge='rise') for c in g.relative.CORNERS for s in (.02,2.)])
        evidence=dict(schema='riscay-guard-sizing-measurements-v1',guards=[
            dict(instance=row['instance'],previous_stages=row['stages'],obligations=[obligation])])
        return row,evidence

    def test_deficient_guard_lengthens_instead_of_reverting_to_hardcoded_count(self):
        row,evidence=self.measured()
        proposal=g.candidate_counts([row],evidence)[0]
        self.assertEqual(proposal['stages'],33)
        self.assertGreaterEqual(proposal['estimated_minimum_margin_ns'],g.RESIDUAL_NS)
        self.assertEqual(row['stages'],28)
        row['original_parameters']['DELAY_FS']=10000000000
        self.assertEqual(g.candidate_counts([row],evidence)[0]['stages'],proposal['stages'])

    def test_removal_uses_maximum_cell_delay_and_only_measured_guards(self):
        row,evidence=self.measured(earliest_ns=100.,latest_ns=20.,cell_min_ns=2.,cell_max_ns=10.)
        row['stages']=10;evidence['guards'][0]['previous_stages']=10
        unmeasured=dict(row,instance='Soc.unmeasured')
        result=g.candidate_counts([row,unmeasured],evidence)
        self.assertEqual([(r['instance'],r['stages']) for r in result],[('Soc.guard',4)])
        # The next smaller count fails the declared floor.
        self.assertLess(g.conservative_margin(100-(10-3)*10,20),g.RESIDUAL_NS)

    def test_same_corner_ratio_not_global_fastest_cell(self):
        row,evidence=self.measured(earliest_ns=40.,latest_ns=20.,cell_min_ns=1.,cell_max_ns=1.)
        row['stages']=20;evidence['guards'][0]['previous_stages']=20
        cases=evidence['guards'][0]['obligations'][0]['cases']
        for case in cases:
            if case['corner'].startswith('ss_'):
                for key in ('earliest_ns','latest_ns','cell_min_ns','cell_max_ns'):case[key]*=5
        proposal=g.candidate_counts([row],evidence)[0]
        self.assertEqual(proposal['stages'],13)

    def test_absolute_minimum_is_kept_separate(self):
        row,evidence=self.measured(earliest_ns=30.,latest_ns=0.,cell_min_ns=1.,cell_max_ns=1.)
        row['stages']=10;evidence['guards'][0]['previous_stages']=10
        o=evidence['guards'][0]['obligations'][0]
        o.update(kind='absolute-minimum',id='pulse-width',basis='Liberty minimum pulse width')
        for case in o['cases']:
            case.pop('latest_ns');case.pop('aperture_ns');case['required_ns']=20.
        self.assertEqual(g.candidate_counts([row],evidence)[0]['stages'],8)
        o['kind']='simulation-delay'
        with self.assertRaisesRegex(ValueError,'GUARD_OBLIGATION_KIND'):g.candidate_counts([row],evidence)

    def test_missing_duplicate_or_invalid_measurements_fail_closed(self):
        row,source=self.measured()
        mutations=[lambda e:e['guards'][0]['obligations'][0]['cases'].pop(),
                   lambda e:e['guards'][0]['obligations'][0]['cases'].append(e['guards'][0]['obligations'][0]['cases'][0]),
                   lambda e:e['guards'][0].update(previous_stages=27),
                   lambda e:e['guards'][0].update(obligations=[]),
                   lambda e:e.update(guards=[])]
        for field,value in [('earliest_ns',math.nan),('latest_ns',math.inf),('cell_min_ns',0),
                            ('cell_max_ns',1),('electrical_pass',False),('earliest_ns',True)]:
            mutations.append(lambda e,f=field,v=value:e['guards'][0]['obligations'][0]['cases'][0].update({f:v}))
        for change in mutations:
            with self.subTest(change=change):
                evidence=deepcopy(source);change(evidence)
                with self.assertRaises(ValueError):g.candidate_counts([row],evidence)

    def test_all_declared_edges_and_obligations_control_the_count(self):
        row,evidence=self.measured(earliest_ns=100.,latest_ns=20.)
        other=deepcopy(evidence['guards'][0]['obligations'][0]);other.update(id='return',edges=['fall'])
        for case in other['cases']:case.update(edge='fall',latest_ns=75.)
        evidence['guards'][0]['obligations'].append(other)
        result=g.candidate_counts([row],evidence)[0]
        self.assertGreater(result['stages'],row['stages'])
        self.assertGreaterEqual(result['estimated_minimum_margin_ns'],g.RESIDUAL_NS)

    def test_independent_vector_guards_cannot_be_shared(self):
        row,evidence=self.measured();row['original_parameters']['WIDTH']=4
        with self.assertRaisesRegex(ValueError,'GUARD_SCALAR_CHAIN_REQUIRED'):g.candidate_counts([row],evidence)

    def test_candidate_must_remeasure_every_declared_obligation(self):
        row,evidence=self.measured(earliest_ns=100.,latest_ns=20.)
        proposals=g.candidate_counts([row],evidence)
        g.require_candidate_binder(proposals,'bd')
        with self.assertRaisesRegex(ValueError,'GUARD_REQUEST_REQUIRES_DATA'):
            g.require_candidate_binder(proposals,'bd',focused=True)
        for kind,ident,disposition in [('absolute-minimum','setup','measure-canonical-stage'),
                                      ('relative-ordering','reset-return','measure-canonical-stage'),
                                      ('relative-ordering','setup','retain-custom-obligation')]:
            altered=deepcopy(proposals)
            altered[0]['sizing_obligations'][0].update(kind=kind,id=ident)
            altered[0]['disposition']=disposition
            with self.assertRaisesRegex(ValueError,'GUARD_(UNSUPPORTED_CANDIDATE_OBLIGATION|CUSTOM_BINDER_REQUIRED)'):
                g.require_candidate_binder(altered,'bd')
        altered=deepcopy(proposals);altered[0]['stages']=row['stages']+1
        with self.assertRaisesRegex(ValueError,'GUARD_LENGTHEN_REMAP_REQUIRED'):g.require_candidate_binder(altered,'bd')

    def test_family_removes_numeric_specialization_only(self):
        self.assertEqual(g.family('ClickStage_125'),'ClickStage')
        self.assertEqual(g.family('ClickStage_foo'),'ClickStage_foo')


if __name__=='__main__':unittest.main()
