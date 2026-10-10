# SPDX-License-Identifier: Apache-2.0
"""Independent mapping-stimulus controls; no production transition logic."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

from check_export import control_background


class ControlBackgroundTest(unittest.TestCase):
    def test_native_decode_vectors_preserve_coverage_and_reject_disconnected_mapping(self):
        for click in (False, True):
            top = "ClickSoc" if click else "FourPhaseSoc"
            left, right = ("left_storage", "right_storage") if click else ("left", "right")
            prefix = top + ".ca_child_control.ca_child_join"
            children = [{"id": name, "contract": {"primitives": [{"id": "payload",
                "rtl_path": prefix + ".ca_child_" + name + ".ca_primitive_payload",
                "ports": [{"name": "q", "width": width, "direction": "output"}]}]}}
                for name, width in ((left, 337), (right, 379))]
            manifest = {"top": top, "design": {"children": [{"id": "control", "contract": {
                "module": "ClickControl" if click else "FourPhaseControl",
                "children": [{"id": "join", "contract": {"children": children}}]}}]}}
            scopes = {top: {"registers": {"fabric_housekeepingState_now": 32}},
                      top + ".ca_child_request_bridge": {"registers": {"data_address": 32}}}
            registers = [("reset", 1), ("fabric_housekeepingState_now", 32), ("fabric_hostFrames_count", 2),
                         ("fabric_mmioCommitPending", 1), ("fabric_mmioCommit_applicationWritable", 1),
                         ("fabric_hostFrames_first_frame_length", 6),
                         ("fabric_hostFrames_first_frame_overflow", 1)] + [
                         (f"fabric_hostFrames_first_frame_bytes_{i}", 8) for i in range(33)]
            drivers = [(top + "." + name, width) for name, width in registers] + [
                (top + ".ca_child_request_bridge.data_address", 32),
                (prefix + ".ca_child_" + left + ".ca_primitive_payload.q", 337),
                (prefix + ".ca_child_" + right + ".ca_primitive_payload.q", 379)]
            prelude = f'''module ContractProbe; timeunit 1ns; timeprecision 1ps;
reg [98:0] ones_0=0, zeros_0=0;
task check; integer i; begin
if ({top}.observed !== {top}.expected) $fatal(1,"BINDING_MISMATCH");
for(i=0;i<99;i=i+1) begin
if ({top}.observed[i] === 1'b1) ones_0[i]=1;
if ({top}.observed[i] === 1'b0) zeros_0[i]=1;
end end endtask
initial begin
force {top}.reset = 1'b1; #1;
'''
            header = "".join(f"force {path} = {width}'h0;\n" for path, width in drivers) + "#1;\n"
            coverage = 'if (ones_0 !== {99{1\'b1}} || zeros_0 !== {99{1\'b1}}) $fatal(1,"INACTIVE_ENDPOINT:observed");\n'
            original = prelude + header + "#1; check;\n" + coverage + '$display("CONTRACT_PROBES_PASS:1"); $finish; end endmodule'
            augmented, count = control_background(original, manifest, scopes, 1)
            self.assertGreater(count, 100)
            self.assertTrue(augmented.startswith(prelude + header + "#1; check;\n"))
            self.assertIn(coverage, augmented)
            self.assertEqual(control_background(original, {"design": {}}, {}, 1), (original, 1))
            bad = copy.deepcopy(scopes); bad[top]["registers"]["fabric_housekeepingState_now"] = 31
            with self.assertRaisesRegex(ValueError, "CONTROL_PROBE_DRIVER_MISMATCH"):
                control_background(original, manifest, bad, 1)
            with self.assertRaisesRegex(ValueError, "CONTROL_PROBE_SHAPE_CHANGED"):
                control_background("", manifest, scopes, 1)
            for stimulus, broken, diagnostic in ((original, False, "INACTIVE_ENDPOINT"),
                    (augmented, False, f"CONTRACT_PROBES_PASS:{count}"),
                    (augmented, True, "BINDING_MISMATCH")):
                declarations = "\n".join(f"reg [{width-1}:0] {name}=0;" for name, width in registers)
                rtl = f'''
module Payload #(parameter W=1); reg [W-1:0] q=0; endmodule
module Storage #(parameter W=1); Payload #(W) ca_primitive_payload(); endmodule
module Join;
Storage #(337) ca_child_{left}(); Storage #(379) ca_child_{right}();
endmodule
module Control; Join ca_child_join(); endmodule
module Request; reg [31:0] data_address=0; endmodule
module {top};
{declarations}
Control ca_child_control(); Request ca_child_request_bridge();
wire [378:0] c=ca_child_control.ca_child_join.ca_child_{right}.ca_primitive_payload.q;
wire [336:0] s=ca_child_control.ca_child_join.ca_child_{left}.ca_primitive_payload.q;
wire host=c[378:376]==0;
wire [31:0] candidate={{c[144:137],c[136:129],c[128:121],c[120:113]}};
wire period=host && c[375:370]==5 && c[112:105]==7;
wire [98:0] expected={{
  ca_child_request_bridge.data_address==4 ? fabric_housekeepingState_now : 32'b0,
  host && c[375:370]==9 && c[112:105]==2 && s[336:334]==1,
  host && c[375:370]==1 && c[112:105]==8,
  period && candidate==1000,
  period ? candidate : 32'b0,
  c[378:376]==4 && c[102:101]==1 && c[100:69]==32'h30000004 && c[36:33]==15 ? c[32:1] : 32'b0}};
wire [98:0] observed={"{expected[98:1],1'b0}" if broken else "expected"};
endmodule
'''
                with tempfile.TemporaryDirectory(prefix="riscay-control-probe-") as folder:
                    path = Path(folder)
                    (path / "test.sv").write_text(rtl + stimulus, encoding="utf-8")
                    build = subprocess.run(["iverilog", "-g2012", "-s", top, "-s", "ContractProbe",
                        "-o", "sim.vvp", "test.sv"], cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    run = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertIn(diagnostic, run.stdout)
                    self.assertEqual(run.returncode == 0, "CONTRACT_PROBES_PASS" in diagnostic)


if __name__ == "__main__":
    unittest.main()
