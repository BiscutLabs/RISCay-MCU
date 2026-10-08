# SPDX-License-Identifier: Apache-2.0
"""Independent chip-boundary reset tests with production hold counts."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / 'soc/src/main/resources/riscay'


class ResetCircuitTest(unittest.TestCase):
    def simulate(self, body, hz=20000000, hold=100000):
        output = ROOT / 'build/reset-tests'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as tmp:
            base = Path(tmp)
            (base/'test.sv').write_text('''module Testbench;
timeunit 1ns; timeprecision 1ps;
reg reset=0, work=0; wire good, clk, released;
wire enabled=good && (!released || work);
riscay_supply_monitor #(.SETTLE_NS(100)) monitor(good);
riscay_service_osc #(.NOMINAL_HZ(%s),.STARTUP_NS(1000)) osc(good,enabled,clk);
riscay_reset_hold #(.HOLD_CYCLES(%s)) dut(clk,good,reset,released);
integer edges=0, saved; real startTime;
always @(posedge clk) edges=edges+1;
initial begin #50000000; $fatal(1,"RESET_TIMEOUT"); end
initial begin
%s
$display("RESET_PASS"); $finish;
end
endmodule
''' % (hz, hold, body))
            sources = ['riscay_supply_monitor_model.sv', 'riscay_service_osc_model.sv', 'riscay_reset_hold.sv']
            p = subprocess.run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',
                                *[str(RESOURCES/s) for s in sources], 'test.sv'],
                               cwd=base,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stderr)
            p = subprocess.run(['vvp','sim.vvp'],cwd=base,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual(p.stdout.count('RESET_PASS'),1)

    def test_real_hold_at_both_frequency_bounds(self):
        for hz in (8000000,20000000):
            with self.subTest(hz=hz):
                self.simulate('''
wait(good); startTime=$realtime; wait(released); #1;
if($realtime-startTime < 5000000 || edges != 100002)
  $fatal(1,"PREMATURE_RELEASE edges=%d duration=%f",edges,$realtime-startTime);
#1000; saved=edges; #10000;
if(clk !== 0 || edges != saved) $fatal(1,"RESET_CLOCK_DID_NOT_STOP");
''',hz=hz)

    def test_brownout_during_hold_restarts_full_interval(self):
        self.simulate('''
wait(good); #3000000;
monitor.supply_voltage=2.9; #1;
if(released !== 0 || enabled !== 0) $fatal(1,"BROWNOUT_ASSERT");
#10000; monitor.supply_voltage=3.15; #10000;
if(good !== 0) $fatal(1,"NO_HYSTERESIS");
monitor.supply_voltage=3.3; startTime=$realtime;
wait(released); if($realtime-startTime < 5000000) $fatal(1,"REUSED_OLD_COUNT");
''')

    def test_manual_reset_and_power_failure_while_asleep(self):
        self.simulate('''
wait(released); #1000; if(clk !== 0) $fatal(1,"NOT_ASLEEP");
reset=1; #1; if(released !== 0 || !enabled) $fatal(1,"MANUAL_ASSERT");
#10000; reset=0; startTime=$realtime;
wait(released); if($realtime-startTime < 5000000) $fatal(1,"MANUAL_HOLD");
#1000; monitor.supply_voltage=0; #1;
if(released !== 0 || clk !== 0) $fatal(1,"POWER_LOSS_ASSERT");
#10000; monitor.supply_voltage=3.3; startTime=$realtime;
wait(released); if($realtime-startTime < 5000000) $fatal(1,"POWER_RETURN_HOLD");
''')

    def test_clock_failure_cannot_release_reset(self):
        self.simulate('''
wait(good); force clk=0; #6000000;
if(released !== 0) $fatal(1,"RELEASE_WITHOUT_CLOCK");
release clk; startTime=$realtime; wait(released);
if($realtime-startTime < 5000000) $fatal(1,"CLOCK_RETURN_HOLD");
''')

    def test_supply_plateau_does_not_boot(self):
        self.simulate('''
monitor.supply_voltage=2.8; #10000000;
if(good !== 0 || released !== 0 || edges != 0) $fatal(1,"LOW_SUPPLY_BOOT");
monitor.supply_voltage=3.3; startTime=$realtime; wait(released);
if($realtime-startTime < 5000000) $fatal(1,"PLATEAU_HOLD");
''')


if __name__ == '__main__': unittest.main()
