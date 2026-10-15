from test_quiescing_receipt_probe import add_native_request_fixture, request_fixture_rtl
# SPDX-License-Identifier: Apache-2.0
"""Independent mapping-stimulus controls; no production transition logic."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from check_export import control_background, control_program_bytes
from test_service_reply_receipt import add_control_token_fixture


class ControlBackgroundTest(unittest.TestCase):
    def test_capacity_uses_validated_inventory_and_not_observed_width(self):
        manifest=dict(top='FourPhaseSoc',design=dict(rtl_path='FourPhaseSoc',children=[dict(id='control')]))
        scopes={'arbitrary_observed_width':32}
        with tempfile.TemporaryDirectory(prefix='control-capacity-') as folder:
            directory=Path(folder)
            with patch('check_export.sram_scopes',return_value=set()) as validate:
                with self.assertRaisesRegex(ValueError,'CONTROL_PROBE_CAPACITY_MISSING'):
                    control_program_bytes(directory,manifest,scopes)
                for capacity in (4,12,1024,1028,2048,3072):
                    (directory/'sram.json').write_text(json.dumps(dict(program_bytes=capacity)))
                    self.assertEqual(control_program_bytes(directory,manifest,scopes),capacity)
                    validate.assert_called_with(directory,manifest['design'],scopes)
                (directory/'sram.json').write_text(json.dumps(dict(program_bytes=3)))
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_CONTROL_CAPACITY'):
                    control_program_bytes(directory,manifest,scopes)
            # A failed real macro/inventory validation must never grant capacity.
            with patch('check_export.sram_scopes',side_effect=ValueError('SRAM_INSTANCE_MISMATCH')):
                with self.assertRaisesRegex(ValueError,'SRAM_INSTANCE_MISMATCH'):
                    control_program_bytes(directory,manifest,scopes)
            self.assertIsNone(control_program_bytes(directory,dict(design={}),{}))

    def test_native_decode_vectors_preserve_coverage_and_reject_disconnected_mapping(self):
        for click in (False, True):
            top = "ClickSoc" if click else "FourPhaseSoc"
            left, right = ("left_storage", "right_storage") if click else ("left", "right")
            prefix = top + ".ca_child_control.ca_child_join"
            children = [{"id": name, "contract": {"primitives": [{"id": "payload",
                "rtl_path": prefix + ".ca_child_" + name + ".ca_primitive_payload",
                "ports": [{"name": "q", "width": width, "direction": "output"}]}]}}
                for name, width in ((left, 276), (right, 379))]
            add_control_token_fixture(children[0]["contract"],2048)
            manifest = {"top": top, "design": {"children": [{"id": "control", "contract": {
                "module": "ClickControl" if click else "FourPhaseControl",
                "children": [{"id": "join", "contract": {"children": children}}]}}]}}
            store_prefix = top + ".ca_child_i2c.ca_child_frame_store"
            banks = [{"id": f"payload{i}" if click else "payload",
                "model": "ChiselAsyncEventRegister_v1" if click else "ChiselAsyncClosingLatch_v1",
                "rtl_path": store_prefix + (f".ca_primitive_payload{i}" if click else
                    f".ca_child_storage{i}.ca_primitive_payload"),
                "ports": [{"name": "q", "width": 337, "direction": "output"}]} for i in range(4)]
            store = {"module": "ClickFrameStore" if click else "FourPhaseFrameStore"}
            if click:
                store["primitives"] = banks
            else:
                store["children"] = [{"id": f"storage{i}", "contract": {"primitives": [bank]}}
                                     for i, bank in enumerate(banks)]
            manifest["design"]["children"].append({"id": "i2c", "contract": {
                "children": [{"id": "frame_store", "contract": store}]}})
            scopes = {top: {"registers": {"fabric_housekeepingState_now": 32}},
                      top + ".ca_child_request_bridge": {"registers": {"state": 2}}}
            registers = [("reset", 1), ("fabric_housekeepingState_now", 32), ("fabric_hostFrames_count", 2),
                         ("fabric_mmioCommitPending", 1), ("fabric_mmioCommit_applicationWritable", 1),
                         ("fabric_hostFrames_first_bank", 2)]
            drivers = [(top + "." + name, width) for name, width in registers] + [
                (top + ".ca_child_request_bridge.state", 2),
                (prefix + ".ca_child_" + left + ".ca_primitive_payload.q", 276),
                (prefix + ".ca_child_" + right + ".ca_primitive_payload.q", 379)] + [
                (bank["rtl_path"] + ".q", 337) for bank in banks]
            inventory={}
            add_native_request_fixture(manifest,scopes,inventory)
            drivers += [(path+'.'+name,width) for path,regs in inventory.items() for name,width in regs.items()
                        if path != top+'.ca_child_request_bridge']
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
            augmented, count = control_background(original, manifest, scopes, 1, 2048)
            self.assertGreater(count, 100)
            self.assertTrue(augmented.startswith(prelude + header + "#1; check;\n"))
            self.assertIn(coverage, augmented)
            self.assertEqual(control_background(original, {"design": {}}, {}, 1), (original, 1))
            bad = copy.deepcopy(scopes); bad[top]["registers"]["fabric_housekeepingState_now"] = 31
            with self.assertRaisesRegex(ValueError, "CONTROL_PROBE_DRIVER_MISMATCH"):
                control_background(original, manifest, bad, 1, 2048)
            with self.assertRaisesRegex(ValueError, "CONTROL_PROBE_SHAPE_CHANGED"):
                control_background("", manifest, scopes, 1, 2048)
            for stimulus, broken, diagnostic in ((original, False, "INACTIVE_ENDPOINT"),
                    (augmented, False, f"CONTRACT_PROBES_PASS:{count}"),
                    (augmented, True, "BINDING_MISMATCH")):
                declarations = "\n".join(f"reg [{width-1}:0] {name}=0;" for name, width in registers)
                bank_declarations = "\n".join(
                    f"Payload #(337) ca_primitive_payload{i}();" if click else
                    f"Storage #(337) ca_child_storage{i}();" for i in range(4))
                rtl = f'''
module Payload #(parameter W=1); reg [W-1:0] q=0; endmodule
module Storage #(parameter W=1); Payload #(W) ca_primitive_payload(); endmodule
module Join;
Storage #(276) ca_child_{left}(); Storage #(379) ca_child_{right}();
endmodule
module Control; Join ca_child_join(); endmodule
{request_fixture_rtl()}
module FrameStore; {bank_declarations} endmodule
module I2c; FrameStore ca_child_frame_store(); endmodule
module {top};
{declarations}
Control ca_child_control(); NativeCore ca_child_core();
Request ca_child_request_bridge(ca_child_core.ca_child_address.ca_primitive_payload.q);
I2c ca_child_i2c();
wire [378:0] c=ca_child_control.ca_child_join.ca_child_{right}.ca_primitive_payload.q;
wire [275:0] s=ca_child_control.ca_child_join.ca_child_{left}.ca_primitive_payload.q;
wire host=c[378:376]==0;
wire [31:0] candidate={{c[144:137],c[136:129],c[128:121],c[120:113]}};
wire period=host && c[375:370]==5 && c[112:105]==7;
wire [98:0] expected={{
  ca_child_request_bridge.data_address==4 ? fabric_housekeepingState_now : 32'b0,
  host && c[375:370]==9 && c[112:105]==2 && s[275:273]==1,
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
