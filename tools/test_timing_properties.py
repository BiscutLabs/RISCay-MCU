# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from timing_properties import validate_cases, period_invariant


class TimingPropertiesTest(unittest.TestCase):
    def test_obligations_follow_selected_owners_not_historical_counts(self):
        for owners in [('a',), ('a','b','c')]:
            records=[dict(owner=o,primitive_id='request_delay') for o in owners]
            cases=[dict(instance=o,key=c+'-s'+str(s),minima=dict(setup=3,hold=.1))
                   for o in owners for c in ('fast','slow') for s in (.02,2.)]
            check=lambda rows: validate_cases(records,rows,2,('fast','slow'),(.02,2.))
            self.assertEqual(set(check(cases)['owner_minima_ns']),set(owners))
            with self.assertRaisesRegex(ValueError,'CASE_COVERAGE'):check(cases[:-1])
            with self.assertRaisesRegex(ValueError,'CASE_COVERAGE'):check(cases+[cases[0]])

    def test_each_guard_kind_requires_its_real_metrics(self):
        obligations={'request_delay':dict(setup=3,hold=.1),
                     'output_delay':{'publication-rise':3,'publication-fall':3},
                     'acknowledge_guard':{'hold':3,'pulse-high':3,'ack-after-rearm':3}}
        for primitive, metrics in obligations.items():
            records=[dict(owner='owner',primitive_id=primitive)]
            cases=[dict(instance='owner',key='corner-s2.0',minima=metrics)]
            check=lambda rows: validate_cases(records,rows,2,('corner',),(2.,))
            check(cases)
            bad=deepcopy(cases);bad[0]['minima'][next(iter(metrics))]=-1
            with self.assertRaisesRegex(ValueError,'NEGATIVE_MARGIN'):check(bad)
            bad=deepcopy(cases);bad[0]['minima'][next(iter(metrics))]=float('nan')
            with self.assertRaisesRegex(ValueError,'NONFINITE'):check(bad)

    def test_period_is_analysis_only_for_every_row(self):
        rows={'setup':{'lane3':4},'hold':{'lane3':1},'ack':{'lane3':2}}
        period_invariant(rows,deepcopy(rows))
        changed=deepcopy(rows);changed['ack']['lane3']+=.01
        with self.assertRaisesRegex(ValueError,'PERIOD_DEPENDENCE'):period_invariant(rows,changed)



if __name__=='__main__':unittest.main()
