// SPDX-License-Identifier: Apache-2.0
package riscay
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class DesyncChipSpec extends AnyFunSuite {
  test("actual exported shell runs through POR hold, parks, wakes and recovers power") {
    val p=SocParameters(McuConfiguration(32,32,7,Vector.empty,
      ApplicationProfile(1,1,"desync-shell",Vector.empty,Vector.empty)),
      watchdogCycles=1000000,lowPower=Some(LowPowerParameters.gf180Slow))
    SynchronousSimulation.run(new riscay.desync.DesyncSoc(p),"desync-chip",s"""
module Testbench;
timeunit 1ns;timeprecision 1ps;
reg powerGood;
reg watchdogClock=0,reset=0,scl=1,sda=1,adcMiso=0;
reg [31:0] gpioIn=0;
wire [31:0] gpioOut,gpioOe;
wire systemReset;
DesyncSocChip dut(.powerGood(powerGood),.watchdogClock(watchdogClock),
  .reset(reset),.scl(scl),.sda(sda),.gpioIn(gpioIn),.adcMiso(adcMiso),
  .gpioOut(gpioOut),.gpioOe(gpioOe),.systemReset(systemReset));
${DesyncSimulation.bounds("dut.fastRegion",50)}
always #100000 watchdogClock=~watchdogClock;
integer edges=0,startEdges,saved;
always @(posedge dut.serviceClock) edges=edges+1;
initial begin #50000000;$$fatal(1,"DESYNC_SHELL_DEADLINE");end
task release_power; begin
  #200;startEdges=edges;powerGood=1;
  wait(dut.porReleased);
  if(edges-startEdges<100000) $$fatal(1,"DESYNC_POR_HOLD_BYPASSED");
  wait(!systemReset);
end endtask
initial begin
  // Match the supply-monitor model: assert POR after processes have installed
  // their event controls, rather than a pre-time-zero declaration assignment.
  #0;powerGood=0;
  release_power();
  wait(!dut.serviceClockEnable);#200;saved=edges;#1000;
  if(edges!=saved) $$fatal(1,"DESYNC_SHELL_DID_NOT_PARK");
  gpioIn=1;wait(edges>saved+3);
  wait(!dut.serviceClockEnable);#200;saved=edges;sda=0;
  wait(edges>saved+3);sda=1;
  @(posedge dut.serviceClock);#7;powerGood=0;#1;
  if(!systemReset || gpioOe || dut.porReleased || dut.serviceClock)
    $$fatal(1,"DESYNC_SHELL_POWER_FAIL");
  release_power();
  $$display("RISCAY_CLOCKED_PASS");$$finish;
end
endmodule
""",exportDesync=true,prepare=base => {
      SramInventory.write(base,p.config,synchronous=true,metadataFile="desync.json")
      riscay.desync.DesyncChip.write(base)
      Seq("DesyncClock.sv","DesyncSocChip.sv","riscay_reset_hold.sv","desync_models.sv")
        .map(s => base.resolve("chip").resolve(s).toString)
    })
  }
}
