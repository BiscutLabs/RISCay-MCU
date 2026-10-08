# SPDX-License-Identifier: Apache-2.0
"""Contract-model checks only; no analog/power characterization is implied."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "soc/src/main/resources/riscay/riscay_lf_osc_model.sv"


class OscillatorModelTest(unittest.TestCase):
    def simulate(self, parameters, body, success=True):
        output = ROOT / "build/oscillator-tests"
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as tmp:
            base = Path(tmp)
            source = """module Testbench;
timeunit 1ns; timeprecision 1ps;
reg enable=0; wire clk;
real previous, delta; integer n;
riscay_lf_osc #(%s) dut(enable,clk);
initial begin #2000000000; $fatal(1,"MODEL_TIMEOUT"); end
initial begin
%s
$display("MODEL_PASS"); $finish;
end
endmodule
""" % (parameters, body)
            (base / "test.sv").write_text(source)
            compile_result = subprocess.run(["iverilog", "-g2012", "-s", "Testbench", "-o", "sim.vvp",
                                             str(MODEL), "test.sv"], cwd=base, capture_output=True, text=True, timeout=30)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run(["vvp", "sim.vvp"], cwd=base, capture_output=True, text=True, timeout=30)
            if success:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count("MODEL_PASS"), 1)
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("INVALID_OSCILLATOR_MODEL", result.stdout)

    def test_startup_nominal_frequency_and_disable(self):
        self.simulate(".NOMINAL_HZ(4000), .STARTUP_NS(1000)", """
enable=1; #999; if(clk !== 0) $fatal(1,"STARTUP");
@(posedge clk); previous=$realtime;
repeat(4) begin
  @(posedge clk); delta=$realtime-previous; previous=$realtime;
  if(delta < 249999 || delta > 250001) $fatal(1,"NOMINAL_FREQUENCY");
end
enable=0; #300000; if(clk !== 0) $fatal(1,"DISABLE");
""")

    def test_frequency_error(self):
        self.simulate(".NOMINAL_HZ(4000), .STARTUP_NS(0), .ERROR_PPM(200000)", """
enable=1;
@(posedge clk); previous=$realtime;
@(posedge clk); delta=$realtime-previous;
if(delta < 208332 || delta > 208334) $fatal(1,"TRIM_DRIFT");
""")

    def test_bounded_jitter(self):
        self.simulate(".NOMINAL_HZ(4000), .STARTUP_NS(0), .JITTER_PPM(20000)", """
enable=1; @(posedge clk); previous=$realtime;
for(n=0;n<4;n=n+1) begin
  @(posedge clk); delta=$realtime-previous; previous=$realtime;
  if(delta < 244999 || delta > 255001) $fatal(1,"JITTER_BOUND");
  if(n % 2 == 0 && delta > 245001) $fatal(1,"MISSING_JITTER");
  if(n % 2 == 1 && delta < 254999) $fatal(1,"MISSING_JITTER");
end
""")

    def test_invalid_frequency_is_rejected(self):
        self.simulate(".STARTUP_NS(0), .ERROR_PPM(-1000000)", "enable=1; #1000000;", success=False)

    def test_slow_nominal_and_por_restart(self):
        self.simulate(".STARTUP_NS(16000000)", """
enable=1; #1000000; enable=0; #100; enable=1;
previous=$realtime;
@(posedge clk); if($realtime-previous != 16000000) $fatal(1,"POR_STARTUP_NOT_RESTARTED");
previous=$realtime; @(posedge clk); delta=$realtime-previous;
if(delta < 129354391 || delta > 129354393) $fatal(1,"SLOW_NOMINAL %f",delta);
enable=0; #1; if(clk !== 0) $fatal(1,"POR_ASSERTION");
""")


if __name__ == "__main__":
    unittest.main()
