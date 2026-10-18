# SPDX-License-Identifier: Apache-2.0
"""Independent malformed-evidence and relative-margin controls; no PDK needed."""
from copy import deepcopy
import unittest

import control_relative_timing as r


def fixture():
    cells=[dict(path=owner,cell="buffer",pins={"I":"input", "Z":owner})
           for owner in ("request_delay","a","long_hold")]
    plan=dict(variant="bd",native=dict(signals={c["path"]:c["path"] for c in cells},cells=cells))
    queries=[dict(id="c:"+m,sink="storage/E",source_edge="rise",sink_edge="fall",mode=m) for m in ("min","max")]
    ctx=dict(kind="request",sources=["in_req"],queries=queries)
    lines=["RELATIVE_BEGIN"]
    for mode,value in (("min",12),("max",14)):
        lines += [f"CONTROL_PATH\tc:{mode}\t0\t{value}\t{value}\t{value}\t1\tin_req\tstorage/E\trise\tfall",
                  f"CONTROL_POINTS\tc:{mode}\tin_req\trequest_delay/Z\ta/Z\tlong_hold/Z\tstorage/E"]
    lines += ["RELATIVE_EVENT_SLEW\t0.5\t0.6","RELATIVE_ELECTRICAL_BEGIN","pin (VIOLATED)","RELATIVE_ELECTRICAL_END","RELATIVE_COMPLETE"]
    return plan,ctx,"\n".join(lines)+"\n"


def arithmetic():
    results={"data":{"rows":{}},"request-0":{"rows":{}},"common":{"rows":{}}}
    for lane in range(315):
        for edge in ("rise","fall"):
            for mode,delay in (("min",2),("max",9)):
                results["data"]["rows"][f"data:{lane}:{mode}:{edge}"]={"delay_ns":delay}
        results["request-0"]["rows"][f"capture:{lane}:min:rise"]={"delay_ns":15}
        results["common"]["rows"][f"capture:{lane}:max"]={"delay_ns":3}
    results["common"]["rows"]["ack:min:rise"]={"delay_ns":6}
    for result in results.values():result["event_slew_ns"]=[.5,.6]
    return results,dict(variant="bd"),dict(setup_ns=1,hold_ns=.5)


class EvidenceTests(unittest.TestCase):
    def reject(self,old,new,diagnostic):
        p,c,s=fixture()
        with self.assertRaisesRegex(ValueError,"^"+diagnostic+"$"):
            r.parse(s.replace(old,new),p,c)

    def test_exact_rows(self):
        p,c,s=fixture();answer=r.parse(s,p,c)
        self.assertEqual(answer["rows"]["c:min"]["delay_ns"],12)
        self.assertEqual(len(answer["electrical_violations"]),1)

    def test_missing_row(self):
        p,c,s=fixture();s="\n".join(l for l in s.splitlines() if "c:max" not in l)+"\n"
        with self.assertRaisesRegex(ValueError,"RELATIVE_COVERAGE"):r.parse(s,p,c)

    def test_duplicate(self):
        p,c,s=fixture();line=next(l for l in s.splitlines() if l.startswith("CONTROL_PATH"))
        with self.assertRaisesRegex(ValueError,"RELATIVE_QUERY_ID"):r.parse(s+line+"\n",p,c)

    def test_nonfinite(self):self.reject("\t12\t12\t12\t","\tnan\tnan\tnan\t","RELATIVE_NUMERIC")
    def test_signed_data_offset_is_preserved_but_control_delay_is_rejected(self):
        p,c,s=fixture();s=s.replace("\t12\t12\t12\t","\t-0.03\t-0.03\t-0.03\t")
        with self.assertRaisesRegex(ValueError,"RELATIVE_NUMERIC"):r.parse(s,p,c)
        c['kind']='data'
        self.assertEqual(r.parse(s,p,c)['rows']['c:min']['delay_ns'],-.03)
    def test_nonzero_launch(self):self.reject("\t0\t12\t","\t2\t12\t","RELATIVE_NUMERIC")
    def test_wrong_phase(self):self.reject("\trise\tfall","\tfall\tfall","RELATIVE_PATH_BINDING")
    def test_wrong_source(self):self.reject("\tin_req\tstorage/E","\twrong\tstorage/E","RELATIVE_PATH_BINDING")
    def test_wrong_endpoint(self):self.reject("\tstorage/E\trise","\tother/E\trise","RELATIVE_PATH_BINDING")
    def test_missing_guard(self):self.reject("\trequest_delay/Z", "", "RELATIVE_CONTROL_PROVENANCE")
    def test_reordered_cone(self):self.reject("\ta/Z\tlong_hold/Z", "\tlong_hold/Z\ta/Z", "RELATIVE_CONTROL_PROVENANCE")
    def test_reversed_bounds(self):self.reject("\t14\t14\t14\t","\t11\t11\t11\t","RELATIVE_REVERSED_BOUNDS")
    def test_tool_warning(self):self.reject("RELATIVE_BEGIN", "Warning: pin not found\nRELATIVE_BEGIN", "RELATIVE_TOOL_DIAGNOSTIC")
    def test_no_completion(self):self.reject("RELATIVE_COMPLETE", "", "RELATIVE_INCOMPLETE")
    def test_missing_electrical(self):self.reject("RELATIVE_ELECTRICAL_END", "", "RELATIVE_ELECTRICAL_COVERAGE")

    def test_sequential_ack_requires_clock_to_q(self):
        p=dict(event="fire",phase={"CLK":{"pin":"phase/CLK"},"Q":{"pin":"phase/Q"}})
        c=dict(kind="sequential_ack",queries=[dict(id="ack:"+m,sink="in_ack",source_edge="rise",sink_edge="rise",mode=m) for m in ("min","max")])
        log="RELATIVE_BEGIN\n"
        for m in ("min","max"):
            log+=f"RELATIVE_ACK\tack:{m}\t30\t2\t1\nRELATIVE_ACK_POINTS\tack:{m}\tfire\tphase/CLK\tphase/Q\tin_ack\n"
        log+="RELATIVE_EVENT_SLEW\t0.5\t0.6\nRELATIVE_ELECTRICAL_BEGIN\nRELATIVE_ELECTRICAL_END\nRELATIVE_COMPLETE\n"
        self.assertEqual(len(r.parse(log,p,c)["rows"]),2)
        with self.assertRaisesRegex(ValueError,"RELATIVE_ACK_SEQUENTIAL_PATH"):
            r.parse(log.replace("\tphase/CLK", ""),p,c)


