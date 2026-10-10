# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_application_reset import validate_application_reset


class ApplicationResetTest(unittest.TestCase):
    def fixture(self,top):
        names=["core","transactions","request_bridge","completion","admission","admission_grant_bridge"]+[
            "completion_"+n+"_bridge" for n in ("plan","memory","telemetry","housekeeping")]
        m=dict(top=top,design=dict(children=[dict(id=n,contract=dict(primitives=[
            dict(parameters=dict(DELAY_FS="210200001"))],timing=[dict(budget=dict(max_fs="10000000"))])) for n in names]))
        s={top:dict(registers=dict(release_0=8))}
        rtl="""wire applicationResetRequest = reset | watchdog_;
wire _systemReset_output = |{applicationResetRequest, release_0};
assign systemReset = _systemReset_output;
always @(posedge serviceClock or posedge applicationResetRequest) begin
  if (applicationResetRequest) release_0 <= 8'hFF;
  else release_0 <= {release_0[6:0], 1'h0};
end
"""
        return m,s,rtl

    def test_actual_hold_logic_is_required_and_mutations_fail_closed(self):
        for top in ("FourPhaseSoc","ClickSoc"):
            m,s,rtl=self.fixture(top);validate_application_reset(m,s,rtl)
            for old,new in (("8'hFF","8'h03"),("posedge serviceClock","posedge workClock"),
                            (" or posedge applicationResetRequest",""),("[6:0]","[5:0]"),
                            ("if (applicationResetRequest)","if (applicationResetRequest && release_0 == 0)"),
                            ("reset | watchdog_","reset"),("|{applicationResetRequest, release_0}","|release_0"),
                            ("assign systemReset = _systemReset_output","assign systemReset = applicationResetRequest")):
                with self.assertRaisesRegex(ValueError,"APPLICATION_RESET_HOLD_LOGIC"):
                    validate_application_reset(m,s,rtl.replace(old,new))
            bad=copy.deepcopy(s);bad[top]["registers"]["release_0"]=2
            with self.assertRaisesRegex(ValueError,"APPLICATION_RESET_HOLD_REGISTER"):
                validate_application_reset(m,bad,rtl)

    def test_every_application_child_and_nested_timing_bound_is_audited(self):
        m,s,rtl=self.fixture("ClickSoc")
        for i in range(len(m["design"]["children"])):
            bad=copy.deepcopy(m);bad["design"]["children"].pop(i)
            with self.assertRaisesRegex(ValueError,"APPLICATION_RESET_ISLAND_INVENTORY"):
                validate_application_reset(bad,s,rtl)
            for key in ("DELAY_FS","max_fs"):
                bad=copy.deepcopy(m);bad["design"]["children"][i]["contract"]["children"]=[dict(contract={key:"250000001"})]
                with self.assertRaisesRegex(ValueError,"APPLICATION_RESET_SETTLEMENT_BUDGET"):
                    validate_application_reset(bad,s,rtl)

    def test_additional_application_children_cannot_escape_the_budget(self):
        for top in ("FourPhaseSoc","ClickSoc"):
            m,s,rtl=self.fixture(top)
            m["design"]["children"].append(dict(id="future_application_owner",contract=dict(children=[])))
            validate_application_reset(m,s,rtl)
            for key in ("DELAY_FS","max_fs"):
                bad=copy.deepcopy(m)
                bad["design"]["children"][-1]["contract"]["children"]=[dict(contract={key:"300000000"})]
                with self.assertRaisesRegex(ValueError,"APPLICATION_RESET_SETTLEMENT_BUDGET"):
                    validate_application_reset(bad,s,rtl)

if __name__=="__main__":unittest.main()
