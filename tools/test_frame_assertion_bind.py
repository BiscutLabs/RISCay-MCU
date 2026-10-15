# SPDX-License-Identifier: Apache-2.0
"""Exact coordinated assertion-layer owner selection, with no simulator."""
from pathlib import Path
import tempfile
import unittest

from check_frame_integration import (assertion_wrapper_policy,
    coordinated_request_assertion_model, _HEADER)


class FrameAssertionBindTests(unittest.TestCase):
    def fixture(self, directory, model, retained):
        variant = "Click" if model == "ClickSoc" else "FourPhase"
        request = variant + ("QuiescingReceipt" if retained else "QuiescingToDecoupled_1")
        rtl = f"module {model}(); {request} ca_child_request_bridge (.clock(serviceClock)); endmodule"
        (directory / (model + ".sv")).write_text(rtl)
        header = "".join(f"`ifndef {m}_\n`ifdef {m}\n`define {m}_ (`{m})\n`else\n`define {m}_ 1\n`endif\n`endif\n"
                         for m in ("STOP_COND", "ASSERT_VERBOSE_COND")) + _HEADER
        blocks = "\n".join(f'always @(posedge {model}.clock) begin if(1) begin if(`ASSERT_VERBOSE_COND_)$error("{label}");if(`STOP_COND_)$fatal;end\nend // always @(posedge)'
            for label in ("CONTROL_HOST_MAILBOX_OVERFLOW", "two", "three", "four", "five", "six", "seven"))
        raw = header + f"module {model}_Verification_Assert();\n`ifndef SYNTHESIS\n" + blocks + "\n`endif\nendmodule\n"
        children = ["DecoupledTo" + variant + "Quiescing", "DecoupledTo" + variant + "Quiescing_1",
                    variant + "QuiescingToDecoupled", "I2cTarget", request]
        guard = "layers_" + model + "_Verification_Assert"
        binding = f'`ifndef {guard}\n`define {guard}\n`include "layers-{model}-Verification.sv"\n'
        binding += "".join(f'`include "layers-{name}-Verification-Assert.sv"\n' for name in children)
        binding += f"bind {model} {model}_Verification_Assert verification_assert ();\n`endif\n"
        path = directory / "verification/assert" / ("layers-" + model + "-Verification-Assert.sv")
        path.parent.mkdir(parents=True); path.write_text(binding)
        return raw, binding, path, rtl, request

    def check(self, directory, model, raw):
        assertion_wrapper_policy(directory, model, raw, "CONTROL_HOST_MAILBOX_OVERFLOW", "OVERFLOW_ASSERTION", True)

    def test_both_protocols_and_exact_stored_or_retained_owner(self):
        for model in ("FourPhaseSoc", "ClickSoc"):
            for retained in (False, True):
                with self.subTest(model=model, retained=retained), tempfile.TemporaryDirectory() as folder:
                    directory = Path(folder); raw, _, _, _, request = self.fixture(directory, model, retained)
                    self.assertEqual(coordinated_request_assertion_model(directory, model, "OVERFLOW_ASSERTION"), request)
                    self.check(directory, model, raw)

    def test_layer_is_chosen_from_unique_actual_owner_not_include(self):
        for model in ("FourPhaseSoc", "ClickSoc"):
            with tempfile.TemporaryDirectory() as folder:
                directory=Path(folder); raw, _, _, rtl, request=self.fixture(directory,model,True)
                source=directory/(model+".sv")
                for text in (rtl.replace(request,"UnknownReceiver"), rtl.replace(request,"ClickQuiescingReceipt" if model=="FourPhaseSoc" else "FourPhaseQuiescingReceipt"),
                             rtl.replace("ca_child_request_bridge","different_instance"), rtl+rtl,
                             rtl.replace(request,request+"_1")):
                    source.write_text(text)
                    with self.assertRaisesRegex(ValueError,"FRAME_INTEGRATION_OVERFLOW_ASSERTION_REQUEST_OWNER$"):
                        self.check(directory,model,raw)

    def test_parameterized_or_malformed_instance_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);raw,_,_,rtl,request=self.fixture(directory,"FourPhaseSoc",True)
            source=directory/'FourPhaseSoc.sv'
            for text,diagnostic in ((rtl.replace(request,request+" #(.WIDTH(70))"),"INSTANCE_PARAMETERS:ca_child_request_bridge"),
                                    (rtl.replace(".clock(serviceClock)",".clock(serviceClock), .clock(other)"),"PIN_SYNTAX:ca_child_request_bridge")):
                source.write_text(text)
                with self.assertRaisesRegex(ValueError,"FRAME_INTEGRATION_"+diagnostic+"$"):
                    self.check(directory,"FourPhaseSoc",raw)

    def test_exact_include_order_guard_and_bind_remain_mandatory(self):
        for model in ("FourPhaseSoc", "ClickSoc"):
            for retained in (False,True):
                with tempfile.TemporaryDirectory() as folder:
                    directory=Path(folder);raw,binding,path,_,request=self.fixture(directory,model,retained)
                    entry=f'`include "layers-{request}-Verification-Assert.sv"\n'
                    other=request.replace("QuiescingReceipt","QuiescingToDecoupled_1") if retained else request.replace("QuiescingToDecoupled_1","QuiescingReceipt")
                    faults=[binding.replace(request,other),binding.replace(entry,""),binding.replace(entry,entry+entry),
                            binding.replace(entry,"").replace('`include "layers-I2cTarget',entry+'`include "layers-I2cTarget'),
                            binding.replace("bind "+model+" ","bind Other "),binding.replace("verification_assert ()","verification_wrong ()"),
                            binding.replace("`ifndef layers_","`ifdef layers_",1),binding+"`define DISABLE_ASSERTION 1\n"]
                    for faulty in faults:
                        path.write_text(faulty)
                        with self.assertRaisesRegex(ValueError,"FRAME_INTEGRATION_OVERFLOW_ASSERTION_BIND$"):
                            self.check(directory,model,raw)

    def test_new_owner_does_not_relax_assertion_execution_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);raw,_,_,_,_=self.fixture(directory,"FourPhaseSoc",True)
            self.check(directory,"FourPhaseSoc",raw)
            for mutant,diagnostic in ((raw.replace("module FourPhaseSoc_Verification_Assert();\n`ifndef SYNTHESIS","module FourPhaseSoc_Verification_Assert();\n`ifdef SYNTHESIS"),"WRAPPER"),
                                     (raw.replace("`define STOP_COND_ 1","`define STOP_COND_ 0"),"HEADER"),
                                     (raw.replace("always @(posedge FourPhaseSoc.clock)","initial",1),"OWNERSHIP")):
                with self.assertRaisesRegex(ValueError,"FRAME_INTEGRATION_OVERFLOW_ASSERTION_"+diagnostic+"$"):
                    self.check(directory,"FourPhaseSoc",mutant)


if __name__ == "__main__":
    unittest.main()