class MarginTests(unittest.TestCase):
    def test_request_slew_outside_common_context(self):
        results,plan,cell=arithmetic();results["request-0"]["event_slew_ns"]=[.5,.7]
        with self.assertRaisesRegex(ValueError,"RELATIVE_COMMON_SLEW_COVERAGE"):r.margins(results,plan,cell)

    def test_missing_event_slew(self):
        p,c,s=fixture()
        with self.assertRaisesRegex(ValueError,"RELATIVE_EVENT_SLEW_MISSING"):
            r.parse(s.replace("RELATIVE_EVENT_SLEW\t0.5\t0.6\n",""),p,c)

    def test_common_reference(self):
        results,plan,cell=arithmetic();v=r.margins(results,plan,cell)
        self.assertEqual(v["minimum_input_data_lag_ns"],5)
        self.assertEqual(v["minimum_zero_reuse_hold_ns"],4.5)
        self.assertEqual(v["minimum_ack_after_capture_ns"],3)
        self.assertFalse(v["physical_qualification"])

    def test_backpressure_is_not_hold_credit(self):
        results,plan,cell=arithmetic();before=r.margins(results,plan,cell)
        for v in results["request-0"]["rows"].values():v["delay_ns"]+=10000
        after=r.margins(results,plan,cell)
        self.assertEqual(after["minimum_zero_reuse_hold_ns"],before["minimum_zero_reuse_hold_ns"])

    def test_leaf_hold_debits_negative_data_offset_without_positive_credit(self):
        results,plan,cell=arithmetic();plan['leaf_anchored']=True
        results['common']['rows']['ack:min:rise'].update(end='ack',receiver_role='source')
        before=r.margins(results,plan,cell)
        results['data']['rows']['data:17:min:fall']['delay_ns']=-.03
        after=r.margins(results,plan,cell)
        self.assertAlmostEqual(after['minimum_zero_reuse_hold_ns'],before['minimum_zero_reuse_hold_ns']-.03)
        self.assertEqual([x['lane'] for x in after['lanes'] if x['zero_reuse_hold_margin_ns']<before['minimum_zero_reuse_hold_ns']],[17])

    def test_late_data_fails_setup(self):
        results,plan,cell=arithmetic();results["data"]["rows"]["data:17:max:fall"]["delay_ns"]=20
        v=r.margins(results,plan,cell)
        self.assertEqual([x["lane"] for x in v["lanes"] if x["maximum_input_data_lag_ns"]<0],[17])

    def test_early_ack_fails_hold(self):
        results,plan,cell=arithmetic();results["common"]["rows"]["ack:min:rise"]["delay_ns"]=0
        v=r.margins(results,plan,cell);self.assertEqual(v["minimum_zero_reuse_hold_ns"],-1.5)

    def test_late_capture_fails_exact_lane(self):
        results,plan,cell=arithmetic();results["common"]["rows"]["capture:44:max"]["delay_ns"]=12
        v=r.margins(results,plan,cell)
        self.assertEqual([x["lane"] for x in v["lanes"] if x["zero_reuse_hold_margin_ns"]<0],[44])

    def test_cell_aperture_uses_both_data_polarities(self):
        cell='pin (D) { timing () { timing_type : setup_rising; rise_constraint (t) { values ("0.1, 0.3"); } fall_constraint (t) { values ("0.2, 0.7"); } } timing () { timing_type : hold_rising; rise_constraint (t) { values ("-0.1, 0.4"); } fall_constraint (t) { values ("0.3, 0.2"); } } }'
        self.assertEqual(r.aperture({r.SC+"dffrnq_1":cell},"click"),dict(setup_ns=.7,hold_ns=.4))


if __name__=="__main__":unittest.main()
