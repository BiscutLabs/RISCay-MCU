# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from report_electrical_groups import cap_audit_rows,require_bound_files,sha


def log(load='0.08', components='0.02\t0.06\t0.02\t0.06', report=True):
    return '\n'.join([
        'ADAPTER_CAP_LIMITS_BEGIN','ADAPTER_CAP_LIMIT\tu/Z\t0.05','ADAPTER_CAP_LIMITS_END',
        'ADAPTER_CAP_REPORT_BEGIN\ttt','max capacitance','Pin Limit Cap Slack','------------',
        f'u/Z 0.35 {load} 0.27 (MET)' if report else '',
        'ADAPTER_CAP_REPORT_END\ttt',f'ADAPTER_CAP_LOAD\ttt\tu/Z\t{components}','ADAPTER_CAP_COMPLETE'])


class AdapterCapAuditTests(unittest.TestCase):
    def test_reference_loads_include_ordinary_and_met_drivers(self):
        text=log().replace('ADAPTER_CAP_REPORT_END',
            'ordinary/Z 0.2 0.203 -0.003 (VIOLATED)\nmet/Z 0.2 0.1 0.1 (MET)\nADAPTER_CAP_REPORT_END')
        result=cap_audit_rows(text,['tt'],{'tt':['ordinary/Z','met/Z','missing/Z']})['tt']
        self.assertEqual(result['reference_loads_pf'],{'ordinary/Z':.203,'met/Z':.1,'missing/Z':None})
        self.assertEqual(result['measured_pins'],1)
        self.assertEqual(result['definite_violations'],1)

    def test_changed_or_missing_checkpoint_inputs_fail(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'limits.sdc';path.write_text('limit 0.05')
            expected={path.name:sha(path)}
            require_bound_files([path],expected,'CHANGED',root)
            require_bound_files([path],{str(path.resolve()):sha(path)},'CHANGED')
            with self.assertRaisesRegex(ValueError,'CHANGED'):require_bound_files([path],{},'CHANGED',root)
            path.write_text('limit 0.5')
            with self.assertRaisesRegex(ValueError,'CHANGED'):require_bound_files([path],expected,'CHANGED',root)
            path.unlink()
            with self.assertRaisesRegex(ValueError,'CHANGED'):require_bound_files([path],expected,'CHANGED',root)

    def test_adapter_violation_is_independent_of_liberty_pass(self):
        result=cap_audit_rows(log(),['tt'])['tt']
        self.assertEqual(result['definite_violations'],1)
        self.assertEqual(result['liberty_reported_violations'],[])
        self.assertEqual(result['rows'][0]['coherent_load_pf'],.08)

    def test_coherent_load_overrides_independently_maximal_sum(self):
        result=cap_audit_rows(log('0.04','0.01\t0.01\t0.03\t0.03'),['tt'])['tt']
        self.assertEqual(result['rows'][0]['status'],'within-bound')
        self.assertEqual(result['rows'][0]['upper_load_bound_pf'],.04)

    def test_filtered_driver_is_bound_only_until_proved(self):
        result=cap_audit_rows(log(components='0.01\t0.01\t0.03\t0.03',report=False),['tt'])['tt']
        self.assertEqual(result['bound_only_candidates'],1)
        self.assertEqual(result['definite_violations'],0)
        self.assertEqual(result['coherent_report_missing_pins'],['u/Z'])
        self.assertEqual(cap_audit_rows(log(report=False),['tt'])['tt']['definite_violations'],1)

    def test_missing_load_is_explicit_not_zero(self):
        text='\n'.join(x for x in log().splitlines() if not x.startswith('ADAPTER_CAP_LOAD'))
        result=cap_audit_rows(text,['tt'])['tt']
        self.assertEqual(result['missing_pins'],['u/Z'])
        self.assertEqual(result['measured_pins'],0)
        self.assertEqual(result['rows'],[])

    def test_bad_measurements_and_incomplete_sections_fail(self):
        cases=[log().replace('0.02\t0.06\t0.02\t0.06','nan\t0.06\t0.02\t0.06'),
               log().replace('ADAPTER_CAP_COMPLETE',''),
               log().replace('0.02\t0.06\t0.02\t0.06','-1\t0.06\t0.02\t0.06'),
               log().replace('u/Z 0.35 0.08 0.27 (MET)','u/Z 0.35 8 0.27 (MET)'),
               log().replace('ADAPTER_CAP_LIMITS_END','ADAPTER_CAP_LIMIT\tu/Z\t0.05\nADAPTER_CAP_LIMITS_END')]
        for text in cases:
            with self.subTest(text=text),self.assertRaises(ValueError):cap_audit_rows(text,['tt'])

    def test_escaped_alias_collisions_fail(self):
        text=log().replace('u/Z','u/x/Z').replace('ADAPTER_CAP_REPORT_END',
            'u\\/x/Z 0.35 0.08 0.27 (MET)\nADAPTER_CAP_REPORT_END')
        with self.assertRaisesRegex(ValueError,'ADAPTER_CAP_DUPLICATE_REPORT_PIN'):cap_audit_rows(text,['tt'])


if __name__=='__main__':unittest.main()
