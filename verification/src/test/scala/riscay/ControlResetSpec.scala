// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import java.util.zip.CRC32

class BdControlResetFixture(p: SocParameters) extends MemoryResetFixture(p) {
  val pauseReplies = IO(Input(Bool())); val pauseCommands = IO(Input(Bool()))
  val replyPending = IO(Output(Bool())); val replyKind = IO(Output(UInt(3.W)))
  val framePending = IO(Output(Bool())); framePending := fabric.io.hostFrameAccepted
  val commandLaunch = IO(Output(Bool())); commandLaunch := fabric.io.controlCommand.fire
  fabric.io.controlReply.valid := controlReplyBridge.out.valid && !pauseReplies
  controlReplyBridge.out.ready := fabric.io.controlReply.ready && !pauseReplies
  controlCommandBridge.in.valid := fabric.io.controlCommand.valid && !pauseCommands
  fabric.io.controlCommand.ready := controlCommandBridge.in.ready && !pauseCommands
  replyPending := controlReplyBridge.out.valid; replyKind := controlReplyBridge.out.bits.kind
}
class ClickControlResetFixture(p: SocParameters) extends ClickMemoryResetFixture(p) {
  val pauseReplies = IO(Input(Bool())); val pauseCommands = IO(Input(Bool()))
  val replyPending = IO(Output(Bool())); val replyKind = IO(Output(UInt(3.W)))
  val framePending = IO(Output(Bool())); framePending := fabric.io.hostFrameAccepted
  val commandLaunch = IO(Output(Bool())); commandLaunch := fabric.io.controlCommand.fire
  fabric.io.controlReply.valid := controlReplyBridge.out.valid && !pauseReplies
  controlReplyBridge.out.ready := fabric.io.controlReply.ready && !pauseReplies
  controlCommandBridge.in.valid := fabric.io.controlCommand.valid && !pauseCommands
  fabric.io.controlCommand.ready := controlCommandBridge.in.ready && !pauseCommands
  replyPending := controlReplyBridge.out.valid; replyKind := controlReplyBridge.out.bits.kind
}

