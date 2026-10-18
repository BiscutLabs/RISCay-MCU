# SPDX-License-Identifier: Apache-2.0
"""Adoption must fail closed on incomplete or negative guard evidence."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from control_relative_timing import CORNERS
from gf180_physical import sha
from seal_ordering_guards import (validate_cases, validate_inputs, validate_retry_source,
                                  replace_retry, SCRIPT_LINE, CRPR_LINE, CRPR_PREFIX)


class GuardSealTests(unittest.TestCase):
    def setUp(self):
        self.records = [dict(owner='owner', primitive_id='acknowledge_guard')]
        self.cases = [dict(instance='owner', key=f'{corner}-s{slew}',
                           minima={'hold': 3., 'pulse-high': 4., 'ack-after-rearm': 2.1})
                      for corner in CORNERS for slew in (.02, 2.)]

    def test_complete_actual_owner_cohort(self):
        result = validate_cases(self.records, self.cases, 2)
        self.assertEqual(result['case_count'], 10)
        self.assertEqual(result['minima_ns']['ack-after-rearm'], 2.1)

    def test_duplicate_does_not_replace_missing_corner(self):
        rows = deepcopy(self.cases)
        rows[-1] = deepcopy(rows[0])
        with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_CASE_COVERAGE$'):
            validate_cases(self.records, rows, 2)

    def test_one_instance_cannot_stand_in_for_another(self):
        records = self.records + [dict(owner='other', primitive_id='acknowledge_guard')]
        with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_CASE_COVERAGE$'):
            validate_cases(records, self.cases, 2)

    def test_rearm_and_pulse_aperture_are_required(self):
        for metric in ('pulse-high', 'ack-after-rearm'):
            with self.subTest(metric=metric):
                rows = deepcopy(self.cases)
                del rows[0]['minima'][metric]
                with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_METRIC_MISSING$'):
                    validate_cases(self.records, rows, 2)

    def test_near_zero_and_nan_cannot_pass(self):
        for value, diagnostic in ((1.999, 'NEGATIVE_MARGIN'), (float('nan'), 'NONFINITE')):
            with self.subTest(value=value):
                rows = deepcopy(self.cases)
                rows[0]['minima']['ack-after-rearm'] = value
                with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_'+diagnostic+'$'):
                    validate_cases(self.records, rows, 2)

    def test_elapsed_requires_setup_and_existing_hold(self):
        records = [dict(owner='owner', primitive_id='request_delay')]
        rows = deepcopy(self.cases)
        for row in rows:
            row['minima'] = dict(setup=5., hold=.9)
        self.assertEqual(validate_cases(records, rows, 2)['minima_ns']['hold'], .9)
        rows[-1]['minima']['hold'] = -.01
        with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_ELAPSED_HOLD$'):
            validate_cases(records, rows, 2)

    def test_executed_helper_can_use_exact_snapshot(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root/'tools'; tools.mkdir()
            campaign = root/'run'; (campaign/'source-snapshot').mkdir(parents=True)
            helper = tools/'helper.py'; helper.write_text('executed')
            frozen = {str(helper): sha(helper)}
            snapshot = campaign/'source-snapshot/helper.py'; snapshot.write_bytes(helper.read_bytes())
            helper.write_text('later revision')
            self.assertEqual(validate_inputs(frozen, campaign, tools)[str(helper)], str(snapshot))
            snapshot.write_text('wrong revision')
            with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_INPUT_CHANGED$'):
                validate_inputs(frozen, campaign, tools)

    def test_changed_pdk_cannot_use_helper_snapshot_fallback(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root/'run'; (campaign/'source-snapshot').mkdir(parents=True)
            liberty = root/'corner.lib'; liberty.write_text('measured')
            frozen = {str(liberty): sha(liberty)}
            (campaign/'source-snapshot/corner.lib').write_bytes(liberty.read_bytes())
            liberty.write_text('changed')
            with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_INPUT_CHANGED$'):
                validate_inputs(frozen, campaign, root/'tools')

    def test_retry_changes_only_the_crpr_setting(self):
        original = 'before\n'+SCRIPT_LINE+'after\n'
        retry = original.replace(SCRIPT_LINE, SCRIPT_LINE+CRPR_LINE)
        validate_retry_source(original, retry)
        for bad in (retry+'# extra change\n', retry.replace('false', 'true'), original):
            with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_RETRY_SOURCE_SCOPE$'):
                validate_retry_source(original, bad)

    def retry_fixture(self, root):
        old = root/'old'; new = root/'new'
        for directory in (old, new):
            (directory/'0').mkdir(parents=True)
            (directory/'0/plan.json').write_text(json.dumps(dict(descriptor=dict(instance='owner'))))
        original = 'before\n'+SCRIPT_LINE+'after\n'
        (old/'size_ordering_guards.py').write_text(original)
        (new/'size_ordering_guards.py').write_text(original.replace(SCRIPT_LINE, SCRIPT_LINE+CRPR_LINE))
        for case in self.cases:
            name = case['key']
            value = dict(result=case, results={'raw_path': ['root', 'capture']})
            (new/'0'/(name+'.json')).write_text(json.dumps(value))
            if case is not self.cases[-1]:
                (old/'0'/(name+'.json')).write_text(json.dumps(value))
            (old/'0'/(name+'-ack.tcl')).write_text('exact existing query\n')
            (new/'0'/(name+'-ack.tcl')).write_text(CRPR_PREFIX+'exact existing query\n')
        before = dict(input_sha256={str(old/'size_ordering_guards.py'): sha(old/'size_ordering_guards.py')},
                      cases=self.cases[:-1], failures=[dict(type='CalledProcessError', message='exit status 11')])
        after = dict(input_sha256={str(new/'size_ordering_guards.py'): sha(new/'size_ordering_guards.py')},
                     cases=self.cases, status='COMPLETE_MEASURED', failures=[])
        (new/'results.json').write_text(json.dumps(after))
        policy = dict(variants=dict(click=self.records), residual_ns=2)
        return old, new, before, after, policy

    def test_retry_retains_failure_and_checks_all_overlap(self):
        with TemporaryDirectory() as temporary:
            old, new, before, after, policy = self.retry_fixture(Path(temporary))
            cases, evidence = replace_retry(policy, 'click', old, before, new, after)
            self.assertEqual(len(cases), 10)
            self.assertEqual(evidence['raw_overlap_count'], 9)
            self.assertEqual(evidence['original_failures'], before['failures'])
            self.assertEqual(evidence['exact_tcl_delta_checks'], 10)

    def test_retry_cannot_change_raw_path_or_tcl(self):
        for fault, diagnostic in [('json', 'RAW_ROWS_CHANGED'), ('tcl', 'TCL_CHANGED')]:
            with self.subTest(fault=fault), TemporaryDirectory() as temporary:
                old, new, before, after, policy = self.retry_fixture(Path(temporary))
                name = self.cases[0]['key']
                if fault == 'json':
                    path = new/'0'/(name+'.json')
                    value = json.loads(path.read_text()); value['results']['raw_path'][0] = 'different'
                    path.write_text(json.dumps(value))
                else:
                    (new/'0'/(name+'-ack.tcl')).write_text(CRPR_PREFIX+'changed query\n')
                with self.assertRaisesRegex(ValueError, '^GUARD_SEAL_RETRY_'+diagnostic+'$'):
                    replace_retry(policy, 'click', old, before, new, after)


if __name__ == '__main__':
    unittest.main()
