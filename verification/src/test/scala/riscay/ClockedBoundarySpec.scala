// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class ClockedRecoveryFixture(p: SocParameters) extends ClockedFabricFixture(p) {
  val recovery=IO(Input(Bool()))
  applicationResetRequest:=reset.asBool || watchdog.io.expired || recovery
  val cancel=IO(Output(Bool()));cancel:=cpuResetActive
  val work=IO(Output(Clock()));work:=workClock
  val samplePublished=IO(Output(Bool()));samplePublished:=BoringUtils.bore(fabric.publish(0).valid)
  val sampleAge=IO(Output(UInt(32.W)));sampleAge:=BoringUtils.bore(fabric.hostSamples(0).age)
}

class ClockedBoundarySpec extends AnyFunSuite {
  val config=McuConfiguration(256,256,7,Vector(MeasurementChannel(0,"sample",2,0)),
    ApplicationProfile(1,1,"clocked-boundary",Vector(HostRegister(0,"WORD")),Vector.empty))
  val tasks="""
task offer(input [1:0] op,input [31:0] addr,input [31:0] data);begin
  @(negedge serviceClock);request_valid=1;request_bits_operation=op;
  request_bits_address=addr;request_bits_data=data;request_bits_mask=15;
  @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);
  #1;request_valid=0;
end endtask
task answer(input [31:0] expected);begin
  wait(response_valid);if(response_bits_error || response_bits_data!==expected)
    $fatal(1,"CLOCKED_BOUNDARY_REPLY actual=%h expected=%h",response_bits_data,expected);
  @(negedge serviceClock);response_ready=1;@(posedge serviceClock);#1;response_ready=0;
end endtask
task write_bus(input [31:0] addr,input [31:0] data);begin offer(2,addr,data);answer(0);end endtask
task read_bus(input [31:0] addr,input [31:0] expected);begin offer(1,addr,0);answer(expected);end endtask
real workEdge=-100;
always @(posedge work) workEdge=$realtime;
always @(gpioOut or gpioOe) if(!reset && !systemReset && !cancel && resetSettled && $realtime!=workEdge)
  $fatal(1,"CLOCKED_GPIO_CHANGED_OFF_EDGE");
integer phase;
"""
  for(retain <- Seq(false,true)) test(s"clocked recovery retains committed RAM, cancels replies and preserves only configured GPIO ($retain)") {
    val p=SocParameters(config,watchdogCycles=1000000,spiBoot=true,retainGpioOnWatchdog=retain)
    ClockedSimulation.run(new ClockedRecoveryFixture(p),"clocked-reset-commit",s"""
      wait(resetSettled);
      for(phase=0;phase<8;phase=phase+1) begin
        write_bus(32'h30000034,32'h12345678);
        write_bus(32'h30000018,127);write_bus(32'h3000001c,127);
        offer(2,32'h20000000,32'h10203040+phase);
        // The SRAM word is already accepted. Watchdog assertion must neither
        // truncate it nor expose its completion to the next application.
        #(3+phase*11);recovery=1;#2500;recovery=0;
        wait(!systemReset);wait(resetSettled);#2000;
        if(response_valid) $$fatal(1,"CLOCKED_STALE_REPLY_AFTER_RESET");
        read_bus(32'h20000000,32'h10203040+phase);
        read_bus(32'h30000034,0);
        read_bus(32'h30000018,${if(retain) 0x47 else 0});
        read_bus(32'h3000001c,${if(retain) 0x47 else 0});
        if((gpioOe&56)!=0) $$fatal(1,"CLOCKED_SPI_NOT_RELEASED");
      end
      read_words(0,0,8);if(snapshot[0+:32]!==8) $$fatal(1,"CLOCKED_CRASH_COUNT");
      reset=1;#2000;reset=0;#3000;
      if(gpioOe || gpioOut) $$fatal(1,"CLOCKED_POR_GPIO");
      read_bus(32'h30000034,0);
    """,tasks,synchronous=true)
  }
  test("clocked ADC age begins at acquisition admission across a stopped service clock") {
    val p=SocParameters(config,staleMs=3000,watchdogCycles=1000000,
      adc=Some(AdcParameters(halfPeriodCycles=100)),lowPower=Some(LowPowerParameters(stopServiceClock=false)))
    ClockedSimulation.run(new ClockedRecoveryFixture(p),"clocked-adc-age","""
      // Discarded first conversion, then a real acquisition. Preserve LF time
      // while the conversion is suspended; completion must not make it fresh.
      @(negedge adcCsN);@(posedge adcCsN);@(negedge adcCsN);
      #1000;clockEnabled=0;#40000000;clockEnabled=1;
      wait(samplePublished);@(posedge serviceClock);#1;
      if(sampleAge<4000) $fatal(1,"CLOCKED_ADC_AGE_RESTARTED_AT_COMPLETION age=%d",sampleAge);
    """,tasks,referenceHalfPeriodNs=1250,synchronous=true)
  }
}
