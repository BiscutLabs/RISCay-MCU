// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import chiselasync.core.ResetDomain
import chiselasync.metadata.{DelayBounds,ModelTime}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.bd._
import riscay.soc._

class AppRegisterIntegrationFixture(p: SocParameters) extends FabricFixture(p) {
  val resetApplication=IO(Input(Bool()))
  applicationResetRequest:=reset.asBool || watchdog.io.expired || resetApplication
  val cancel=IO(Output(Bool()));cancel:=applicationCancel
  val nativeReset=IO(Output(Bool()));nativeReset:=nativeApplicationReset
  val snapshotCaptured=IO(Output(Bool()));snapshotCaptured:=fabric.io.i2c.readStart
  val replyCaptured=IO(Output(Bool()));replyCaptured:=telemetryReplyBridge.out.fire
  val bankCommitted=IO(Output(Bool()));bankCommitted:=telemetry.reply.ack
  val holdTelemetry=IO(Input(Bool()))
  telemetryReplyBridge.out.ready:=fabric.telemetryReply.ready && !holdTelemetry
  fabric.telemetryReply.valid:=telemetryReplyBridge.out.valid && !holdTelemetry
  val replyWaiting=IO(Output(Bool()));replyWaiting:=telemetryReplyBridge.out.valid && telemetryReplyBridge.out.bits.kind === TelemetryKind.Commit.U
  val recoveryBlocked=IO(Output(Bool()));recoveryBlocked:=fabric.io.telemetrySource.recoveryDebt || fabric.io.telemetrySource.returnFence
  val observedPending=IO(Output(UInt(6.W)));observedPending:=BoringUtils.bore(fabric.pendingView)
  val replyDraining=IO(Output(Bool()));replyDraining:=fabric.io.telemetryDraining
  val observeReplyWaiting=IO(Output(Bool()));observeReplyWaiting:=telemetryReplyBridge.out.valid &&
    telemetryReplyBridge.out.bits.kind === TelemetryKind.Observe.U
}

