# SPDX-License-Identifier: Apache-2.0
"""Fast-source timing contracts; these are not analog feasibility tests."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "soc/src/main/resources/riscay/riscay_service_osc_model.sv"


class ServiceOscillatorTest(unittest.TestCase):
    def simulate(self, body, parameters="", rejected=False):
        output = ROOT / "build/oscillator-tests"
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as tmp:
            base = Path(tmp)
            (base / "test.sv").write_text("""module Testbench;
timeunit 1ns; timeprecision 1ps;
reg enable=0; wire clk; integer edges=0, saved; real lastRise=0, startTime;
riscay_service_osc #(%s) dut(enable,clk);
always @(posedge clk) begin edges=edges+1; lastRise=$realtime; end
always @(negedge clk) if(lastRise > 0 && $realtime-lastRise < 49.999) $fatal(1,"RUNT_HIGH_PULSE");
initial begin #2000000; $fatal(1,"TIMEOUT"); end
initial begin
%s
$display("SERVICE_MODEL_PASS"); $finish;
end
endmodule
""" % (parameters, body))
            result = subprocess.run(["iverilog", "-g2012", "-s", "Testbench", "-o", "sim.vvp",
                                     str(MODEL), "test.sv"], cwd=base, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(["vvp", "sim.vvp"], cwd=base, capture_output=True, text=True, timeout=30)
            if rejected:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("INVALID_SERVICE_OSCILLATOR_MODEL", result.stdout)
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count("SERVICE_MODEL_PASS"), 1)

    def test_cancel_startup_stop_full_pulse_and_restart(self):
        self.simulate("""
enable=1; #10000; enable=0; #1; enable=1; startTime=$realtime;
@(posedge clk);
if($realtime-startTime != 100000) $fatal(1,"STARTUP_CONTRACT");
@(posedge clk); #10; enable=0;
@(negedge clk); #1; saved=edges;
#200000; if(clk !== 0 || edges != saved) $fatal(1,"CLOCK_DID_NOT_STOP");
enable=1; startTime=$realtime; @(posedge clk);
if($realtime-startTime != 100000) $fatal(1,"RESTART_CONTRACT");
""")

    def test_startup_outside_required_bound_rejected(self):
        self.simulate("enable=1; #200000;", ".STARTUP_NS(100001)", rejected=True)

    def test_frequency_above_host_hold_bound_rejected(self):
        self.simulate("enable=1; #200000;", ".NOMINAL_HZ(20000001)", rejected=True)

    def test_frequency_below_i2c_phase_bound_rejected(self):
        self.simulate("enable=1; #200000;", ".NOMINAL_HZ(7999999)", rejected=True)
