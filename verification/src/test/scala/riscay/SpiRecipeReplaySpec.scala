// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Compact-player retention and cadence tests, additional to the original
  * SpiAdcSpec wire/reset/age oracles.
  */
class SpiRecipeReplayFixture(click: Boolean, halfCycles: Int) extends FabricFixture(SocParameters(McuConfiguration(
    8,8,0,Vector.empty,ApplicationProfile(1,1,"spi-replay",Vector.empty,Vector.empty)),
    watchdogCycles=64,watchdogHoldCycles=32)) {
  val conversionStart=IO(Input(Bool())); val ageStep=IO(Input(UInt(32.W)))
  val conversionBusy=IO(Output(Bool())); val conversionDone=IO(Output(Bool()))
  val sampleValid=IO(Output(Bool())); val value=IO(Output(UInt(32.W))); val age=IO(Output(UInt(32.W)))
  watchdog.io.heartbeat:=false.B
  private val time = withClockAndReset(serviceClock,reset) { val t=RegInit(0.U(64.W)); t:=t+ageStep; t }
  private val timeNext=time+ageStep
  private def ageOf(timestamp: UInt): UInt = {val elapsed=timeNext-chisel3.util.experimental.BoringUtils.bore(timestamp); Mux(elapsed(63,32).orR,"hffffffff".U,elapsed(31,0))}
  private val pAdc=AdcParameters(halfCycles,50*halfCycles,25300,4095,offset = -100)
  if(click) {
    val adc=asyncChild("tested_spi_adc")(d => new riscay.click.SpiAdc(pAdc,false,d))
    adc.clock:=serviceClock; adc.io.start:=conversionStart; adc.io.upperTime:=timeNext; adc.miso:=adcMiso
    conversionBusy:=adc.io.busy; conversionDone:=adc.io.done; sampleValid:=adc.io.result.valid
    value:=adc.io.result.bits.value; age:=ageOf(adc.native.timestamp); adcCsN:=adc.csN; adcSclk:=adc.sclk
  } else {
    val adc=asyncChild("tested_spi_adc")(d => new riscay.bd.SpiAdc(pAdc,false,d))
    adc.clock:=serviceClock; adc.io.start:=conversionStart; adc.io.upperTime:=timeNext; adc.miso:=adcMiso
    conversionBusy:=adc.io.busy; conversionDone:=adc.io.done; sampleValid:=adc.io.result.valid
    value:=adc.io.result.bits.value; age:=ageOf(adc.native.timestamp); adcCsN:=adc.csN; adcSclk:=adc.sclk
  }
}

class SpiRecipeReplaySpec extends AnyFunSuite {
  private def monitor(halfCycles: Int): String = s"""
integer tickCount=0, edgeTick=0, wireEdges=0, completed=0, replies=0;
integer phase, residue, savedEdges, savedReplies;
reg tracking=0, savedCs, savedSclk, savedPlaying;
reg [4:0] savedSlot;
reg [31:0] savedSamples, savedDivider, wanted;
reg [15:0] word=16'hfabc, shift;
always @(posedge serviceClock) if(!reset) tickCount=tickCount+1;
always @(adcCsN or adcSclk) if(!reset && (tracking || !adcCsN)) begin
  if(serviceClock!==1'b1) $$fatal(1,"SPI_REPLAY_PIN_EDGE");
end
always @(negedge adcCsN) if(!reset) begin
  if(tracking || adcSclk || !conversionBusy) $$fatal(1,"SPI_REPLAY_START");
  tracking=1; wireEdges=0; edgeTick=tickCount; shift=word; adcMiso=shift[15];
end
always @(adcSclk) if(!reset && tracking) begin
  if(tickCount-edgeTick != $halfCycles) $$fatal(1,"SPI_REPLAY_EDGE_CADENCE");
  if(adcSclk !== (wireEdges%2 == 0)) $$fatal(1,"SPI_REPLAY_EDGE_ORDER");
  edgeTick=tickCount; wireEdges=wireEdges+1;
  if(!adcSclk) begin shift=shift<<1; adcMiso=shift[15]; end
end
always @(posedge adcCsN) if(!reset && tracking) begin
  #0.001;
  if(wireEdges!=32 || adcSclk) $$fatal(1,"SPI_REPLAY_TERMINAL_PINS");
  tracking=0; completed=completed+1;
end
always @(posedge serviceClock) if(!reset && conversionDone) replies=replies+1;
always @(posedge reset) tracking=0;
task launch(input [15:0] nextWord); begin
  wait(!conversionBusy); @(negedge serviceClock); word=nextWord; conversionStart=1;
  @(negedge serviceClock); conversionStart=0;
end endtask
task retire(input bit publish); begin
  wait(conversionDone); #1;
  wanted=(word & 4095)*25300/4095-100;
  if(sampleValid!==publish || value!==wanted || !conversionBusy)
    $$fatal(1,"SPI_REPLAY_RESULT");
  @(posedge serviceClock); #1;
  if(conversionDone || sampleValid) $$fatal(1,"SPI_REPLAY_DUPLICATE");
  wait(!conversionBusy);
end endtask
"""

  for(click <- Seq(false,true); halfCycles <- Seq(2,3,5)) {
    val name=if(click) "click" else "bd"
    test(s"$name SPI compact replay: every slot and divider residue retain state across a stopped physical clock ($halfCycles)") {
      ClockedSimulation.run(new SpiRecipeReplayFixture(click,halfCycles),s"$name-spi-replay-stopped-$halfCycles",s"""
        launch(16'hf123); retire(0);
        for(phase=0;phase<32;phase=phase+1) for(residue=0;residue<$halfCycles;residue=residue+1) begin
          launch(16'h5000 | ((phase*117+residue*43) & 4095));
          wait(!adcCsN); wait(wireEdges==phase);
          repeat(residue) @(posedge serviceClock);
          @(negedge serviceClock); #1; clockEnabled=0;
          savedCs=adcCsN; savedSclk=adcSclk; savedEdges=wireEdges; savedReplies=replies;
          savedSlot=dut.ca_child_tested_spi_adc.slot;
          savedPlaying=dut.ca_child_tested_spi_adc.playing;
          savedDivider=dut.ca_child_tested_spi_adc.divider;
          savedSamples=dut.ca_child_tested_spi_adc.samples;
          #1000;
          if(adcCsN!==savedCs || adcSclk!==savedSclk || wireEdges!=savedEdges || replies!=savedReplies ||
             dut.ca_child_tested_spi_adc.slot!==savedSlot ||
             dut.ca_child_tested_spi_adc.playing!==savedPlaying ||
             dut.ca_child_tested_spi_adc.divider!==savedDivider ||
             dut.ca_child_tested_spi_adc.samples!==savedSamples || !conversionBusy)
            $$fatal(1,"SPI_REPLAY_STOPPED_STATE");
          clockEnabled=1; retire(1);
        end
        if(completed!=1+32*$halfCycles || replies!=completed)
          $$fatal(1,"SPI_REPLAY_STOPPED_COVERAGE");
      """,monitor(halfCycles),referenceHalfPeriodNs=250,serviceHalfPeriodNs=25,
        maximumDelaySubtree=Some("tested_spi_adc"))
    }
  }
}
