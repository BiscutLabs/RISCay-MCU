// SPDX-License-Identifier: Apache-2.0
package riscay
import org.scalatest.funsuite.AnyFunSuite

class DesyncClockSpec extends AnyFunSuite {
  private def bench(fault: String="", half: Double=50, porWidth: Double=200): String = s"""
module Testbench;
timeunit 1ns;timeprecision 1ps;
reg reset=1,run=1;wire clockOut;
DesyncClock dut(.*);
${DesyncSimulation.bounds("dut",half)}
$fault
integer rises=0,saved,i;
real lastRise=-1000,lastFall=-1000;
reg checkHigh=0,checkLow=0;
// POR may abort a pulse. Exempt only the interval containing POR, then check
// every complete high/low interval again, including the first resumed pulse.
always @(posedge reset) begin checkHigh=0;checkLow=0;end
always @(posedge clockOut) begin
  if(checkLow && $$realtime-lastFall<49.999) $$fatal(1,"DESYNC_RUNT_LOW");
  if(reset || !dut.mutex.grant1 || dut.mutex.grant0) $$fatal(1,"DESYNC_UNGRANTED_CLOCK");
  lastRise=$$realtime;rises=rises+1;checkHigh=1;
end
always @(negedge clockOut) begin
  if(!reset && checkHigh && $$realtime-lastRise<49.999) $$fatal(1,"DESYNC_RUNT_HIGH");
  lastFall=$$realtime;checkLow=!reset;
end
always @(dut.mutex.grant0 or dut.mutex.grant1) begin
  #0;if(dut.mutex.grant0 && dut.mutex.grant1) $$fatal(1,"DESYNC_DOUBLE_GRANT");
end
always @(negedge dut.controller.pauseRequest) if(!reset && !dut.mutex.grant0)
  $$fatal(1,"DESYNC_PENDING_STOP_WITHDRAWN");
initial begin #100000;$$fatal(1,"DESYNC_GENERATOR_DEADLINE");end
initial begin
  #200;reset=0;repeat(4) @(posedge clockOut);
  for(i=0;i<100;i=i+1) begin
    // Sweep the entire phase, including a wake while pause arbitration resolves.
    #(1+(i*17)%110);run=0;
    if(i%3==0) begin #0.001;run=1;repeat(2) @(posedge clockOut);run=0;end
    #200;saved=rises;#200;
    if(clockOut || rises!=saved || !dut.mutex.grant0) $$fatal(1,"DESYNC_NOT_STOPPED");
    run=1;repeat(2) @(posedge clockOut);
    if(i%7==0) begin
      #(7+(i*13)%100);reset=1;#0.001;
      if(clockOut || dut.mutex.grant0 || dut.mutex.grant1 || dut.controller.cycleRequest || dut.controller.pauseRequest)
        $$fatal(1,"DESYNC_POR_NOT_CLEAR");
      #${porWidth-0.001};reset=0;repeat(2) @(posedge clockOut);
    end
  end
  $$display("RISCAY_CLOCKED_PASS");$$finish;
end
endmodule
"""
  test("pausible generator completes pulses, retains racing stops, resumes and resets") {
    SynchronousSimulation.run(new riscay.desync.DesyncClock,"desync-source",bench(),prototypeClock=true)
  }
  test("pulse monitor detects a shortened model delay") {
    val bad=bench(half=1)
    val e=intercept[IllegalArgumentException] {
      SynchronousSimulation.run(new riscay.desync.DesyncClock,"desync-short-delay",bad,prototypeClock=true)
    };assert(e.getMessage.contains("DESYNC_RUNT_"),e.getMessage)
  }
  test("grant monitor detects bypassed arbitration") {
    val e=intercept[IllegalArgumentException] {
      SynchronousSimulation.run(new riscay.desync.DesyncClock,"desync-bypass",
        bench("initial begin #1000;force dut.mutex.grant0=1;force dut.mutex.grant1=1;end"),prototypeClock=true)
    };assert(e.getMessage.contains("DESYNC_DOUBLE_GRANT"),e.getMessage)
  }
  test("short POR cancels stale events and resumes with complete pulses") {
    SynchronousSimulation.run(new riscay.desync.DesyncClock,"desync-short-reset",
      bench(porWidth=1),prototypeClock=true)
  }
}
