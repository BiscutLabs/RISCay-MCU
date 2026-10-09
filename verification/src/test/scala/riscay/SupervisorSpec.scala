// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.profiles._

class BdSupervisorFixture(p: SocParameters) extends riscay.bd.FourPhaseSoc(p,x => new GroundlarkBoard(x,PowerPolicy(enabled=true))) {
  val pauseCommands=IO(Input(Bool())); val pauseReplies=IO(Input(Bool()))
  val pauseOff=IO(Input(Bool())); val pauseShutdown=IO(Input(Bool()))
  val pauseOthers=IO(Input(Bool())); val stopHeartbeat=IO(Input(Bool()))
  val injected=IO(Input(Bool())); val injectedValue=IO(Input(UInt(32.W)))
  val injectedValid=IO(Input(Bool()))
  val publication=BoringUtils.drive(fabric.publish)
  publication(0).valid := injected; publication(0).bits.value := injectedValue
  publication(0).bits.valid := injectedValid; publication(0).bits.calibrated := true.B
  val (commandBridge,replyBridge)=supervisorBridges.get
  commandBridge.in.valid := fabric.boardCommand.valid && !pauseCommands
  fabric.boardCommand.ready := commandBridge.in.ready && !pauseCommands
  val holdReply=pauseReplies || (pauseOff && replyBridge.out.bits.mode === 0.U) ||
    (pauseShutdown && replyBridge.out.bits.mode === 2.U)
  fabric.boardReply.valid := replyBridge.out.valid && !holdReply
  replyBridge.out.ready := fabric.boardReply.ready && !holdReply
  val pending=IO(Output(Bool())); pending := replyBridge.out.valid
  val nativeState=IO(Output(new SupervisorState)); nativeState := replyBridge.out.bits
  val queued=IO(Output(new SupervisorCommand)); queued := fabric.boardCommand.bits
  val visible=IO(Output(new BoardResult)); visible := BoringUtils.bore(fabric.boardResult)
  val active=IO(Output(Bool())); active := BoringUtils.bore(fabric.boardWork)
  fabric.io.controlReply.valid := controlReplyBridge.out.valid && !pauseOthers
  controlReplyBridge.out.ready := fabric.io.controlReply.ready && !pauseOthers
  fabric.telemetryReply.valid := telemetryReplyBridge.out.valid && !pauseOthers
  telemetryReplyBridge.out.ready := fabric.telemetryReply.ready && !pauseOthers
  watchdog.io.heartbeat := Mux(stopHeartbeat,false.B,fabric.io.heartbeat)
}

class ClickSupervisorFixture(p: SocParameters) extends riscay.click.ClickSoc(p,x => new GroundlarkBoard(x,PowerPolicy(enabled=true))) {
  val pauseCommands=IO(Input(Bool())); val pauseReplies=IO(Input(Bool()))
  val pauseOff=IO(Input(Bool())); val pauseShutdown=IO(Input(Bool()))
  val pauseOthers=IO(Input(Bool())); val stopHeartbeat=IO(Input(Bool()))
  val injected=IO(Input(Bool())); val injectedValue=IO(Input(UInt(32.W)))
  val injectedValid=IO(Input(Bool()))
  val publication=BoringUtils.drive(fabric.publish)
  publication(0).valid := injected; publication(0).bits.value := injectedValue
  publication(0).bits.valid := injectedValid; publication(0).bits.calibrated := true.B
  val (commandBridge,replyBridge)=supervisorBridges.get
  commandBridge.in.valid := fabric.boardCommand.valid && !pauseCommands
  fabric.boardCommand.ready := commandBridge.in.ready && !pauseCommands
  val holdReply=pauseReplies || (pauseOff && replyBridge.out.bits.mode === 0.U) ||
    (pauseShutdown && replyBridge.out.bits.mode === 2.U)
  fabric.boardReply.valid := replyBridge.out.valid && !holdReply
  replyBridge.out.ready := fabric.boardReply.ready && !holdReply
  val pending=IO(Output(Bool())); pending := replyBridge.out.valid
  val nativeState=IO(Output(new SupervisorState)); nativeState := replyBridge.out.bits
  val queued=IO(Output(new SupervisorCommand)); queued := fabric.boardCommand.bits
  val visible=IO(Output(new BoardResult)); visible := BoringUtils.bore(fabric.boardResult)
  val active=IO(Output(Bool())); active := BoringUtils.bore(fabric.boardWork)
  fabric.io.controlReply.valid := controlReplyBridge.out.valid && !pauseOthers
  controlReplyBridge.out.ready := fabric.io.controlReply.ready && !pauseOthers
  fabric.telemetryReply.valid := telemetryReplyBridge.out.valid && !pauseOthers
  telemetryReplyBridge.out.ready := fabric.telemetryReply.ready && !pauseOthers
  watchdog.io.heartbeat := Mux(stopHeartbeat,false.B,fabric.io.heartbeat)
}

