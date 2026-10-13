# SPDX-License-Identifier: Apache-2.0
"""Regression for local phase state omitted by a module-input timing filter."""
import unittest
from gf180_constraints import data_bound


class RegisterLaunchBounds(unittest.TestCase):
    def test_internal_phase_launch_survives_missing_alias_and_constant_inputs(self):
        # ClickProgramSource storedTarget is armed.q, which does not traverse
        # an input port. The conservative destination constraint must exist
        # even with no dynamic module-input references.
        sink='[rp {soc/source/stored_data_delay/u4/Z}]'
        result=data_bound(10,[],sink,optimized_source=True)
        self.assertEqual(result,'set_max_delay 10 -ignore_clock_latency -from [all_registers -clock_pins] -to '+sink)
        self.assertEqual(data_bound(10,['[rp {unrelated/input}]'],sink,optimized_source=True),result)

    def test_exact_retained_source_keeps_its_filter_and_static_case_is_distinct(self):
        result=data_bound(10,['[rp {source/Q}]'],'[rp {sink/D}]')
        self.assertIn('-through [concat [rp {source/Q}]]',result)
        self.assertIsNone(data_bound(10,[],'[rp {sink/D}]'))


if __name__=='__main__':unittest.main()
