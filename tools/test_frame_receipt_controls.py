# SPDX-License-Identifier: Apache-2.0
import unittest
from check_frame_receipt_controls import change, instrument, mutate


class ReceiptControlsTest(unittest.TestCase):
    def test_mutations_require_one_actual_anchor(self):
        for text in ('none', 'requestSync <= requestMeta; requestSync <= requestMeta;'):
            with self.assertRaisesRegex(ValueError,'MUTATION_ANCHOR'):
                mutate(text,'sync-bypassed',False)

    def test_monitor_adds_without_changing_original_assertions(self):
        body='module Testbench; initial begin $fatal(1,"OLD"); end\nendmodule\n'
        result=instrument(body,'dut.receipt')
        self.assertIn(body.split('\nendmodule')[0],result)
        self.assertEqual(result.count('$fatal(1,"OLD")'),1)
        self.assertIn('FRAME_RECEIPT_POR_RELEASE_STAGES',result)

    def test_unknown_fault_or_ambiguous_testbench_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNKNOWN_FAULT'):mutate('', 'arbitrary', False)
        with self.assertRaisesRegex(ValueError,'TESTBENCH_SHAPE'):instrument('\nendmodule\nendmodule','dut.r')

    def test_native_phase_and_return_mutations_are_separate(self):
        self.assertEqual(mutate('acknowledge <= requestSync;', 'return-or-phase', True), 'acknowledge <= ~requestSync;')
        self.assertEqual(mutate('requestSync & acknowledge;', 'return-or-phase', False), 'in_req & acknowledge;')


if __name__=='__main__':unittest.main()
