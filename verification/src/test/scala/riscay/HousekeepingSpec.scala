// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdHousekeepingFixture(p: SocParameters) extends FabricFixture(p) {
  val pauseHouseCommand=IO(Input(Bool())); val pauseHouseReply=IO(Input(Bool()))
  val pauseTelemetry=IO(Input(Bool())); val stopHeartbeat=IO(Input(Bool()))
  val manualTime=IO(Input(Bool())); val injectTime=IO(Input(Bool())); val injectTarget=IO(Input(UInt(32.W)))
  val injectElapsed=IO(Input(UInt(32.W))); val injectUpper=IO(Input(UInt(32.W)))
  val injectSample=IO(Input(Bool())); val sampleValue=IO(Input(UInt(32.W)))
  housekeepingCommandBridge.in.valid:=fabric.housekeepingCommand.valid && !pauseHouseCommand
  fabric.housekeepingCommand.ready:=housekeepingCommandBridge.in.ready && !pauseHouseCommand
  fabric.housekeepingReply.valid:=housekeepingReplyBridge.out.valid && !pauseHouseReply
  housekeepingReplyBridge.out.ready:=fabric.housekeepingReply.ready && !pauseHouseReply
  fabric.telemetryReply.valid:=telemetryReplyBridge.out.valid && !pauseTelemetry
  telemetryReplyBridge.out.ready:=fabric.telemetryReply.ready && !pauseTelemetry
  when(manualTime) {
    fabric.io.elapsedScaling.valid:=injectTime; fabric.io.elapsedScaling.single:=injectTime
    fabric.io.elapsedScaling.publicationTarget:=injectTarget; fabric.io.elapsedScaling.busy:=false.B
    fabric.io.elapsedScaling.elapsed(0):=Mux(injectTime,injectElapsed,0.U)
    fabric.io.elapsedScaling.elapsed(1):=Mux(injectTime,injectElapsed,0.U)
    fabric.io.elapsedScaling.elapsed(2):=Mux(injectTime,injectUpper,0.U)
    fabric.io.timeGray:=injectTarget ^ (injectTarget >> 1)
  }
  val publications=BoringUtils.drive(fabric.publish)
  publications(0).valid:=injectSample; publications(0).bits.value:=sampleValue
  publications(0).bits.valid:=true.B; publications(0).bits.calibrated:=true.B
  val housePending=IO(Output(Bool())); housePending:=housekeepingReplyBridge.out.valid
  val houseAccepted=IO(Output(Bool())); houseAccepted:=fabric.housekeepingCommand.fire
  val houseCommand=IO(Output(new HousekeepingCommand)); houseCommand:=fabric.housekeepingCommand.bits
  val houseState=IO(Output(new HousekeepingState)); houseState:=BoringUtils.bore(fabric.housekeepingState)
  val visibleLease=IO(Output(UInt(32.W))); visibleLease:=BoringUtils.bore(fabric.sleepRemaining)
  val visibleMask=IO(Output(UInt(32.W))); visibleMask:=BoringUtils.bore(fabric.wakeMask)
  val boardTime=IO(Output(UInt(32.W))); boardTime:=BoringUtils.bore(fabric.boardNow)
  val consumed=IO(Output(UInt(32.W))); consumed:=fabric.io.consumedGray
  val idle=IO(Output(Bool())); idle:= !BoringUtils.bore(fabric.housekeepingWork) &&
    !BoringUtils.bore(fabric.telemetryWork) && !BoringUtils.bore(fabric.controlBusy)
  val sleepEligible=IO(Output(Bool())); sleepEligible:=fabric.io.canSleep
  val resetObserved=IO(Output(Bool())); resetObserved:=cpuResetActive
  watchdog.io.heartbeat:=Mux(stopHeartbeat,false.B,fabric.io.heartbeat)
}