class AppRegistersSpec extends AnyFunSuite {
  private val config=McuConfiguration(256,256,7,Vector.empty,
    ApplicationProfile(1,1,"native-view",Vector(HostRegister(0,"FIRST"),HostRegister(17,"MIDDLE"),
      HostRegister(63,"LAST")),Vector.empty))
  private def fresh = { val root=Paths.get("build/telemetry-view-tests");Files.createDirectories(root);Files.createTempDirectory(root,"native") }
  private def command(kind: Int,offset: Int=0,value: Long=0,index: Int=0): String=s"""
    command_bits_kind=$kind;command_bits_offset=$offset;command_bits_data=32'h${value.toHexString};command_bits_appIndex=$index;
    #17000000;
    fork
      begin command_req=1;wait(command_ack);#17000000;command_req=0;wait(!command_ack);end
      begin wait(reply_req);#87000000;reply_ack=1;wait(!reply_req);#17000000;reply_ack=0;end
    join
    #200000000;
  """
  for(retain <- Seq(false,true)) {
    test(s"BD retained Telemetry bank: closed pins, sparse words, ordered recovery and POR retention=$retain") {
      AsyncTest.run(new FourPhaseTelemetry(SocParameters(config,spiBoot=true,retainGpioOnWatchdog=retain),
        Vector(0,17,63),new ResetDomain("root")),Seq(1L,2L,3L,7L,19L),fresh,
        routingCells=DelayBounds(ModelTime.ps(1000),ModelTime.ps(5000),ModelTime.ps(1000))) { _ =>
        val writes=Seq(0,17,63).zipWithIndex.map{case(w,i)=>command(1,52,0x12345678L+i,w)}.mkString
        s"""
        $writes
        if(view_application_0!==32'h12345678 || view_application_1!==32'h12345679 || view_application_2!==32'h1234567a)
          $$fatal(1,"NATIVE_WORD_BANK");
        ${command(1,52,0xffffffffL,2)}
        if(view_application_1!==32'h12345679) $$fatal(1,"UNDECLARED_WORD_EFFECT");
        ${command(1,24,127)} ${command(1,28,127)}
        begin : pins
          reg [13:0] previous,changed;reg done;
          previous={view_enable,view_output};changed=0;done=0;
          fork
            begin while(!done) begin @({view_enable,view_output});if(!done) begin
              if((changed & (previous ^ {view_enable,view_output}))!=0) $$fatal(1,"PIN_REPEATED_TRANSITION");
              changed=changed | (previous ^ {view_enable,view_output});previous={view_enable,view_output};
            end end end
            begin ${command(1,24,42)} ${command(1,28,85)} done=1;end
          join_any
          disable pins;
        end
        if(view_output!==42 || view_enable!==85) $$fatal(1,"PIN_READBACK");
        ${command(2)}
        if(view_application_0!==0 || view_application_1!==0 || view_application_2!==0 ||
          view_output!==${if(retain) 2 else 0} || view_enable!==${if(retain) 69 else 0}) $$fatal(1,"NATIVE_RESET_VIEW");
        reset=1;command_req=0;reply_ack=0;#1000000000;reset=0;#1000000000;
        if(view_output!==0 || view_enable!==0 || view_application_0!==0) $$fatal(1,"NATIVE_POR_VIEW");
        """
      }
    }
  }
  private val tasks="""
    task access(input integer wr,input integer off,input [31:0] data,input [31:0] expected,input integer fault,input integer mask);
    begin
      @(negedge serviceClock);request_bits_operation=wr ? 2:1;request_bits_address=32'h30000000+off;
      request_bits_data=data;request_bits_mask=mask;request_valid=1;
      @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);#1;request_valid=0;
      wait(response_valid);
      if(response_bits_error!==fault || response_bits_data!==expected) $fatal(1,"VIEW_MMIO_ABI off=%d data=%h fault=%b",off,response_bits_data,response_bits_error);
      @(negedge serviceClock);response_ready=1;@(posedge serviceClock);#1;response_ready=0;
    end endtask
  """
  for(retain <- Seq(false,true)) {
    test(s"BD Telemetry view MMIO and host snapshots preserve sparse ABI and recovery retention=$retain") {
      val writes=Seq(0,17,63).map(w=>s"access(1,48,$w,0,0,15);access(1,52,32'h12345678+$w,0,0,15);access(0,52,0,32'h12345678+$w,0,15);").mkString
      val masks=(0 until 15).map(m=>s"access(1,52,32'hffffffff,0,1,$m);").mkString
      ClockedSimulation.run(new AppRegisterIntegrationFixture(SocParameters(config,watchdogCycles=1000000,
        spiBoot=true,retainGpioOnWatchdog=retain)),"telemetry-view-abi",s"""
        wait(!cancel && !recoveryBlocked);#1000;
        $writes $masks
        access(1,48,2,0,1,15);access(0,48,0,63,0,15);access(0,52,0,32'h123456b7,0,15);
        access(1,24,127,0,0,15);access(1,28,127,0,0,15);
        access(0,24,0,127,0,15);access(0,28,0,127,0,15);
        read_words(128,0,17);if(snapshot[31:0]!==32'h12345689) $$fatal(1,"VIEW_HOST_WORD");
        read_words(128,0,2);if(snapshot[31:0]!==32'hffffffff || supported[0]!==0) $$fatal(1,"VIEW_HOST_ABSENT");
        repeat(3) begin
          resetApplication=1;wait(cancel);#1000;monitorSpiRelease=1;
          if(gpioOut!==${if(retain) 71 else 0} || gpioOe!==${if(retain) 71 else 0}) $$fatal(1,"VIEW_RESET_ISOLATION");
          resetApplication=0;wait(!cancel && !recoveryBlocked);#1000;
          access(0,48,0,0,0,15);access(0,52,0,0,0,15);
          if(gpioOut!==${if(retain) 71 else 0} || gpioOe!==${if(retain) 71 else 0}) $$fatal(1,"VIEW_RESET_RELEASE");
        end
        reset=1;#1000;reset=0;wait(!cancel && !recoveryBlocked);#1000;
        if(gpioOut!==0 || gpioOe!==0) $$fatal(1,"VIEW_POR");
      """,tasks+"""
        reg monitorSpiRelease=0;
        always @(gpioOut or gpioOe) if(monitorSpiRelease && ((gpioOut & 32'h38)!=0 || (gpioOe & 32'h38)!=0))
          $fatal(1,"SPI_PINS_REASSERTED_DURING_RECOVERY");
      """)
    }
  }
  test("BD revoked Telemetry completion cannot alter retained pins during recovery") {
    ClockedSimulation.run(new AppRegisterIntegrationFixture(SocParameters(config,watchdogCycles=1000000,
      spiBoot=true,retainGpioOnWatchdog=true)),"telemetry-view-revoked","""
      wait(!cancel && !recoveryBlocked);#1000;
      access(1,24,1,0,0,15);access(1,28,1,0,0,15);#5000;holdTelemetry=1;
      @(negedge serviceClock);request_bits_operation=2;request_bits_address=32'h30000018;
      request_bits_data=0;request_bits_mask=15;request_valid=1;
      @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);#1;request_valid=0;
      wait(replyWaiting);resetApplication=1;wait(cancel);#500;holdTelemetry=0;#2000;
      if(gpioOut!==1 || gpioOe!==1) $fatal(1,"REVOKED_REPLY_CHANGED_RETAINED_PIN");
      resetApplication=0;wait(!cancel && !recoveryBlocked);#2000;
      if(gpioOut!==1 || gpioOe!==1) $fatal(1,"REVOKED_REPLY_SURVIVED_RECOVERY");
    """,tasks)
  }

