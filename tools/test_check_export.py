# SPDX-License-Identifier: Apache-2.0
"""Prove the generated-reset adapter accepts correct wiring and rejects a missed
watchdog reset. The fixture uses only ordinary Verilog, independently of Chisel.
"""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_export import generated_reset_probe, vector_coverage_probe, probe_timeout, sleep_clock_background, register_file_background, sram_background, service_background


class ResetProbeTest(unittest.TestCase):
    def test_service_background_exercises_joint_states_and_rejects_broken_aliases(self):
        for top in ("FourPhaseSoc", "ClickSoc"):
            root = {"gate_first": 32, "gate_second": 32}
            if top == "ClickSoc": root["controlStart_stages"] = 2
            elapsed = {"returned_stages_0": 1, "returned_stages_1": 1, "active": 1, "consumed": 32}
            response = {"data_data": 32, "data_error": 1}
            inventories = {top: root, top+".ca_child_elapsed_scaler": elapsed}
            children = [{"id": "elapsed_scaler", "contract": {
                "module": "ElapsedTicks", "rtl_path": top+".ca_child_elapsed_scaler"}}]
            payload = top+".ca_child_core.ca_child_address.ca_primitive_payload.q"
            if top == "FourPhaseSoc":
                inventories[top+".ca_child_response_bridge"] = response
                children.append({"id": "core", "contract": {"children": [{"id": "address", "contract": {
                    "primitives": [{"id": "payload", "rtl_path": payload[:-2],
                        "ports": [{"name": "q", "width": 70, "direction": "output"}]}]}}]}})
            manifest = {"top": top, "design": {"children": children}}
            scopes = {path: {"registers": regs} for path,regs in inventories.items()}
            def declarations(regs):
                return "\n".join(f"reg [{width-1}:0] {name};" for name,width in regs.items())
            rtl = "module Elapsed;\n"+declarations(elapsed)+"\nendmodule\n"
            rtl += "module Response;\n"+declarations(response)+"\nendmodule\n"
            rtl += """module Payload; reg [69:0] q; endmodule
module Address; Payload ca_primitive_payload(); endmodule
module Core; Address ca_child_address(); endmodule
"""
            rtl += f"module {top}; reg reset;\n"+declarations(root)+"\nElapsed ca_child_elapsed_scaler();\n"
            rtl += "wire elapsed_valid = !ca_child_elapsed_scaler.active && ca_child_elapsed_scaler.returned_stages_1 && gate_second != ca_child_elapsed_scaler.consumed;\n"
            if top == "ClickSoc":
                width = 2
                rtl += "wire [1:0] expected = {&controlStart_stages, elapsed_valid};\n"
            else:
                width = 34
                rtl += """Core ca_child_core(); Response ca_child_response_bridge();
wire selected = ca_child_core.ca_child_address.ca_primitive_payload.q[69:68] == 1 &&
  ca_child_core.ca_child_address.ca_primitive_payload.q[67:36] == 32'h20000000;
wire [32:0] reply = selected ? {ca_child_response_bridge.data_data, ca_child_response_bridge.data_error} : 33'b0;
wire [33:0] expected = {elapsed_valid, reply};
"""
            rtl += f"wire [{width-1}:0] observed = expected;\nendmodule\n"
            header = f"force {top}.reset = 1'b0;\n" + "".join(
                f"force {path}.{name} = {bits}'h0;\n" for path,regs in inventories.items() for name,bits in regs.items())
            if top == "FourPhaseSoc": header += f"force {payload} = 70'h0;\n"
            header += "#1;\n"
            source = f"""module ContractProbe; timeunit 1ns; timeprecision 1ps;
reg [{width-1}:0] ones_0=0, zeros_0=0;
task check; begin
if ({top}.observed !== {top}.expected) $fatal(1,"BINDING_MISMATCH");
ones_0 = ones_0 | {top}.observed; zeros_0 = zeros_0 | ~{top}.observed;
end endtask
initial begin
force {top}.reset = 1'b1; #1;
{header}check;
if (ones_0 !== {width}'h{(1<<width)-1:x} || zeros_0 !== {width}'h{(1<<width)-1:x}) $fatal(1,"INACTIVE_ENDPOINT:observed");
$display("CONTRACT_PROBES_PASS:1"); $finish; end endmodule
"""
            extended, count = service_background(source,manifest,scopes,1)
            self.assertGreater(count,1)
            self.assertTrue(extended.startswith(source[:source.index('if (ones_0 !==')]))
            self.assertIn(f'if ({top}.observed !== {top}.expected)',extended)
            import re
            allowed = {f"{path}.{name}" for path,regs in inventories.items() for name in regs} | {top+".reset",payload}
            self.assertLessEqual(set(re.findall(r"force (\S+) =",extended)),allowed)
            with tempfile.TemporaryDirectory(prefix="riscay-service-probe-") as folder:
                path = Path(folder)
                for stimulus,model,diagnostic in ((source,rtl,"INACTIVE_ENDPOINT"),(extended,rtl,"CONTRACT_PROBES_PASS"),
                        (extended,rtl.replace("observed = expected;","observed = expected ^ 1'b1;"),"BINDING_MISMATCH")):
                    (path/"test.sv").write_text(model+stimulus)
                    built = subprocess.run(["iverilog","-g2012","-s",top,"-s","ContractProbe","-o","sim.vvp","test.sv"],
                        cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(built.returncode,0,built.stderr)
                    result = subprocess.run(["vvp","sim.vvp"],cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(result.returncode == 0,diagnostic == "CONTRACT_PROBES_PASS",result.stdout)
                    self.assertIn(diagnostic,result.stdout)
            for bits in (None,31):
                bad=copy.deepcopy(scopes)
                if bits is None: del bad[top]["registers"]["gate_second"]
                else: bad[top]["registers"]["gate_second"]=bits
                with self.assertRaisesRegex(ValueError,"SERVICE_PROBE_DRIVER_MISMATCH"):
                    service_background(source,manifest,bad,1)
            with self.assertRaisesRegex(ValueError,"SERVICE_PROBE_DRIVER_MISMATCH"):
                service_background(source.replace(f"force {top}.gate_second = 32'h0;\n",""),manifest,scopes,1)
            if top == "FourPhaseSoc":
                bad=copy.deepcopy(manifest)
                bad["design"]["children"][1]["contract"]["children"][0]["contract"]["primitives"][0]["ports"][0]["width"]=69
                with self.assertRaisesRegex(ValueError,"SERVICE_PROBE_DRIVER_MISMATCH"):
                    service_background(source,bad,scopes,1)

    def test_sram_background_adds_joint_idle_and_all_tags_without_masking_mapping(self):
        for top in ("FourPhaseSoc", "ClickSoc"):
            root = {"gate_enabled": 1, "fabric_controlOutstanding": 1}
            for bank in ("program", "ram"):
                root.update({f"fabric_{bank}_state": 2, f"fabric_{bank}_tag": 2, f"fabric_{bank}_result": 8})
            sync = {f"{group}_{stage}": 1 for group in ("returned_stages", "bytesReturned_stages",
                "bytesReturned_stages_1", "bytesReturned_stages_2", "bytesReturned_stages_3") for stage in (0, 1)}
            sync["active"] = 1
            reply = {"state": 2, "data_programWrite": 1, "data_state_received": 32, "data_state_loaderWord": 32}
            request = {"state": 2, "data_operation": 2, "data_address": 32, "data_data": 32, "data_mask": 4}
            inventories = {top: root, top+".ca_child_control_reply_bridge": reply,
                           top+".ca_child_request_bridge": request}
            for bank in ("program", "ram"):
                inventories[top+f".ca_child_{bank}_access"] = sync
            scopes = {path: {"registers": regs} for path, regs in inventories.items()}
            manifest = {"top": top, "design": {"children": [{"id": bank+"_access", "contract": {
                "module": "SramAccess", "rtl_path": top+f".ca_child_{bank}_access"}} for bank in ("program", "ram")]}}
            def declarations(regs):
                return "\n".join(f"reg [{width-1}:0] {name};" for name,width in regs.items())
            rtl = "module Access;\n"+declarations(sync)+"\nwire idle = !active && " + " && ".join(
                name for name in sync if name.endswith("_1")) + "; endmodule\n"
            rtl += "module Reply;\n"+declarations(reply)+"\nendmodule\n"
            rtl += "module Request;\n"+declarations(request)+"\nendmodule\n"
            rtl += f"module {top}; reg reset;\n"+declarations(root)+"""
Access ca_child_program_access(); Access ca_child_ram_access();
Reply ca_child_control_reply_bridge(); Request ca_child_request_bridge();
wire program_valid = ca_child_program_access.idle && gate_enabled && fabric_controlOutstanding &&
    ca_child_control_reply_bridge.state == 2 && ca_child_control_reply_bridge.data_programWrite;
wire ram_valid = ca_child_ram_access.idle && gate_enabled && ca_child_request_bridge.state == 2 &&
    ca_child_request_bridge.data_operation == 2 && ca_child_request_bridge.data_address == 32'h20000000;
wire [7:0] lanes = { (4'b1 << fabric_program_tag) & {4{fabric_program_state == 3}},
                     (4'b1 << fabric_ram_tag) & {4{fabric_ram_state == 3}} };
wire [9:0] expected = {program_valid, ram_valid, lanes};
wire [9:0] observed = expected;
endmodule
"""
            header = f"force {top}.reset = 1'b0;\n" + "".join(
                f"force {path}.{name} = {width}'h0;\n" for path,regs in inventories.items() for name,width in regs.items()) + "#1;\n"
            source = f"""module ContractProbe; timeunit 1ns; timeprecision 1ps;
reg [9:0] ones_0=0, zeros_0=0;
task check; begin
if ({top}.observed !== {top}.expected) $fatal(1,"BINDING_MISMATCH");
ones_0 = ones_0 | {top}.observed; zeros_0 = zeros_0 | ~{top}.observed;
end endtask
initial begin
force {top}.reset = 1'b1; #1;
{header}check;
if (ones_0 !== 10'h3ff || zeros_0 !== 10'h3ff) $fatal(1,"INACTIVE_ENDPOINT:observed");
$display("CONTRACT_PROBES_PASS:1"); $finish; end endmodule
"""
            extended, count = sram_background(source, manifest, scopes, 1)
            self.assertGreater(count, 1)
            self.assertIn('if (ones_0 !==', extended)
            self.assertIn(f'if ({top}.observed !== {top}.expected)', extended)
            allowed = {f"{path}.{name}" for path,regs in inventories.items() for name in regs} | {top+".reset"}
            import re
            self.assertLessEqual(set(re.findall(r"force (\S+) =", extended)), allowed)
            with tempfile.TemporaryDirectory(prefix="riscay-sram-probe-") as folder:
                path = Path(folder)
                for stimulus, model, diagnostic in ((source,rtl,"INACTIVE_ENDPOINT"),
                        (extended,rtl,"CONTRACT_PROBES_PASS"),
                        (extended,rtl.replace("observed = expected;", "observed = expected ^ 10'b1;"),"BINDING_MISMATCH")):
                    (path/"test.sv").write_text(model+stimulus)
                    built = subprocess.run(["iverilog","-g2012","-s",top,"-s","ContractProbe","-o","sim.vvp","test.sv"],
                        cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(built.returncode,0,built.stderr)
                    result = subprocess.run(["vvp","sim.vvp"],cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(result.returncode == 0, diagnostic == "CONTRACT_PROBES_PASS",result.stdout)
                    self.assertIn(diagnostic,result.stdout)
            for width in (None,2):
                bad=copy.deepcopy(scopes)
                registers=bad[top+".ca_child_program_access"]["registers"]
                if width is None: del registers["returned_stages_1"]
                else: registers["returned_stages_1"]=width
                with self.assertRaisesRegex(ValueError,"SRAM_PROBE_DRIVER_MISMATCH"):
                    sram_background(source,manifest,bad,1)
            bad=copy.deepcopy(manifest);bad["design"]["children"].pop()
            with self.assertRaisesRegex(ValueError,"SRAM_PROBE_OWNER_MISMATCH"):
                sram_background(source,bad,scopes,1)

    def test_register_file_background_adds_activity_without_masking_bad_mapping(self):
        manifest = {"top": "RfTop", "design": {"module": "ArchitecturalRegisters", "primitives": [
            {"id": "x1", "rtl_path": "RfTop.data", "ports": [{"name": "q", "direction": "output", "width": 32}]}]}}
        stimulus = "initial begin\nforce RfTop.reset = 1'b1; #1;\n"
        checks = 0
        for control in (0, 1):
            for name, width in (("reset",1),("index",5),("data.q",32)):
                stimulus += f"force RfTop.{name} = {width}'h{control if width==1 else 0:x};\n"
            stimulus += "#1;\n"
            for name, width in (("reset",1),("index",5),("data.q",32)):
                for bit in range(width):
                    for value in (1<<bit,((1<<width)-1)^(1<<bit)):
                        stimulus += f"force RfTop.{name} = {width}'h{value:x};\n#1; check;\n"
                        checks += 1
                stimulus += f"force RfTop.{name} = {width}'h{control if width==1 else 0:x};\n#1;\n"
        prelude = '''module ContractProbe; timeunit 1ns; timeprecision 1ps;
reg [31:0] ones_0=0, zeros_0=0;
task check; integer i; begin
if(RfTop.observed !== RfTop.expected) $fatal(1,"BINDING_MISMATCH");
for(i=0;i<32;i=i+1) begin
if(RfTop.observed[i] === 1'b1) ones_0[i]=1;
if(RfTop.observed[i] === 1'b0) zeros_0[i]=1;
end
end endtask
'''
        coverage = 'if (ones_0 !== 32\'hffffffff || zeros_0 !== 32\'hffffffff) $fatal(1,"INACTIVE_ENDPOINT:RfTop.observed");\n'
        original = prelude + stimulus + coverage + f'$display("CONTRACT_PROBES_PASS:{checks}"); $finish; end endmodule'
        augmented, count = register_file_background(original, manifest, checks)
        self.assertEqual(count, checks*3//2)
        self.assertTrue(augmented.startswith(prelude + stimulus))
        self.assertIn(coverage, augmented)
        self.assertEqual(register_file_background(original,{"design":{}},checks),(original,checks))
        with self.assertRaisesRegex(ValueError,"PROBE_SHAPE_CHANGED"):
            register_file_background("",manifest,checks)
        bad = copy.deepcopy(manifest); bad["design"]["primitives"][0]["ports"][0]["width"]=31
        with self.assertRaisesRegex(ValueError,"DRIVER_MISMATCH"):
            register_file_background(original,bad,checks)
        for source, broken, diagnostic in ((original,False,"INACTIVE_ENDPOINT"),
                                           (augmented,False,f"CONTRACT_PROBES_PASS:{count}"),
                                           (augmented,True,"BINDING_MISMATCH")):
            with tempfile.TemporaryDirectory(prefix="riscay-register-probe-") as folder:
                path=Path(folder)
                rtl='''module Bank; reg [31:0] q=0; endmodule
module RfTop;
reg reset=0; reg [4:0] index=0; Bank data();
wire [31:0] expected=index==1 ? data.q : 0;
wire [31:0] observed=%s;
endmodule
''' % ("32'b0" if broken else "expected")
                (path/"test.sv").write_text(rtl+source)
                built=subprocess.run(["iverilog","-g2012","-s","RfTop","-s","ContractProbe","-o","sim.vvp","test.sv"],
                                     cwd=path,capture_output=True,text=True,timeout=30)
                self.assertEqual(built.returncode,0,built.stderr)
                result=subprocess.run(["vvp","sim.vvp"],cwd=path,capture_output=True,text=True,timeout=30)
                self.assertIn(diagnostic,result.stdout)
                self.assertEqual(result.returncode==0,"CONTRACT_PROBES_PASS" in diagnostic)

    def test_sleep_background_adds_coverage_and_keeps_mapping_failures(self):
        manifest = {"top": "SleepTop"}
        scopes = {"SleepTop": {"registers": {"gate_enabled": 1}}}
        checks = 0
        stimulus = "initial begin\nforce SleepTop.reset = 1'b1; #1;\n"
        drivers = ("reset", "gate_enabled", "request", "returned", "response")
        for control in (0, 1):
            stimulus += "".join(f"force SleepTop.{name} = 1'h{control};\n" for name in drivers) + "#1;\n"
            for name in drivers:
                for value in (1, 0):
                    stimulus += f"force SleepTop.{name} = 1'h{value};\n#1; check;\n"
                    checks += 1
                stimulus += f"force SleepTop.{name} = 1'h{control};\n#1;\n"
        prelude = '''module ContractProbe;
timeunit 1ns; timeprecision 1ps;
reg ones_0=0, zeros_0=0;
task check; begin
if(SleepTop.observed !== SleepTop.expected) $fatal(1,"BINDING_MISMATCH");
if(SleepTop.observed === 1'b1) ones_0=1;
if(SleepTop.observed === 1'b0) zeros_0=1;
end endtask
'''
        coverage = 'if (ones_0 !== 1\'h1 || zeros_0 !== 1\'h1) $fatal(1,"INACTIVE_ENDPOINT:SleepTop.observed");\n'
        original = prelude + stimulus + coverage + f'$display("CONTRACT_PROBES_PASS:{checks}"); $finish; end endmodule'
        augmented, count = sleep_clock_background(original, manifest, scopes, checks)
        self.assertEqual(count, 30)
        # Original stimulus and every assertion remain intact; only more cases
        # and the completion count are added.
        self.assertTrue(augmented.startswith(prelude + stimulus))
        self.assertIn(coverage, augmented)
        with self.assertRaisesRegex(ValueError, "REGISTER_MISMATCH"):
            sleep_clock_background(original, manifest, {}, checks)
        with self.assertRaisesRegex(ValueError, "SHAPE_CHANGED"):
            sleep_clock_background("", manifest, scopes, checks)
        for source, broken, diagnostic in ((original, False, "INACTIVE_ENDPOINT"),
                                           (augmented, False, "CONTRACT_PROBES_PASS:30"),
                                           (augmented, True, "BINDING_MISMATCH")):
            with tempfile.TemporaryDirectory(prefix="riscay-sleep-probe-") as folder:
                path = Path(folder)
                rtl = '''module SleepTop;
reg reset=0, gate_enabled=0, request=0, returned=0, response=0;
wire expected=gate_enabled & (request ^ returned) & ~response;
wire observed=%s;
endmodule
''' % ("1'b0" if broken else "expected")
                (path / "test.sv").write_text(rtl + source)
                built = subprocess.run(["iverilog", "-g2012", "-s", "SleepTop", "-s", "ContractProbe", "-o", "sim.vvp", "test.sv"],
                                       cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(built.returncode, 0, built.stderr)
                result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                self.assertIn(diagnostic, result.stdout)
                self.assertEqual(result.returncode == 0, "CONTRACT_PROBES_PASS" in diagnostic)

    def test_timeout_extension_only_targets_generated_probe(self):
        self.assertEqual(probe_timeout(["vvp", "contract_probe.vvp"], 60, 601, 602), 601)
        self.assertEqual(probe_timeout(["iverilog", "-o", "contract_probe.vvp", "contract_probe.sv"], 60, 601, 602), 602)
        self.assertEqual(probe_timeout(("iverilog.exe", "-o", "contract_probe.vvp", "contract_probe.sv"), 60, 601, 602), 602)
        for command in (["vvp", "sim.vvp"], ["iverilog", "-o", "contract_probe.vvp", "design.sv"],
                        ["iverilog", "-o", "other.vvp", "contract_probe.sv"],
                        ["unrelated", "contract_probe.vvp"], [], "vvp contract_probe.vvp"):
            self.assertEqual(probe_timeout(command, 60, 601, 602), 60)

    manifest = {"top": "FourPhaseSoc", "design": {
        "endpoints": [{"id": "system_reset", "width": 1,
                       "source": "~|FourPhaseSoc>systemReset", "rtl_path": "FourPhaseSoc.systemReset"}],
        "children": [{"contract": {"rtl_path": "FourPhaseSoc.core", "children": []}}]}}

    def test_fails_closed_on_missing_endpoint_or_changed_checker(self):
        broken = copy.deepcopy(self.manifest)
        broken["design"]["endpoints"] = []
        with self.assertRaisesRegex(ValueError, "ENDPOINT_MISMATCH"):
            generated_reset_probe("", broken)
        with self.assertRaisesRegex(ValueError, "CHECK_SHAPE_CHANGED"):
            generated_reset_probe("", self.manifest)

    def test_real_reset_mismatch_is_rejected(self):
        body = '''module ContractProbe;
timeunit 1ns; timeprecision 1ps;
task check; begin
if (FourPhaseSoc.core.reset !== FourPhaseSoc.reset) $fatal(1, "RESET_BINDING_MISMATCH");
end endtask
initial begin
#1; check;
FourPhaseSoc.watchdog=1; #1; check;
FourPhaseSoc.reset=1; #1; check;
$display("RESET_TEST_PASS"); $finish;
end endmodule
'''
        body = generated_reset_probe(body, self.manifest)
        for correct in (True, False):
            with tempfile.TemporaryDirectory(prefix="riscay-reset-probe-") as folder:
                path = Path(folder)
                rtl = '''module Child(input reset); endmodule
module FourPhaseSoc;
reg reset=0, watchdog=0;
wire systemReset=reset|watchdog;
Child core(.reset(%s));
endmodule
''' % ("systemReset" if correct else "reset")
                (path / "test.sv").write_text(rtl + body)
                compile_result = subprocess.run(["iverilog", "-g2012", "-s", "FourPhaseSoc", "-s", "ContractProbe",
                                                 "-o", "sim.vvp", "test.sv"], cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
                result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                if correct:
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertIn("RESET_TEST_PASS", result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("RESET_BINDING_MISMATCH", result.stdout)
                    self.assertNotIn("RESET_TEST_PASS", result.stdout)

    def test_persistent_control_and_descendants_must_use_por(self):
        manifest = copy.deepcopy(self.manifest)
        names = {"control": "FourPhaseControl", "control_command_bridge": "DecoupledToFourPhase",
                 "control_reply_bridge": "FourPhaseToDecoupled"}
        for name, model in names.items():
            manifest["design"]["children"].append({"id": name, "contract": {
                "rtl_path": "FourPhaseSoc." + name, "module": model, "children": []}})
        manifest["design"]["children"][1]["contract"]["children"] = [{"id": "storage", "contract": {
            "rtl_path": "FourPhaseSoc.control.storage", "module": "Storage", "children": []}}]
        paths = ["core", "control", "control.storage", "control_command_bridge", "control_reply_bridge"]
        checks = "\n".join(f'if (FourPhaseSoc.{p}.reset !== FourPhaseSoc.reset) $fatal(1, "RESET_BINDING_MISMATCH");' for p in paths)
        probe = generated_reset_probe('module ContractProbe; task check; begin\n' + checks + '''
end endtask
initial begin #1; check; FourPhaseSoc.watchdog=1; #1; check;
FourPhaseSoc.reset=1; #1; check; $display("MIXED_RESET_PASS"); $finish; end endmodule
''', manifest)
        for broken in (None, "core", "control", "storage", "control_command_bridge", "control_reply_bridge"):
            with tempfile.TemporaryDirectory(prefix="riscay-persistent-reset-") as folder:
                path = Path(folder)
                def pin(name):
                    correct = "systemReset" if name == "core" else "reset"
                    return ("reset" if name == "core" else "systemReset") if broken == name else correct
                rtl = '''module Child(input reset); endmodule
module Control(input reset, input systemReset);
Child storage(.reset(%s)); endmodule
module FourPhaseSoc;
reg reset=0, watchdog=0; wire systemReset=reset|watchdog;
Child core(.reset(%s));
Control control(.reset(%s),.systemReset(systemReset));
Child control_command_bridge(.reset(%s)); Child control_reply_bridge(.reset(%s)); endmodule
''' % (pin("storage"), pin("core"), pin("control"), pin("control_command_bridge"), pin("control_reply_bridge"))
                (path / "test.sv").write_text(rtl + probe)
                built = subprocess.run(["iverilog", "-g2012", "-s", "FourPhaseSoc", "-s", "ContractProbe", "-o", "sim.vvp", "test.sv"],
                                       cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(built.returncode, 0, built.stderr)
                result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode == 0, broken is None, result.stdout)
                self.assertIn("MIXED_RESET_PASS" if broken is None else "RESET_BINDING_MISMATCH", result.stdout)
        bad = copy.deepcopy(manifest); bad["design"]["children"].pop()
        with self.assertRaisesRegex(ValueError, "RESET_INVENTORY"):
            generated_reset_probe("", bad)
        bad = copy.deepcopy(manifest); bad["design"]["children"][1]["contract"]["module"] = "Unknown"
        with self.assertRaisesRegex(ValueError, "RESET_OWNER"):
            generated_reset_probe("", bad)

    def test_persistent_telemetry_and_descendants_must_use_por(self):
        manifest = copy.deepcopy(self.manifest)
        names = {"telemetry": "FourPhaseTelemetry", "telemetry_command_bridge": "DecoupledToFourPhase",
                 "telemetry_reply_bridge": "FourPhaseToDecoupled"}
        for name, model in names.items():
            manifest["design"]["children"].append({"id": name, "contract": {
                "rtl_path": "FourPhaseSoc." + name, "module": model, "children": []}})
        manifest["design"]["children"][1]["contract"]["children"] = [{"id": "storage", "contract": {
            "rtl_path": "FourPhaseSoc.telemetry.storage", "module": "Storage", "children": []}}]
        paths = ["core", "telemetry", "telemetry.storage", "telemetry_command_bridge", "telemetry_reply_bridge"]
        checks = "\n".join(f'if (FourPhaseSoc.{p}.reset !== FourPhaseSoc.reset) $fatal(1, "RESET_BINDING_MISMATCH");' for p in paths)
        probe = generated_reset_probe('module ContractProbe; task check; begin\n' + checks + '''
end endtask
initial begin #1; check; FourPhaseSoc.watchdog=1; #1; check;
FourPhaseSoc.reset=1; #1; check; $display("MIXED_RESET_PASS"); $finish; end endmodule
''', manifest)
        for broken in (None, "core", "telemetry", "storage", "telemetry_command_bridge", "telemetry_reply_bridge"):
            with tempfile.TemporaryDirectory(prefix="riscay-persistent-reset-") as folder:
                path = Path(folder)
                def pin(name):
                    correct = "systemReset" if name == "core" else "reset"
                    return ("reset" if name == "core" else "systemReset") if broken == name else correct
                rtl = '''module Child(input reset); endmodule
module Telemetry(input reset, input systemReset);
Child storage(.reset(%s)); endmodule
module FourPhaseSoc;
reg reset=0, watchdog=0; wire systemReset=reset|watchdog;
Child core(.reset(%s));
Telemetry telemetry(.reset(%s),.systemReset(systemReset));
Child telemetry_command_bridge(.reset(%s)); Child telemetry_reply_bridge(.reset(%s)); endmodule
''' % (pin("storage"), pin("core"), pin("telemetry"), pin("telemetry_command_bridge"), pin("telemetry_reply_bridge"))
                (path / "test.sv").write_text(rtl + probe)
                built = subprocess.run(["iverilog", "-g2012", "-s", "FourPhaseSoc", "-s", "ContractProbe", "-o", "sim.vvp", "test.sv"],
                                       cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(built.returncode, 0, built.stderr)
                result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode == 0, broken is None, result.stdout)
                self.assertIn("MIXED_RESET_PASS" if broken is None else "RESET_BINDING_MISMATCH", result.stdout)
        bad = copy.deepcopy(manifest); bad["design"]["children"].pop()
        with self.assertRaisesRegex(ValueError, "RESET_INVENTORY"):
            generated_reset_probe("", bad)
        bad = copy.deepcopy(manifest); bad["design"]["children"][1]["contract"]["module"] = "Unknown"
        with self.assertRaisesRegex(ValueError, "RESET_OWNER"):
            generated_reset_probe("", bad)

    def test_persistent_supervisor_and_descendants_must_use_por(self):
        manifest = copy.deepcopy(self.manifest)
        names = {"supervisor": "FourPhaseSupervisor", "supervisor_command_bridge": "DecoupledToFourPhase",
                 "supervisor_reply_bridge": "FourPhaseToDecoupled"}
        for name, model in names.items():
            manifest["design"]["children"].append({"id": name, "contract": {
                "rtl_path": "FourPhaseSoc." + name, "module": model, "children": []}})
        manifest["design"]["children"][1]["contract"]["children"] = [{"id": "storage", "contract": {
            "rtl_path": "FourPhaseSoc.supervisor.storage", "module": "Storage", "children": []}}]
        paths = ["core", "supervisor", "supervisor.storage", "supervisor_command_bridge", "supervisor_reply_bridge"]
        checks = "\n".join(f'if (FourPhaseSoc.{p}.reset !== FourPhaseSoc.reset) $fatal(1, "RESET_BINDING_MISMATCH");' for p in paths)
        probe = generated_reset_probe('module ContractProbe; task check; begin\n' + checks + '''
end endtask
initial begin #1; check; FourPhaseSoc.watchdog=1; #1; check;
FourPhaseSoc.reset=1; #1; check; $display("MIXED_RESET_PASS"); $finish; end endmodule
''', manifest)
        for broken in (None, "core", "supervisor", "storage", "supervisor_command_bridge", "supervisor_reply_bridge"):
            with tempfile.TemporaryDirectory(prefix="riscay-persistent-reset-") as folder:
                path = Path(folder)
                def pin(name):
                    correct = "systemReset" if name == "core" else "reset"
                    return ("reset" if name == "core" else "systemReset") if broken == name else correct
                rtl = '''module Child(input reset); endmodule
module Supervisor(input reset, input systemReset);
Child storage(.reset(%s)); endmodule
module FourPhaseSoc;
reg reset=0, watchdog=0; wire systemReset=reset|watchdog;
Child core(.reset(%s));
Supervisor supervisor(.reset(%s),.systemReset(systemReset));
Child supervisor_command_bridge(.reset(%s)); Child supervisor_reply_bridge(.reset(%s)); endmodule
''' % (pin("storage"), pin("core"), pin("supervisor"), pin("supervisor_command_bridge"), pin("supervisor_reply_bridge"))
                (path / "test.sv").write_text(rtl + probe)
                built = subprocess.run(["iverilog", "-g2012", "-s", "FourPhaseSoc", "-s", "ContractProbe", "-o", "sim.vvp", "test.sv"],
                                       cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(built.returncode, 0, built.stderr)
                result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode == 0, broken is None, result.stdout)
                self.assertIn("MIXED_RESET_PASS" if broken is None else "RESET_BINDING_MISMATCH", result.stdout)
        bad = copy.deepcopy(manifest); bad["design"]["children"].pop()
        with self.assertRaisesRegex(ValueError, "RESET_INVENTORY"):
            generated_reset_probe("", bad)
        bad = copy.deepcopy(manifest); bad["design"]["children"][1]["contract"]["module"] = "Unknown"
        with self.assertRaisesRegex(ValueError, "RESET_OWNER"):
            generated_reset_probe("", bad)

    def test_sram_owners_and_nested_bridges_require_por(self):
        for top in ("FourPhaseSoc", "ClickSoc"):
            manifest = copy.deepcopy(self.manifest)
            manifest = json.loads(json.dumps(manifest).replace("FourPhaseSoc", top))
            descendants = ["native", "command_bridge", "reply_bridge"] + [
                f"byte_{kind}_{lane}" for kind in ("request", "reply") for lane in range(4)]
            for name in ("program_access", "ram_access"):
                manifest["design"]["children"].append({"id": name, "contract": {
                    "rtl_path": f"{top}.{name}", "module": "SramAccess", "children": [
                        {"id": part, "contract": {"rtl_path": f"{top}.{name}.{part}", "module": "Child", "children": []}}
                        for part in descendants]}})
            paths = ["core"] + [name + suffix for name in ("program_access", "ram_access")
                                for suffix in [""] + ["." + part for part in descendants]]
            checks = "\n".join(f'if ({top}.{p}.reset !== {top}.reset) $fatal(1, "RESET_BINDING_MISMATCH");' for p in paths)
            probe = generated_reset_probe("module ContractProbe; task check; begin\n" + checks + f'''
end endtask
initial begin #1; check; {top}.watchdog=1; #1; check;
{top}.reset=1; #1; check; $display("SRAM_RESET_PASS"); $finish; end endmodule
''', manifest)
            for broken in (None, *paths):
                with tempfile.TemporaryDirectory(prefix="riscay-sram-reset-") as folder:
                    path = Path(folder)
                    def pin(part):
                        correct = "systemReset" if part == "core" else "reset"
                        return ("reset" if part == "core" else "systemReset") if broken == part else correct
                    modules = []
                    for name in ("program_access", "ram_access"):
                        children = "\n".join(f'Child {part}(.reset({pin(name+"."+part)}));' for part in descendants)
                        modules.append(f"module {name}_model(input reset,input systemReset); {children} endmodule")
                    rtl = "module Child(input reset); endmodule\n" + "\n".join(modules) + f"""
module {top};
reg reset=0, watchdog=0; wire systemReset=reset|watchdog;
Child core(.reset({pin("core")}));
program_access_model program_access(.reset({pin("program_access")}),.systemReset(systemReset));
ram_access_model ram_access(.reset({pin("ram_access")}),.systemReset(systemReset));
endmodule
"""
                    (path / "test.sv").write_text(rtl + probe)
                    built = subprocess.run(["iverilog", "-g2012", "-s", top, "-s", "ContractProbe", "-o", "sim.vvp", "test.sv"],
                                           cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode == 0, broken is None, result.stdout)
                    self.assertIn("SRAM_RESET_PASS" if broken is None else "RESET_BINDING_MISMATCH", result.stdout)
            bad = copy.deepcopy(manifest); bad["design"]["children"].pop()
            with self.assertRaisesRegex(ValueError, "RESET_INVENTORY"):
                generated_reset_probe("", bad)
            bad = copy.deepcopy(manifest); bad["design"]["children"][1]["contract"]["module"] = "Unknown"
            with self.assertRaisesRegex(ValueError, "RESET_OWNER"):
                generated_reset_probe("", bad)

    def test_scaling_i2c_spi_roots_native_state_and_bridges_must_use_por(self):
        for name, model in (("elapsed_scaler", "ElapsedTicks"), ("sample_scaler", "SampleScaler"), ("i2c", "I2cTarget"), ("spi_adc", "SpiAdc")):
            manifest = copy.deepcopy(self.manifest)
            child = {"rtl_path": "FourPhaseSoc." + name, "module": model, "children": []}
            manifest["design"]["children"].append({"id": name, "contract": child})
            descendants = ("native", "command_bridge", "reply_bridge", "wave_bridge", "capture_bridge")
            for part in descendants:
                child["children"].append({"id": part, "contract": {
                    "rtl_path": "FourPhaseSoc." + name + "." + part, "module": "Child", "children": []}})
            paths = ["core", name] + [name + "." + part for part in descendants]
            checks = "\n".join(f'if (FourPhaseSoc.{p}.reset !== FourPhaseSoc.reset) $fatal(1, "RESET_BINDING_MISMATCH");' for p in paths)
            probe = generated_reset_probe('module ContractProbe; task check; begin\n' + checks + '''
end endtask
initial begin #1; check; FourPhaseSoc.watchdog=1; #1; check;
FourPhaseSoc.reset=1; #1; check; $display("SCALING_RESET_PASS"); $finish; end endmodule
''', manifest)
            for broken in (None, "core", name, *descendants):
                with tempfile.TemporaryDirectory(prefix="riscay-scaling-reset-") as folder:
                    path = Path(folder)
                    def pin(part):
                        correct = "systemReset" if part == "core" else "reset"
                        return ("reset" if part == "core" else "systemReset") if broken == part else correct
                    rtl = f'''module Child(input reset); endmodule
module Scaler(input reset,input systemReset);
Child native(.reset({pin("native")})); Child command_bridge(.reset({pin("command_bridge")}));
Child reply_bridge(.reset({pin("reply_bridge")}));
Child wave_bridge(.reset({pin("wave_bridge")})); Child capture_bridge(.reset({pin("capture_bridge")})); endmodule
module FourPhaseSoc;
reg reset=0, watchdog=0; wire systemReset=reset|watchdog;
Child core(.reset({pin("core")})); Scaler {name}(.reset({pin(name)}),.systemReset(systemReset)); endmodule
'''
                    (path / "test.sv").write_text(rtl + probe)
                    built = subprocess.run(["iverilog", "-g2012", "-s", "FourPhaseSoc", "-s", "ContractProbe", "-o", "sim.vvp", "test.sv"],
                                           cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode == 0, broken is None, result.stdout)
                    self.assertIn("SCALING_RESET_PASS" if broken is None else "RESET_BINDING_MISMATCH", result.stdout)
            child["module"] = "Unknown"
            with self.assertRaisesRegex(ValueError, "RESET_OWNER"):
                generated_reset_probe("", manifest)

    def test_packed_coverage_matches_scalar_for_all_four_state_vectors(self):
        # Every 4-bit vector over {0,1,X,Z}; both empty and accumulated coverage.
        manifest = {"design": {"endpoints": [{"rtl_path": "value", "width": 4}], "children": []}}
        scalar = "\n".join(line for bit in range(4) for line in (
            f"if (value[{bit}] === 1'b1) ones_0[{bit}] = 1'b1;",
            f"if (value[{bit}] === 1'b0) zeros_0[{bit}] = 1'b1;"))
        task = vector_coverage_probe("task check; begin\n" + scalar + "\nend endtask", manifest)
        with self.assertRaisesRegex(ValueError, "COVERAGE_CHECK_SHAPE_CHANGED"):
            vector_coverage_probe("", manifest)
        fixture = """module Test;
reg [3:0] value, ones_0, zeros_0, expected_one, expected_zero;
integer iteration, b, k;
""" + task + """
initial begin
ones_0=0; zeros_0=0; expected_one=0; expected_zero=0;
for(k=0;k<2;k=k+1) for(iteration=0;iteration<256;iteration=iteration+1) begin
  if(k==0) begin ones_0=0; zeros_0=0; expected_one=0; expected_zero=0; end
  for(b=0;b<4;b=b+1) case((iteration >> (2*b)) & 3)
    0: value[b]=0; 1: value[b]=1; 2: value[b]=1'bx; 3: value[b]=1'bz;
  endcase
  for(b=0;b<4;b=b+1) begin
    if(value[b] === 1'b1) expected_one[b]=1;
    if(value[b] === 1'b0) expected_zero[b]=1;
  end
  check;
  if(ones_0 !== expected_one || zeros_0 !== expected_zero) $fatal(1,"COVERAGE_NOT_EQUIVALENT");
end
$display("COVERAGE_EQUIVALENCE_PASS"); $finish;
end endmodule
"""
        with tempfile.TemporaryDirectory(prefix="riscay-coverage-") as folder:
            path = Path(folder)
            (path / "test.sv").write_text(fixture)
            built = subprocess.run(["iverilog", "-g2012", "-s", "Test", "-o", "sim.vvp", "test.sv"],
                                   cwd=path, capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("COVERAGE_EQUIVALENCE_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