class HousekeepingSpec extends AnyFunSuite {
  private val config=McuConfiguration(16,16,1,Vector(MeasurementChannel(0,"sample",1,0)),
    ApplicationProfile(1,1,"housekeeping",Vector.empty,Vector.empty))
  private val tasks="""
integer commits=0,replies=0,resetEdges=0,n,savedCommits,savedReplies;
reg [31:0] savedNow;
always @(posedge serviceClock) if(!systemReset) begin
  if(commit_valid) commits=commits+1;
  if(response_valid && response_ready) replies=replies+1;
end
always @(posedge watchdogClock) if(systemReset && !reset) resetEdges=resetEdges+1;
task issue(input [1:0] op,input [31:0] address,input [31:0] value); begin
  @(negedge serviceClock); request_valid=1; request_bits_operation=op;
  request_bits_address=address; request_bits_data=value; request_bits_mask=15;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
end endtask
task answer; begin
  wait(response_valid); if(response_bits_error) $fatal(1,"HOUSEKEEPING_BUS_ERROR");
  @(negedge serviceClock); response_ready=1; @(posedge serviceClock); #1; response_ready=0;
end endtask
task write_bus(input [31:0] address,input [31:0] value); begin
  issue(2,address,value); answer;
end endtask
task advance(input [31:0] target,input [31:0] amount,input [31:0] upper); begin
  @(negedge serviceClock); injectTime=1; injectTarget=target; injectElapsed=amount; injectUpper=upper;
  @(posedge serviceClock); #1; injectTime=0;
end endtask
task publish; begin
  @(negedge serviceClock); injectSample=1; sampleValue=12345;
  @(posedge serviceClock); #1; injectSample=0;
end endtask
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(p: SocParameters): SocTop = if(click) new ClickHousekeepingFixture(p) else new BdHousekeepingFixture(p)
    def parameters = SocParameters(config,staleMs=100,watchdogCycles=64,watchdogHoldCycles=32,
      lowPower=Some(LowPowerParameters()))
    test(s"$name housekeeping: deadline commit joins unequal consumer completions exactly once") {
      ClockedSimulation.run(fixture(parameters),name+"-housekeeping-completions","""
        manualTime=1; referenceEnabled=0; wait(idle);
        for(n=0;n<2;n=n+1) begin
          savedCommits=commits; savedReplies=replies;
          @(negedge serviceClock); pauseHouseReply=(n==0); pauseTelemetry=(n==1);
          issue(2,32'h30000008,100+n);
          #5000;
          if(response_valid || commits != savedCommits+1 || replies != savedReplies)
            $fatal(1,"HOUSEKEEPING_EARLY_OR_DUPLICATE_COMPLETION");
          pauseHouseReply=0; pauseTelemetry=0; answer;
          #5000;
          if(response_valid || commits != savedCommits+1 || replies != savedReplies+1)
            $fatal(1,"HOUSEKEEPING_REPLAYED_COMPLETION");
          wait(idle);
        end
      """,tasks,referenceHalfPeriodNs=10000000,deadlineNs=200000)
    }
    test(s"$name housekeeping: stalled timer publication retains Gray work while independent observation ingress ages samples") {
      ClockedSimulation.run(fixture(parameters),name+"-housekeeping-publication","""
        manualTime=1; referenceEnabled=0; wait(idle); publish; wait(idle);
        pauseHouseCommand=1; advance(1,120,120); #5000;
        if(consumed || timeNow || boardTime != 120 || sleepEligible)
          $fatal(1,"HOUSEKEEPING_EARLY_TIME_OR_LOST_OBSERVATION");
        read_words(2,0,0);
        if(snapshot[64+:32] < 120 || snapshot[32] || !snapshot[33])
          $fatal(1,"HOUSEKEEPING_STALL_HID_SAMPLE_AGE");
        pauseHouseReply=1; pauseHouseCommand=0; wait(housePending);
        advance(2,5,7); #2000;
        if(consumed || timeNow || boardTime != 125 || sleepEligible)
          $fatal(1,"HOUSEKEEPING_PENDING_PUBLICATION_ACKNOWLEDGED");
        pauseHouseReply=0; wait(consumed==3); wait(idle);
        if(timeNow != 125 || boardTime != 125) $fatal(1,"HOUSEKEEPING_ELAPSED_LOST_OR_REPLAYED");
        read_words(2,0,0);
        if(snapshot[64+:32] != 127) $fatal(1,"HOUSEKEEPING_AGE_DOUBLE_COUNTED");
      """,tasks,referenceHalfPeriodNs=10000000,deadlineNs=3000000)
    }
    test(s"$name housekeeping: continuous legacy ticks permit bounded CPU progress") {
      ClockedSimulation.run(fixture(SocParameters(config,serviceHz=1000,watchdogCycles=1000000)),
        name+"-housekeeping-continuous","""
        referenceEnabled=0;
        for(n=0;n<8;n=n+1) begin
          write_bus(32'h30000038,n & 3);
          issue(1,32'h30000004,0); wait(response_valid); savedNow=response_bits_data; answer;
          if(savedNow==0) $fatal(1,"HOUSEKEEPING_CONTINUOUS_TIME_STOPPED");
        end
        if(commits != 16 || replies != 16) $fatal(1,"HOUSEKEEPING_CONTINUOUS_CPU_STARVED");
      """,tasks,referenceHalfPeriodNs=10000000,deadlineNs=200000)
    }
    test(s"$name housekeeping: queued interval wrap expires leases without losing upper-age history") {
      ClockedSimulation.run(fixture(parameters),name+"-housekeeping-wrap","""
        manualTime=1; referenceEnabled=0; wait(idle); publish; wait(idle);
        write_bus(32'h3000003c,20); write_bus(32'h30000008,20); wait(idle); pauseHouseCommand=1;
        advance(1,32'hffffffff,32'hffffffff); advance(2,1,1); #1000;
        if(!houseCommand_elapsedOverflow || houseCommand_elapsed_0 ||
          houseCommand_elapsed_2 !== 32'hffffffff) $fatal(1,"HOUSEKEEPING_QUEUE_WRAP");
        pauseHouseCommand=0; wait(consumed==3); wait(idle);
        if(timeNow || visibleLease) $fatal(1,"HOUSEKEEPING_WRAP_POLICY");
        issue(1,32'h3000000c,0); wait(response_valid);
        if(!response_bits_data[4] || !response_bits_data[1]) $fatal(1,"HOUSEKEEPING_WRAP_TIMER_EVENTS"); answer;
        read_words(2,0,0);
        if(snapshot[64+:32] !== 32'hffffffff || snapshot[32]) $fatal(1,"HOUSEKEEPING_WRAP_AGE");
      """,tasks,referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
    test(s"$name housekeeping: host period-pending status includes dispatched unpublished updates") {
      ClockedSimulation.run(fixture(parameters.copy(adc=Some(AdcParameters(halfPeriodCycles=2,intervalCycles=100000)))),
        name+"-housekeeping-period-status","""
        manualTime=1; referenceEnabled=0; wait(idle); #10000;
        @(negedge serviceClock); pauseHouseReply=1;
        issue(2,32'h30000040,20); wait(housePending); #1000;
        if(response_valid) $fatal(1,"HOUSEKEEPING_PERIOD_EARLY_REPLY");
        read_words(3,0,0);
        if(!snapshot[227] || snapshot[64+:32] != 10) $fatal(1,"HOUSEKEEPING_DISPATCHED_PERIOD_HIDDEN");
        @(negedge serviceClock); pauseHouseReply=0; answer; wait(idle);
        read_words(3,0,0);
        if(!snapshot[227]) $fatal(1,"HOUSEKEEPING_PENDING_PERIOD_HIDDEN");
      """,tasks,referenceHalfPeriodNs=10000000,deadlineNs=3000000)
    }
    test(s"$name housekeeping: whole watchdog reset suppresses unpublished application state and CPU reply") {
      ClockedSimulation.run(fixture(parameters),name+"-housekeeping-reset","""
        manualTime=1; referenceEnabled=0; wait(idle);
        write_bus(32'h30000038,4); wait(idle);
        @(negedge serviceClock); pauseHouseReply=1; issue(2,32'h3000003c,77); wait(housePending);
        stopHeartbeat=1; referenceEnabled=1; wait(systemReset); #1;
        if(visibleLease || visibleMask != 15 || response_valid) $fatal(1,"HOUSEKEEPING_RESET_PROJECTION");
        wait(!systemReset); referenceEnabled=0; #1000;
        if(resetEdges < 32) $fatal(1,"HOUSEKEEPING_TRUNCATED_WATCHDOG");
        @(negedge serviceClock); pauseHouseReply=0; stopHeartbeat=0; wait(idle); #1000;
        if(visibleLease || visibleMask != 15 || response_valid || houseState_lease)
          $fatal(1,"HOUSEKEEPING_STALE_APPLICATION_REPLY");
        // Prove CPU progress after recovery before publishing another retained
        // elapsed interval through this fixture's synthetic time ingress.
        issue(1,32'h30000004,0); answer;
        advance(1,10,10); wait(consumed==1); wait(idle);
        if(timeNow != 10) $fatal(1,"HOUSEKEEPING_PERSISTENT_TIME_LOST");
      """,tasks,referenceHalfPeriodNs=1000,deadlineNs=500000)
    }
  }
}
class ClickHousekeepingFixture(p: SocParameters) extends ClickFabricFixture(p) {
  val pauseHouseCommand=IO(Input(Bool())); val pauseHouseReply=IO(Input(Bool()))
  val pauseTelemetry=IO(Input(Bool())); val stopHeartbeat=IO(Input(Bool()))
  val manualTime=IO(Input(Bool())); val injectTime=IO(Input(Bool())); val injectTarget=IO(Input(UInt(32.W)))
  val injectElapsed=IO(Input(UInt(32.W))); val injectUpper=IO(Input(UInt(32.W)))
  val injectSample=IO(Input(Bool())); val sampleValue=IO(Input(UInt(32.W)))
  housekeepingCommandBridge.in.valid:=fabric.housekeepingCommand.valid && !pauseHouseCommand
  fabric.housekeepingCommand.ready:=housekeepingCommandBridge.in.ready && !pauseHouseCommand
  fabric.housekeepingReply.valid:=housekeepingReplyBridge.out.valid && !pauseHouseReply
  housekeepingReplyBridge.out.ready:=fabric.housekeepingReply.ready && !pauseHouseReply
  fabric.telemetryReply.valid:=telemetryReplyBridge.out.valid && !pauseTelemetry
  telemetryReplyBridge.out.ready:=fabric.telemetryReply.ready && !pauseTelemetry
  when(manualTime) {
    fabric.io.elapsedScaling.valid:=injectTime; fabric.io.elapsedScaling.single:=injectTime
    fabric.io.elapsedScaling.publicationTarget:=injectTarget; fabric.io.elapsedScaling.busy:=false.B
    fabric.io.elapsedScaling.elapsed(0):=Mux(injectTime,injectElapsed,0.U)
    fabric.io.elapsedScaling.elapsed(1):=Mux(injectTime,injectElapsed,0.U)
    fabric.io.elapsedScaling.elapsed(2):=Mux(injectTime,injectUpper,0.U)
    fabric.io.timeGray:=injectTarget ^ (injectTarget >> 1)
  }
  val publications=BoringUtils.drive(fabric.publish)
  publications(0).valid:=injectSample; publications(0).bits.value:=sampleValue
  publications(0).bits.valid:=true.B; publications(0).bits.calibrated:=true.B
  val housePending=IO(Output(Bool())); housePending:=housekeepingReplyBridge.out.valid
  val houseAccepted=IO(Output(Bool())); houseAccepted:=fabric.housekeepingCommand.fire
  val houseCommand=IO(Output(new HousekeepingCommand)); houseCommand:=fabric.housekeepingCommand.bits
  val houseState=IO(Output(new HousekeepingState)); houseState:=BoringUtils.bore(fabric.housekeepingState)
  val visibleLease=IO(Output(UInt(32.W))); visibleLease:=BoringUtils.bore(fabric.sleepRemaining)
  val visibleMask=IO(Output(UInt(32.W))); visibleMask:=BoringUtils.bore(fabric.wakeMask)
  val boardTime=IO(Output(UInt(32.W))); boardTime:=BoringUtils.bore(fabric.boardNow)
  val consumed=IO(Output(UInt(32.W))); consumed:=fabric.io.consumedGray
  val idle=IO(Output(Bool())); idle:= !BoringUtils.bore(fabric.housekeepingWork) &&
    !BoringUtils.bore(fabric.telemetryWork) && !BoringUtils.bore(fabric.controlBusy)
  val sleepEligible=IO(Output(Bool())); sleepEligible:=fabric.io.canSleep
  val resetObserved=IO(Output(Bool())); resetObserved:=cpuResetActive
  watchdog.io.heartbeat:=Mux(stopHeartbeat,false.B,fabric.io.heartbeat)
}
