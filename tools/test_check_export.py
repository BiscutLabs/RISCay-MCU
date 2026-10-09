# SPDX-License-Identifier: Apache-2.0
"""Prove the generated-reset adapter accepts correct wiring and rejects a missed
watchdog reset. The fixture uses only ordinary Verilog, independently of Chisel.
"""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_export import generated_reset_probe, vector_coverage_probe, probe_timeout, sleep_clock_background, register_file_background


class ResetProbeTest(unittest.TestCase):
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

    def test_scaling_roots_arithmetic_and_bridges_must_use_por(self):
        for name, model in (("elapsed_scaler", "ElapsedTicks"), ("sample_scaler", "SampleScaler")):
            manifest = copy.deepcopy(self.manifest)
            child = {"rtl_path": "FourPhaseSoc." + name, "module": model, "children": []}
            manifest["design"]["children"].append({"id": name, "contract": child})
            descendants = ("native", "command_bridge", "reply_bridge")
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
Child reply_bridge(.reset({pin("reply_bridge")})); endmodule
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