class SupervisorSpec extends AnyFunSuite {
  private val tasks="""
integer resets=0, savedResets=0;
always @(posedge systemReset) if(!reset) resets=resets+1;
task publish(input [31:0] value,input bit valid);
begin
  @(negedge serviceClock); injected=1; injectedValue=value; injectedValid=valid;
  @(posedge serviceClock); #1; injected=0;
end endtask
reg [31:0] savedSequence;
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(): SocTop = {
      val p=SocParameters(Groundlark.configuration.copy(programBytes=16,workingRamBytes=16),
        serviceHz=1000,staleMs=1000,watchdogCycles=32)
      if(click) new ClickSupervisorFixture(p) else new BdSupervisorFixture(p)
    }
    test(s"$name supervisor ingress: coincident freshness boundaries, retained failures and GPIO history") {
      ClockedSimulation.run(fixture(),name+"-supervisor-history","""
        pauseCommands=1; stopHeartbeat=1; #5000;
        wait(queued_elapsedUpper == 999);
        publish(13000,1);
        if(queued_capture_firstAge !== 1000 || queued_capture_tailAge !== 0)
          $fatal(1,"SUPERVISOR_FIRST_PUBLICATION_AGE %d",queued_capture_firstAge);
        wait(queued_capture_tailAge == 999);
        publish(14000,1);
        if(queued_capture_maximumGap !== 1000 || queued_capture_tailAge !== 0)
          $fatal(1,"SUPERVISOR_LATER_PUBLICATION_GAP %d",queued_capture_maximumGap);
        publish(999,0); publish(13000,1);
        gpioIn=0; #1000; gpioIn=4; #1000;
        if(queued_capture_count !== 4 || !queued_capture_failed || !queued_gpioChanged[2] ||
           queued_capture_minimum !== 13000 || queued_capture_maximum !== 14000 || !active)
          $fatal(1,"SUPERVISOR_INPUT_HISTORY_LOST");
        if(resets < 2) $fatal(1,"NO_REPEATED_APPLICATION_RESETS");
        pauseReplies=1; pauseCommands=0; wait(pending);
        if(nativeState_sample_sequence !== 4 || nativeState_sample_value !== 13000 ||
           !nativeState_sample_valid || nativeState_counts_2 !== 0 || gpioOut[0])
          $fatal(1,"SUPERVISOR_HISTORY_NOT_APPLIED");
        savedSequence=nativeState_sample_sequence; savedResets=resets; #50000;
        if(resets-savedResets < 2) $fatal(1,"NO_REPEATED_RESETS_DURING_HELD_REPLY");
        if(nativeState_sample_sequence !== savedSequence || !pending || !active || gpioOut[0])
          $fatal(1,"SUPERVISOR_HELD_REPLY_RESET");
        pauseReplies=0; #20000;
        if(nativeState_sample_sequence !== 4 || gpioOut[0]) $fatal(1,"SUPERVISOR_BATCH_REPLAY");
      """,tasks,deadlineNs=1000000)
    }
    test(s"$name physical dwell starts after stalled SHUTDOWN and OFF projections") {
      ClockedSimulation.run(fixture(),name+"-supervisor-dwell","""
        stopHeartbeat=1; injected=1; injectedValid=1; injectedValue=13000;
        #3200000; if(!gpioOut[0]) $fatal(1,"SUPERVISOR_DWELL_NO_BOOT");
        pauseShutdown=1; injectedValid=0; #3000; injectedValid=1;
        wait(pending && nativeState_mode == 2); #1200000;
        if(!gpioOut[0] || gpioOut[1]) $fatal(1,"SHUTDOWN_PROJECTED_WHILE_STALLED");
        pauseOff=1; pauseShutdown=0; wait(gpioOut[1]);
        #999000;
        if(!gpioOut[0] || (pending && nativeState_mode == 0)) $fatal(1,"SHORTENED_SHUTDOWN_DWELL");
        wait(pending && nativeState_mode == 0); #3200000;
        if(!gpioOut[0] || !gpioOut[1]) $fatal(1,"OFF_PROJECTED_WHILE_STALLED");
        pauseOff=0; wait(!gpioOut[0]); #2999000;
        if(gpioOut[0]) $fatal(1,"SHORTENED_MINIMUM_OFF_DWELL");
        wait(gpioOut[0]); if(resets < 2) $fatal(1,"DWELL_NOT_TESTED_THROUGH_RESETS");
      """,tasks,deadlineNs=20000000)
    }
    test(s"$name permanent supervision progresses through other consumers' stalls and watchdog resets") {
      ClockedSimulation.run(fixture(),name+"-supervisor-independent","""
        pauseOthers=1; stopHeartbeat=1; injected=1; injectedValid=1; injectedValue=13000;
        #3200000;
        if(!gpioOut[0] || gpioOut[1] || visible_registers_0 !== 1 || resets < 2)
          $fatal(1,"SUPERVISOR_DEPENDS_ON_APPLICATION_OR_TELEMETRY");
        pauseReplies=1; wait(pending); savedSequence=nativeState_sample_sequence; savedResets=resets;
        gpioIn=0; #1000; gpioIn=4; #50000;
        if(resets-savedResets < 2) $fatal(1,"NO_REPEATED_RESETS_DURING_RUN_REPLY");
        if(!gpioOut[0] || nativeState_sample_sequence !== savedSequence || !active)
          $fatal(1,"SUPERVISOR_STALLED_RETENTION");
        pauseReplies=0; #10000;
        if(!gpioOut[0] || visible_registers_3 !== 0) $fatal(1,"QUEUED_GLITCH_QUALIFIED_HALT");
        // A real, continuous current-boot active-low acknowledgment shuts down.
        gpioIn=0; #10000;
        if(gpioOut[0] || visible_registers_4 !== 5) $fatal(1,"SUPERVISOR_HALT_LOST");
        gpioIn=4; #1000000;
        if(gpioOut[0]) $fatal(1,"SUPERVISOR_MINIMUM_OFF_SHORTENED");
      """,tasks,deadlineNs=10000000)
    }
  }
}
