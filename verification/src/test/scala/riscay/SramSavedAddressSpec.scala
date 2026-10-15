// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Direct actual-bank fixture; the full SoC SramSpec remains separately required. */
class SramSavedAddressFixture(click: Boolean, bytes: Int) extends FabricFixture(SocParameters(McuConfiguration(
    bytes,bytes,0,Vector.empty,ApplicationProfile(1,1,"sram-saved-address",Vector.empty,Vector.empty)),
    watchdogCycles=64,watchdogHoldCycles=32)) {
  val probeValid=IO(Input(Bool())); val probeReady=IO(Output(Bool()))
  val probeLane=IO(Input(UInt(2.W))); val probeAddress=IO(Input(UInt(32.W)))
  val probeWrite=IO(Input(Bool())); val probeData=IO(Input(UInt(8.W))); val probeEnable=IO(Input(Bool()))
  val answerValid=IO(Output(Bool())); val answerReady=IO(Input(Bool())); val answerData=IO(Output(UInt(8.W)))
  val captured=IO(Output(UInt(42.W))); val capturedTag=IO(Output(UInt(2.W)))
  val stateView=IO(Output(UInt(2.W)))
  private val banks=(bytes+1023)/1024
  val macroAddress=IO(Output(Vec(banks,UInt(10.W)))); val macroData=IO(Output(Vec(banks,UInt(8.W))))
  val macroCen=IO(Output(Vec(banks,Bool()))); val macroGwen=IO(Output(Vec(banks,Bool())))
  // Keep the two concrete implementations separate; no shared controller is added.
  if(click) {
    val probe=withClockAndReset(serviceClock,reset) { Module(new riscay.click.SramBank(bytes)) }
    for(i <- 0 until 4) {
      probe.io.request(i).valid:=probeValid && probeLane===i.U
      probe.io.request(i).bits.address:=probeAddress; probe.io.request(i).bits.write:=probeWrite
      probe.io.request(i).bits.data:=probeData; probe.io.request(i).bits.enable:=probeEnable
      probe.io.response(i).ready:=answerReady && probeLane===i.U
    }
    probeReady:=probe.io.request(probeLane).ready
    answerValid:=probe.io.response(probeLane).valid; answerData:=probe.io.response(probeLane).bits
    captured:=Cat(BoringUtils.bore(probe.saved.address).pad(32),BoringUtils.bore(probe.saved.write),
      BoringUtils.bore(probe.saved.data),BoringUtils.bore(probe.saved.enable))
    capturedTag:=BoringUtils.bore(probe.tag); stateView:=BoringUtils.bore(probe.state)
    for(i <- 0 until banks) {
      macroAddress(i):=BoringUtils.bore(probe.macros(i).io.A); macroData(i):=BoringUtils.bore(probe.macros(i).io.D)
      macroCen(i):=BoringUtils.bore(probe.macros(i).io.CEN); macroGwen(i):=BoringUtils.bore(probe.macros(i).io.GWEN)
    }
  } else {
    val probe=withClockAndReset(serviceClock,reset) { Module(new riscay.bd.SramBank(bytes)) }
    for(i <- 0 until 4) {
      probe.io.request(i).valid:=probeValid && probeLane===i.U
      probe.io.request(i).bits.address:=probeAddress; probe.io.request(i).bits.write:=probeWrite
      probe.io.request(i).bits.data:=probeData; probe.io.request(i).bits.enable:=probeEnable
      probe.io.response(i).ready:=answerReady && probeLane===i.U
    }
    probeReady:=probe.io.request(probeLane).ready
    answerValid:=probe.io.response(probeLane).valid; answerData:=probe.io.response(probeLane).bits
    captured:=Cat(BoringUtils.bore(probe.saved.address).pad(32),BoringUtils.bore(probe.saved.write),
      BoringUtils.bore(probe.saved.data),BoringUtils.bore(probe.saved.enable))
    capturedTag:=BoringUtils.bore(probe.tag); stateView:=BoringUtils.bore(probe.state)
    for(i <- 0 until banks) {
      macroAddress(i):=BoringUtils.bore(probe.macros(i).io.A); macroData(i):=BoringUtils.bore(probe.macros(i).io.D)
      macroCen(i):=BoringUtils.bore(probe.macros(i).io.CEN); macroGwen(i):=BoringUtils.bore(probe.macros(i).io.GWEN)
    }
  }
}