class ControlResetSpec extends AnyFunSuite {
  private val config=McuConfiguration(12,32,0,Vector(MeasurementChannel(0,"test",1,0)),
    ApplicationProfile(1,1,"reset",Vector(HostRegister(0,"DATA")),Vector.empty))
  private val p=SocParameters(config,watchdogCycles=10000000)
  private val tasks="""
task issue(input [1:0] op,input [31:0] address,input [31:0] value);
begin
  @(negedge serviceClock); request_valid=1; request_bits_operation=op;
  request_bits_address=address; request_bits_data=value; request_bits_mask=15;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
end endtask
task answer(input [31:0] expected);
begin
  wait(response_valid);
  if(response_bits_error || response_bits_data !== expected)
    $fatal(1,"CONTROL_RESET_REPLY actual=%h expected=%h",response_bits_data,expected);
  @(negedge serviceClock); response_ready=1;
  @(posedge serviceClock); #1; response_ready=0;
end endtask
task write_value(input [31:0] value);
begin issue(2,32'h30000028,value); answer(0); end endtask
task pulse_reset;
begin applicationReset=1; #600; applicationReset=0; #1000; end endtask
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(): SocTop = if(click) new ClickControlResetFixture(p) else new BdControlResetFixture(p)
    test(s"$name: short watchdog reset survives a stalled START reply and requires a new START") {
      val crc=new CRC32; Seq(0x73,0,0,0).foreach(crc.update)
      ClockedSimulation.run(fixture(),name+"-control-start-reset",s"""
        #10000;
        begin_image(4,0,32'h${crc.getValue.toHexString},32'h00010000);
        put_word(0,32'h00000073); command(3); command(4); #5000;
        if(!programmed || !locked || mode !== 2) $$fatal(1,"CONTROL_RESET_IMAGE");
        pauseReplies=1; command(5); wait(replyPending && replyKind==0);
        pulse_reset(); pauseReplies=0; #10000;
        if(!programmed || !locked || mode !== 2) $$fatal(1,"STALE_START_SURVIVED_RESET");
        @(negedge serviceClock); request_valid=1; request_bits_operation=1;
        request_bits_address=32'h30000000; request_bits_data=0; request_bits_mask=15;
        repeat(50) begin @(posedge serviceClock);
          if(request_ready || response_valid) $$fatal(1,"STALE_START_RELEASED_BOOT_WAIT");
        end
        @(negedge serviceClock); request_valid=0;
        command(5); #5000;
        issue(1,32'h30000000,0); answer(32'h10000000);
      """,tasks)
    }
    test(s"$name: application reset cancels HALT waiting for native command acceptance") {
      ClockedSimulation.run(fixture(),name+"-control-halt-reset","""
        #10000; pauseCommands=1;
        issue(3,0,0); #17; pulse_reset(); pauseCommands=0; #10000;
        if(mode !== 0 || response_valid) $fatal(1,"STALE_HALT_AFTER_RESET");
        issue(0,0,0); answer(32'h300000b7);
      """,tasks)
    }
    test(s"$name: queued START frames retain their reset lifetime and require a post-reset command") {
      val crc=new CRC32; Seq(0x73,0,0,0).foreach(crc.update)
      ClockedSimulation.run(fixture(),name+"-control-queued-start",s"""
        #10000;
        begin_image(4,0,32'h${crc.getValue.toHexString},32'h00010000);
        put_word(0,32'h00000073); command(3); #5000;
        pauseCommands=1; command(5); pulse_reset(); pauseCommands=0; #10000;
        if(mode !== 2) $$fatal(1,"PRE_RESET_QUEUED_START_RAN");
        read_words(1,0,5); if(snapshot[0+:32] !== 3) $$fatal(1,"QUEUED_RESET_REJECTION");
        pauseCommands=1; applicationReset=1; #1000; command(5);
        applicationReset=0; #1000; pauseCommands=0; #10000;
        if(mode !== 2) $$fatal(1,"RESET_CAPTURED_START_RAN");
        command(5); #5000;
        if(mode !== 3) $$fatal(1,"POST_RESET_START_REJECTED");
      """,tasks)
    }
    test(s"$name: reset cancels prepared MMIO but retains an accepted producer-staging commit") {
      ClockedSimulation.run(fixture(),name+"-control-mmio-reset","""
        #10000; write_value(32'h11223344); #5000;
        pauseReplies=1;
        @(negedge serviceClock); request_valid=1; request_bits_operation=2;
        request_bits_address=32'h30000028; request_bits_data=32'hdeadbeef; request_bits_mask=15;
        wait(replyPending && replyKind==4);
        if(request_ready) $fatal(1,"PREPARED_WRITE_ACCEPTED_EARLY");
        applicationReset=1; request_valid=0; #600; applicationReset=0; #1000;
        pauseReplies=0; #10000;
        if(response_valid) $fatal(1,"STALE_MMIO_COMPLETION");
        issue(1,32'h30000028,0); answer(32'h11223344);
        issue(2,32'h30000028,32'habcdef01);
        // Acceptance has happened, but the native commit is still backpressured.
        pauseCommands=1; pulse_reset(); pauseCommands=0; #10000;
        issue(1,32'h30000028,0); answer(32'habcdef01);
      """,tasks)
    }
    test(s"$name: a loader command received during a stalled WRITE is rejected instead of deferred") {
      val crc=new CRC32; Seq(0x73,0,0,0).foreach(crc.update)
      ClockedSimulation.run(fixture(),name+"-control-busy-frame",s"""
        #10000; begin_image(4,0,32'h${crc.getValue.toHexString},32'h00010000); #5000;
        pauseReplies=1; put_word(0,32'h00000073); wait(replyPending && replyKind==0);
        command(3); pauseCommands=1; pauseReplies=0;
        // SRAM finishes before either accounting or queued VERIFY may dispatch.
        #10000; pauseCommands=0; #10000;
        read_words(1,0,5);
        if(snapshot[0+:32] !== 3 || programmed) $$fatal(1,"BUSY_VERIFY_WAS_DEFERRED");
        command(3); command(4); #5000;
        if(!programmed || !locked) $$fatal(1,"EXPLICIT_VERIFY_DID_NOT_RECOVER");
      """,tasks)
    }
    test(s"$name: simultaneous loader admission and new host frame retains the busy rejection") {
      val crc=new CRC32; Seq(0x73,0,0,0).foreach(crc.update)
      ClockedSimulation.run(fixture(),name+"-control-same-edge-busy",s"""
        #10000; begin_image(4,0,32'h${crc.getValue.toHexString},32'h00010000); #5000;
        pauseCommands=1; put_word(0,32'h00000073); pauseReplies=1;
        fork
          begin command(3); end
          begin
            wait(framePending); @(negedge serviceClock); pauseCommands=0;
            @(posedge serviceClock); #1; pauseCommands=1;
          end
        join
        if(simultaneous !== 1) $$fatal(1,"BUSY_BOUNDARY_NOT_EXERCISED");
        wait(replyPending && replyKind==0); pauseReplies=0; #10000;
        pauseCommands=0; #10000; read_words(1,0,5);
        if(snapshot[0+:32] !== 3 || programmed) $$fatal(1,"SIMULTANEOUS_BUSY_VERIFY_DEFERRED");
        command(3); #5000; if(!programmed) $$fatal(1,"EXPLICIT_VERIFY_FAILED");
      """,tasks+"""
integer simultaneous=0;
always @(posedge serviceClock) if(!reset && framePending && commandLaunch) simultaneous=simultaneous+1;
""")
    }
  }
}
