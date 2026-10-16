# SPDX-License-Identifier: Apache-2.0
"""Fault controls must reject pre-existing failures and unintended movement."""
from copy import deepcopy
import unittest

from check_native_stage_controls import capture_fault_pin, verdict


def fixture():
    before=dict(lanes=[dict(lane=i,phase=0,maximum_input_data_lag_ns=None if i==0 else 10,
                           zero_reuse_hold_margin_ns=None if i==0 else 4,ack_after_capture_ns=3) for i in range(3)])
    after=deepcopy(before)
    for i in (0,1):after["lanes"][i]["ack_after_capture_ns"]=-997
    after["lanes"][1]["zero_reuse_hold_margin_ns"]=-996
    plan=dict(variant="bd",constant_lanes={"0":0},native=dict(cells=[dict(path="branch",pins=dict(Z="cap")),
        *[dict(path="cell"+str(i),pins=dict(E="cap" if i<2 else "other")) for i in range(3)]]),
        contexts=[dict(id="common",queries=[dict(role="capture",lane=i,sink=f"cell{i}/E") for i in range(3)])])
    return before,after,plan,"late_capture",[dict(cell="branch")]


class ControlTests(unittest.TestCase):
    def test_static_branch_and_dynamic_hold(self):
        before,after,plan,fault,arcs=fixture()
        self.assertEqual(capture_fault_pin(plan),"cell0/E")
        result=verdict(before,after,plan,fault,arcs)
        self.assertEqual(result["static_capture_members"],[(0,0)])
        self.assertEqual(result["newly_negative"],[(0,0),(1,0)])

    def reject(self,mutate,diagnostic):
        values=fixture();mutate(*values[:3])
        with self.assertRaisesRegex(ValueError,"^"+diagnostic+"$"):verdict(*values)

    def test_off_branch_improvement(self):
        self.reject(lambda b,a,p:a["lanes"][2].update(ack_after_capture_ns=5),"STAGE_CONTROL_OFF_BRANCH_CHANGE")

    def test_off_branch_hold_improvement(self):
        self.reject(lambda b,a,p:a["lanes"][2].update(zero_reuse_hold_margin_ns=5),"STAGE_CONTROL_OFF_BRANCH_HOLD")

    def test_dynamic_hold_not_affected(self):
        self.reject(lambda b,a,p:a["lanes"][1].update(zero_reuse_hold_margin_ns=4),"STAGE_CONTROL_DYNAMIC_HOLD_NOT_FAILED")

    def test_static_hold_invented(self):
        self.reject(lambda b,a,p:a["lanes"][0].update(zero_reuse_hold_margin_ns=0),"STAGE_CONTROL_STATIC_HOLD")

    def test_fault_branch_misses_constants(self):
        self.reject(lambda b,a,p:p.update(constant_lanes={"2":0}),"STAGE_CONTROL_STATIC_BRANCH_MISSING")

    def test_setup_changed(self):
        self.reject(lambda b,a,p:a["lanes"][2].update(maximum_input_data_lag_ns=9),"STAGE_CONTROL_SETUP_CHANGED")

    def test_old_failure_not_credited(self):
        before,after,plan,_,arcs=fixture()
        for i in (1,2):
            before["lanes"][i]["maximum_input_data_lag_ns"]=-1
            after["lanes"][i]["maximum_input_data_lag_ns"]=-10
        with self.assertRaisesRegex(ValueError,"STAGE_CONTROL_NO_NEW_FAILURE"):
            verdict(before,after,plan,"short_request",arcs)

    def test_new_failure_separate_from_old(self):
        before,after,plan,_,arcs=fixture()
        before["lanes"][1]["maximum_input_data_lag_ns"]=-1
        for i in (1,2):after["lanes"][i]["maximum_input_data_lag_ns"]=-10
        result=verdict(before,after,plan,"short_request",arcs)
        self.assertEqual(result["baseline_negative"],[(1,0)])
        self.assertEqual(result["newly_negative"],[(2,0)])

    def test_changed_static_mask(self):
        before,after,plan,_,arcs=fixture()
        after["lanes"][0]["maximum_input_data_lag_ns"]=-10
        with self.assertRaisesRegex(ValueError,"STAGE_CONTROL_STATIC_MASK"):
            verdict(before,after,plan,"short_request",arcs)


if __name__=="__main__":unittest.main()
