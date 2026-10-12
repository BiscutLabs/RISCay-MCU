# SPDX-License-Identifier: Apache-2.0
"""Fail-closed classification controls, independently of RTL mutation results."""
import unittest
from check_program_return_fatals import fatal_sites, classify_fatal


class FatalPolicyTests(unittest.TestCase):
    source = r'''module Testbench;
// $fatal(1,"TARGET");
initial begin
  $display("fake $fatal(1,\"TARGET\");");
  begin : retained_owner
    if (bad) $fatal(1,"TARGET");
  end
end
endmodule
'''

    def setUp(self):
        self.sites = fatal_sites(self.source, ('TARGET',))
        self.log = 'FATAL: testbench.sv:6: TARGET\n       Time: 123  Scope: Testbench.retained_owner\n'

    def test_comment_string_and_named_scope(self):
        self.assertEqual(self.sites, [dict(source='testbench.sv', line=6, message='TARGET', scope='Testbench.retained_owner')])
        self.assertEqual(len(classify_fatal({'exit_code': 0}, {'exit_code': 1}, self.log, self.sites)), 1)

    def test_expected_text_without_actual_fatal_never_passes(self):
        for log in ('TARGET', 'FATAL: TARGET', 'TARGET\nFATAL: testbench.sv:6: OTHER\n Time: 1 Scope: Testbench.retained_owner\n'):
            with self.subTest(log=log), self.assertRaises(ValueError):
                classify_fatal({'exit_code': 0}, {'exit_code': 1}, log, self.sites)

    def test_wrong_site_scope_message_and_mixed_failures_rejected(self):
        for wrong in (self.log.replace(':6:', ':7:'), self.log.replace('testbench.sv', 'other.sv'),
                      self.log.replace('retained_owner', 'unrelated'), self.log.replace('TARGET', 'OTHER'),
                      self.log + self.log.replace('TARGET', 'OTHER')):
            with self.subTest(log=wrong), self.assertRaises(ValueError):
                classify_fatal({'exit_code': 0}, {'exit_code': 1}, wrong, self.sites)

    def test_success_timeout_compile_failure_and_deadline_rejected(self):
        for compiled, simulated, suffix in ((1, 1, ''), (0, 0, ''), (0, 2, ''), (0, 1, 'CA_TEST_PASS'),
                                             (0, 1, 'TIMEOUT'), (0, 1, 'DEADLINE'), (0, 1, 'ERROR')):
            with self.subTest(values=(compiled, simulated, suffix)), self.assertRaises(ValueError):
                classify_fatal({'exit_code': compiled}, {'exit_code': simulated}, self.log + suffix, self.sites)
        with self.assertRaises(ValueError):
            classify_fatal({'exit_code': 0}, {'exit_code': 1, 'timed_out': True}, self.log, self.sites)

    def test_missing_or_formatted_sites_fail_closed(self):
        for source in ('// $fatal(1,"TARGET");', '$display("TARGET");', '$fatal(1,"TARGET:%d", 2);',
                       'begin $fatal(1,"TARGET");', 'end $fatal(1,"TARGET");'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                fatal_sites(source, ('TARGET',))


if __name__ == '__main__':
    unittest.main()