  test("BD fresh recovery events stay visible while the publication return is held") {
    ClockedSimulation.run(new BdRecoveryOwnershipFixture(SocParameters(config,watchdogCycles=1000000)),
      "telemetry-view-recovery-event","""
      #100000;
      if(qualifiedReset || nativeDebt!==0 || returnFence!==0)
        $fatal(1,"PENDING_RECOVERY_INITIAL_STATE");
      // Hold the recovery command until a post-reset GPIO event is queued,
      // and keep its eventual return open after the reply is accepted.
      @(negedge serviceClock);holdCommand=1;holdDrain=1;applicationReset=1;
      #100;applicationReset=0;
      wait(!qualifiedReset);#1000;
      @(negedge serviceClock);gpioIn=1;#1000;
      if(!visibleEvents[2] || projectedEvents[2])
        $fatal(1,"PENDING_RECOVERY_EVENT_NOT_QUEUED");
      @(negedge serviceClock);holdCommand=0;
      wait(freshRecoveryReply[0]);
      @(posedge serviceClock);#10;
      // The qualified bank capture has completed, but debt is deliberately
      // still high. Masking pending with that debt would hide the event here.
      repeat(8) begin
        @(negedge serviceClock);
        if(!nativeDebt[0] || !returnFence[0] || !projectedEvents[2] || !visibleEvents[2])
          $fatal(1,"PENDING_RECOVERY_PUBLICATION_DISAPPEARED");
      end
      holdDrain=0;
      wait(!returnFence[0]);#1000;
      if(!projectedEvents[2] || !visibleEvents[2])
        $fatal(1,"PENDING_RECOVERY_EVENT_LOST_AFTER_RETURN");
      """,deadlineNs=2000000)
  }

  test("BD pending event stays continuously asserted through an Observe reply and its return") {
    ClockedSimulation.run(new AppRegisterIntegrationFixture(SocParameters(config,watchdogCycles=1000000)),
      "telemetry-view-event-handoff","""
      referenceEnabled=0;
      wait(!cancel && !recoveryBlocked);#5000;
      access(1,12,63,0,0,15);access(0,12,0,0,0,15);#5000;
      @(negedge serviceClock);holdTelemetry=1;gpioIn=5;
      wait(observedPending[2]);monitorPending=1;
      wait(observeReplyWaiting);
      // A CPU read is already waiting when the reply is released. It must
      // remain excluded until the native bank and the full return settle.
      fork
        begin access(0,12,0,4,0,15);end
        begin wait(request_valid);repeat(2) @(negedge serviceClock);holdTelemetry=0;end
      join
      if(drainingReadEdges==0 || !observedPending[2])
        $fatal(1,"PENDING_HANDOFF_NOT_EXERCISED");
      repeat(4) @(negedge serviceClock);
      monitorPending=0;
      access(1,12,4,0,0,15);access(0,12,0,0,0,15);
      if(observedPending[2]) $fatal(1,"PENDING_HANDOFF_CLEAR_FAILED");
      """,tasks+"""
      reg monitorPending=0;
      integer drainingReadEdges=0;
      always @(observedPending) if(monitorPending && observedPending[2]!==1'b1)
        $fatal(1,"PENDING_HANDOFF_DIPPED");
      always @(posedge serviceClock) if(monitorPending && request_valid && replyDraining) begin
        drainingReadEdges=drainingReadEdges+1;
        if(request_ready) $fatal(1,"PENDING_READ_ADMITTED_DURING_RETURN");
      end
      """)
  }

  test("BD serial snapshot and qualified Telemetry commit on the same edge see the complete old bank") {
    val serial="""
      integer simultaneous=0;
      always @(posedge serviceClock) if(!reset && snapshotCaptured && replyCaptured) simultaneous=simultaneous+1;
      reg [255:0] selectedSnapshot;reg [31:0] selectedSupported;
      task read_selected;
        integer b;reg [7:0] value;
        begin start_bus();write_byte(8'h6b);
          for(b=0;b<36;b=b+1) begin read_byte(value,b==35);
            if(b<32) selectedSnapshot[8*b+:8]=value;else selectedSupported[8*(b-32)+:8]=value;
          end stop_bus();
        end
      endtask
    """
    ClockedSimulation.run(new AppRegisterIntegrationFixture(SocParameters(config,watchdogCycles=1000000)),
      "telemetry-view-simultaneous","""
      wait(!cancel && !recoveryBlocked);#1000;
      access(1,48,0,0,0,15);access(1,52,32'ha5c35a3c,0,0,15);
      read_words(128,0,0);if(snapshot[31:0]!==32'ha5c35a3c) $fatal(1,"SNAPSHOT_RACE_SETUP");
      #5000;holdTelemetry=1;
      @(negedge serviceClock);request_bits_operation=2;request_bits_address=32'h30000034;
      request_bits_data=32'h5a3ca5c3;request_bits_mask=15;request_valid=1;
      @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);#1;request_valid=0;
      wait(replyWaiting);response_ready=1;
      fork
        begin read_selected();end
        begin wait(snapshotCaptured);holdTelemetry=0;end
      join
      if(simultaneous!==1 || selectedSnapshot[31:0]!==32'ha5c35a3c)
        $fatal(1,"SAME_EDGE_SNAPSHOT_TORN_OR_NEW count=%d value=%h",simultaneous,selectedSnapshot[31:0]);
      read_selected();if(selectedSnapshot[31:0]!==32'h5a3ca5c3) $fatal(1,"NEXT_EDGE_SNAPSHOT_OLD_OR_TORN");
    """,tasks+serial)
  }

}
