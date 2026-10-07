# SPDX-License-Identifier: Apache-2.0
"""Prove the generated-reset adapter accepts correct wiring and rejects a missed
watchdog reset. The fixture uses only ordinary Verilog, independently of Chisel.
"""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_export import generated_reset_probe, vector_coverage_probe


class ResetProbeTest(unittest.TestCase):
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