class SramSavedAddressSpec extends AnyFunSuite {
  private def monitors(bytes: Int): String = {
    val banks=(bytes+1023)/1024
    val pins=(0 until banks).map { i => s"""
real changed$i=0;
always @(macroAddress_$i or macroData_$i or macroCen_$i or macroGwen_$i) if(!reset) begin
  if(serviceClock!==0) $$fatal(1,"SAVED_ADDRESS_NONFALLING_LAUNCH_$i");
  if(accessAt>0 && $$realtime-accessAt<5) $$fatal(1,"SAVED_ADDRESS_PIN_HOLD_$i");
  changed$i=$$realtime;
end
always @(posedge serviceClock) if(!reset && !macroCen_$i) begin
  if(!expectedEnable || expectedAddress/1024!=$i || macroAddress_$i!==expectedAddress%1024 ||
      macroData_$i!==expectedData || macroGwen_$i!==!expectedWrite)
    $$fatal(1,"SAVED_ADDRESS_MACRO_EFFECT_$i");
  if($$realtime-changed$i<5) $$fatal(1,"SAVED_ADDRESS_PIN_SETUP_$i");
  accesses=accesses+1; if(!macroGwen_$i) writes=writes+1; accessAt=$$realtime;
end
""" }.mkString
    s"""
integer accesses=0,writes=0,lane,address,bitIndex,phase,negativeLane,unused;
integer beforeAccess,beforeWrites;
reg negativeCampaign=0,negativeEnable=1,negativeWrite=1,expectedEnable,expectedWrite;
reg [31:0] expectedAddress,negativeAddress;
reg [7:0] expectedData,heldAnswer;
reg [41:0] sampledRequest,heldCapture;
reg [1:0] sampledLane,heldState;
real accessAt=0;
always @(posedge serviceClock) if(!reset && !negativeCampaign && probeValid && probeReady) begin
  sampledRequest={probeAddress,probeWrite,probeData,probeEnable}; sampledLane=probeLane;
  #0.001;
  if(captured!==sampledRequest || capturedTag!==sampledLane) $$fatal(1,"SAVED_ADDRESS_FULL_CAPTURE");
end
task issue(input integer selectedLane,input [31:0] offset,input bit wr,input [7:0] data,input bit enabled); begin
  @(negedge serviceClock); probeLane=selectedLane; probeAddress=offset; probeWrite=wr;
  probeData=data; probeEnable=enabled; probeValid=1;
  expectedAddress=offset; expectedData=data; expectedWrite=wr; expectedEnable=enabled;
  beforeAccess=accesses; beforeWrites=writes;
  @(posedge serviceClock); while(!probeReady) @(posedge serviceClock);
  #1; probeValid=0; probeAddress=~offset; probeData=~data;
end endtask
task answer(input [7:0] value); begin
  wait(answerValid); #1; heldAnswer=answerData;
  if(answerData!==value || accesses-beforeAccess!==expectedEnable ||
      writes-beforeWrites!==(expectedEnable && expectedWrite)) $$fatal(1,"SAVED_ADDRESS_RESULT_OR_EFFECT_COUNT");
  if(expectedEnable && $$realtime-accessAt<50) $$fatal(1,"SAVED_ADDRESS_EARLY_Q_CAPTURE");
  repeat(4) begin @(negedge serviceClock);
    if(!answerValid || answerData!==heldAnswer || probeReady) $$fatal(1,"SAVED_ADDRESS_REPLY_HOLD");
  end
  answerReady=1; @(posedge serviceClock); #1; answerReady=0;
end endtask
$pins
"""
  }

  for(click <- Seq(false,true); bytes <- Seq(4,12,1024,1028,2048,3072)) {
    val name=if(click) "click" else "bd"
    test(s"$name saved SRAM address: $bytes-byte full-width capture, every lane, physical pins and retained storage") {
      ClockedSimulation.run(new SramSavedAddressFixture(click,bytes),s"$name-sram-saved-$bytes",s"""
        // This branch is reused by the external exact-fatal controls against
        // this identical compiled binary; normal positive tests never enter it.
        if($$value$$plusargs("invalidAddress=%h",negativeAddress)) begin
          negativeCampaign=1; unused=$$value$$plusargs("invalidLane=%d",negativeLane);
          unused=$$value$$plusargs("invalidEnable=%d",negativeEnable);
          unused=$$value$$plusargs("invalidWrite=%d",negativeWrite);
          issue(negativeLane,negativeAddress,negativeWrite,8'hac,negativeEnable);
          #1000; $$fatal(1,"SAVED_ADDRESS_INVALID_WAS_ACCEPTED");
        end
        for(lane=0;lane<4;lane=lane+1) begin
          issue(lane,0,1,8'ha0+lane,1); answer(0);
          issue(lane,0,0,0,1); answer(8'ha0+lane);
          issue(lane,$bytes-1,1,8'hb0+lane,1); answer(0);
          issue(lane,$bytes-1,0,0,1); answer(8'hb0+lane);
          issue(lane,$bytes-1,1,8'hcc,0); answer(0);
          issue(lane,$bytes-1,0,0,1); answer(8'hb0+lane);
          issue(lane,$bytes-1,0,0,0); answer(0);
          for(bitIndex=0;bitIndex<31;bitIndex=bitIndex+1) if((1<<bitIndex)<$bytes) begin
            address=1<<bitIndex;
            issue(lane,address,1,8'h31+bitIndex+lane,1); answer(0);
            issue(lane,address,0,0,1); answer(8'h31+bitIndex+lane);
          end
        end
        // Stop between acceptance, falling launch, macro access and Q capture.
        // Original full-SoC mask/watchdog/POR tests remain unchanged.
        for(phase=0;phase<4;phase=phase+1) begin
          issue(phase,$bytes-1,1,8'hd0+phase,1);
          case (phase)
            0: begin end // issue returns at acceptance + 1 ns, before falling launch
            1: begin @(negedge serviceClock); #1; end
            2: begin @(posedge serviceClock); #1; end
            3: begin repeat(2) @(posedge serviceClock); #1; end
          endcase
          clockEnabled=0;
          if(stateView !== ((phase<2) ? 1 : ((phase==2) ? 2 : 3)))
            $$fatal(1,"SAVED_ADDRESS_STOP_PHASE");
          if(accesses-beforeAccess !== ((phase<2) ? 0 : 1))
            $$fatal(1,"SAVED_ADDRESS_STOP_EFFECTS");
          ${(0 until ((bytes+1023)/1024)).map(i =>
            s"if(macroCen_$i !== !((phase==1 || phase==2) && $i==${(bytes-1)/1024})) $$fatal(1,\"SAVED_ADDRESS_STOP_CEN_$i\");").mkString("\n")}
          heldCapture=captured; heldState=stateView; address=accesses;
          #1000;
          if(captured!==heldCapture || stateView!==heldState || accesses!=address)
            $$fatal(1,"SAVED_ADDRESS_STOPPED_CLOCK");
          clockEnabled=1; answer(0);
          issue(phase,$bytes-1,0,0,1); answer(8'hd0+phase);
        end
        // Controller POR must not clear stored bytes or replay an idle access.
        beforeWrites=writes; reset=1; #2000; reset=0; #3000;
        if(writes!=beforeWrites || answerValid) $$fatal(1,"SAVED_ADDRESS_POR_REPLAY");
        issue(0,$bytes-1,0,0,1); answer(8'hd3);
      """,monitors(bytes),serviceHalfPeriodNs=25,referenceHalfPeriodNs=250)
    }
  }
}
