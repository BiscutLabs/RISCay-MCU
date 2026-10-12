// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import java.util.zip.CRC32

class BdProgramSourceFixture(p: SocParameters) extends SramCrossingFixture(p) {
  val holdGrant=IO(Input(Bool())); val holdDecision=IO(Input(Bool()))
  val holdPublication=IO(Input(Bool())); val holdStored=IO(Input(Bool()))
  val holdCaptureReceipt=IO(Input(Bool())); val stopWorkClock=IO(Input(Bool()))
  workClock:=(serviceClock.asBool && !stopWorkClock).asClock
  fabric.io.clockRunning:= !stopWorkClock
  val observedWorkClock=IO(Output(Clock())); observedWorkClock:=workClock
  val captureWaiting=IO(Output(Bool())); captureWaiting:=programReturn.captureRequest =/= programReturn.captureAcknowledge
  programAccess.captureRequest:=programReturn.captureRequest && !holdCaptureReceipt

  val holdStoredReply=IO(Input(Bool())); val holdProgramByte=IO(Input(Bool()))
  val programLane=IO(Input(UInt(2.W))); val programByteWaiting=IO(Output(Bool()))
  for(i <- 0 until 4) {
    val hold=holdProgramByte && programLane === i.U
    programAccess.io.completions(i).valid:=fabric.io.program.completions(i).valid && !hold
    fabric.io.program.completions(i).ready:=programAccess.io.completions(i).ready && !hold
  }
  programByteWaiting:=fabric.io.program.completions(programLane).valid
  fabric.io.programSource.grant.valid:=programGrant.out.valid && !holdGrant
  programGrant.out.ready:=fabric.io.programSource.grant.ready && !holdGrant
  programDecision.in.valid:=fabric.io.programSource.decision.valid && !holdDecision
  fabric.io.programSource.decision.ready:=programDecision.in.ready && !holdDecision
  programSource.publication.req:=programReturn.publication.req && !holdPublication
  programReturn.publication.ack:=programSource.publication.ack && !holdPublication
  val nativeClick=IO(Output(Bool())); nativeClick:=false.B
  fabric.io.programSource.stored.valid:=programStored.out.valid && !holdStored
  programStored.out.ready:=fabric.io.programSource.stored.ready && !holdStored
  val blockReply=holdStoredReply && controlReplyBridge.out.bits.kind === ControlKind.Stored.U
  fabric.io.controlReply.valid:=controlReplyBridge.out.valid && !blockReply
  controlReplyBridge.out.ready:=fabric.io.controlReply.ready && !blockReply
  // Direct ingress controls acceptance-edge races; serial-host regressions run separately.
  val injectedValid=IO(Input(Bool())); val injectedLength=IO(Input(UInt(6.W)))
  val injectedBytes=IO(Input(UInt(264.W))); val injectedAccepted=IO(Output(Bool()))
  fabric.io.i2c.frame.valid:=injectedValid
  fabric.io.i2c.frame.bits:=0.U.asTypeOf(new ControlIngress)
  fabric.io.i2c.frame.bits.frame.length:=injectedLength
  for(i <- 0 until 33) fabric.io.i2c.frame.bits.frame.bytes(i):=injectedBytes(8*i+7,8*i)
  injectedAccepted:=fabric.io.hostFrameAccepted
  val grantWaiting=IO(Output(Bool())); grantWaiting:=programGrant.out.valid
  val reserved=IO(Output(Bool())); reserved:=programReserve.in.fire
  val sourceDebt=IO(Output(Bool())); sourceDebt:=programResetDebt
  val sourceDraining=IO(Output(Bool())); sourceDraining:=fabric.io.programSource.draining
  val wordAccepted=IO(Output(Bool())); wordAccepted:=programAccess.io.request.fire
  val nativeResponsePhase=IO(Output(Bool())); nativeResponsePhase:=programReturn.response.req
  val publicationAccepted=IO(Output(Bool())); publicationAccepted:=programReturn.publication.ack
  val cancelled=IO(Output(Bool())); cancelled:=programDecision.in.fire && !programDecision.in.bits
  val storedWaiting=IO(Output(Bool())); storedWaiting:=programStored.out.valid
  val storedAccepted=IO(Output(Bool())); storedAccepted:=programStored.out.fire
  val storedReplyWaiting=IO(Output(Bool()))
  storedReplyWaiting:=controlReplyBridge.out.valid && controlReplyBridge.out.bits.kind === ControlKind.Stored.U
  val storedReplyAccepted=IO(Output(Bool()))
  storedReplyAccepted:=fabric.io.controlReply.fire && fabric.io.controlReply.bits.kind === ControlKind.Stored.U
  val loaderReplyWaiting=IO(Output(Bool()))
  loaderReplyWaiting:=controlReplyBridge.out.valid && controlReplyBridge.out.bits.programWrite
  val controlIdle=IO(Output(Bool())); controlIdle:= !BoringUtils.bore(fabric.controlBusy)
  val stateView=BoringUtils.bore(fabric.controlState)
  val received=IO(Output(UInt(32.W))); received:=stateView.received
  val crc=IO(Output(UInt(32.W))); crc:=stateView.crc
  val lastError=IO(Output(UInt(8.W))); lastError:=stateView.lastError
}

class ClickProgramSourceFixture(p: SocParameters) extends ClickSramCrossingFixture(p) {
  val holdGrant=IO(Input(Bool())); val holdDecision=IO(Input(Bool()))
  val holdPublication=IO(Input(Bool())); val holdStored=IO(Input(Bool()))
  val holdCaptureReceipt=IO(Input(Bool())); val stopWorkClock=IO(Input(Bool()))
  workClock:=(serviceClock.asBool && !stopWorkClock).asClock
  fabric.io.clockRunning:= !stopWorkClock
  val observedWorkClock=IO(Output(Clock())); observedWorkClock:=workClock
  val captureWaiting=IO(Output(Bool())); captureWaiting:=programReturn.captureRequest =/= programReturn.captureAcknowledge
  programAccess.captureRequest:=Mux(holdCaptureReceipt,programReturn.captureAcknowledge,programReturn.captureRequest)

  val holdStoredReply=IO(Input(Bool())); val holdProgramByte=IO(Input(Bool()))
  val programLane=IO(Input(UInt(2.W))); val programByteWaiting=IO(Output(Bool()))
  for(i <- 0 until 4) {
    val hold=holdProgramByte && programLane === i.U
    programAccess.io.completions(i).valid:=fabric.io.program.completions(i).valid && !hold
    fabric.io.program.completions(i).ready:=programAccess.io.completions(i).ready && !hold
  }
  programByteWaiting:=fabric.io.program.completions(programLane).valid
  fabric.io.programSource.grant.valid:=programGrant.out.valid && !holdGrant
  programGrant.out.ready:=fabric.io.programSource.grant.ready && !holdGrant
  programDecision.in.valid:=fabric.io.programSource.decision.valid && !holdDecision
  fabric.io.programSource.decision.ready:=programDecision.in.ready && !holdDecision
  programSource.publication.req:=Mux(holdPublication,programSource.publication.ack,programReturn.publication.req)
  programReturn.publication.ack:=programSource.publication.ack
  val nativeClick=IO(Output(Bool())); nativeClick:=true.B
  fabric.io.programSource.stored.valid:=programStored.out.valid && !holdStored
  programStored.out.ready:=fabric.io.programSource.stored.ready && !holdStored
  val blockReply=holdStoredReply && controlReplyBridge.out.bits.kind === ControlKind.Stored.U
  fabric.io.controlReply.valid:=controlReplyBridge.out.valid && !blockReply
  controlReplyBridge.out.ready:=fabric.io.controlReply.ready && !blockReply
  // Direct ingress controls acceptance-edge races; serial-host regressions run separately.
  val injectedValid=IO(Input(Bool())); val injectedLength=IO(Input(UInt(6.W)))
  val injectedBytes=IO(Input(UInt(264.W))); val injectedAccepted=IO(Output(Bool()))
  fabric.io.i2c.frame.valid:=injectedValid
  fabric.io.i2c.frame.bits:=0.U.asTypeOf(new ControlIngress)
  fabric.io.i2c.frame.bits.frame.length:=injectedLength
  for(i <- 0 until 33) fabric.io.i2c.frame.bits.frame.bytes(i):=injectedBytes(8*i+7,8*i)
  injectedAccepted:=fabric.io.hostFrameAccepted
  val grantWaiting=IO(Output(Bool())); grantWaiting:=programGrant.out.valid
  val reserved=IO(Output(Bool())); reserved:=programReserve.in.fire
  val sourceDebt=IO(Output(Bool())); sourceDebt:=programResetDebt
  val sourceDraining=IO(Output(Bool())); sourceDraining:=fabric.io.programSource.draining
  val wordAccepted=IO(Output(Bool())); wordAccepted:=programAccess.io.request.fire
  val nativeResponsePhase=IO(Output(Bool())); nativeResponsePhase:=programReturn.response.req
  val publicationAccepted=IO(Output(Bool())); publicationAccepted:=programReturn.publication.ack
  val cancelled=IO(Output(Bool())); cancelled:=programDecision.in.fire && !programDecision.in.bits
  val storedWaiting=IO(Output(Bool())); storedWaiting:=programStored.out.valid
  val storedAccepted=IO(Output(Bool())); storedAccepted:=programStored.out.fire
  val storedReplyWaiting=IO(Output(Bool()))
  storedReplyWaiting:=controlReplyBridge.out.valid && controlReplyBridge.out.bits.kind === ControlKind.Stored.U
  val storedReplyAccepted=IO(Output(Bool()))
  storedReplyAccepted:=fabric.io.controlReply.fire && fabric.io.controlReply.bits.kind === ControlKind.Stored.U
  val loaderReplyWaiting=IO(Output(Bool()))
  loaderReplyWaiting:=controlReplyBridge.out.valid && controlReplyBridge.out.bits.programWrite
  val controlIdle=IO(Output(Bool())); controlIdle:= !BoringUtils.bore(fabric.controlBusy)
  val stateView=BoringUtils.bore(fabric.controlState)
  val received=IO(Output(UInt(32.W))); received:=stateView.received
  val crc=IO(Output(UInt(32.W))); crc:=stateView.crc
  val lastError=IO(Output(UInt(8.W))); lastError:=stateView.lastError
}

/** Independent CPU/word/macro/publication/Stored counts; no controller oracle. */
class ProgramSourceSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"program-source",Vector.empty,Vector.empty)),watchdogCycles=10000000)
  private def crc(word: Long): Long = {
    val value=new CRC32; (0 until 4).foreach(b => value.update(((word >>> (8*b)) & 255).toInt)); value.getValue
  }
  private val word=0x89abcdefL
  private val tasks="""
    wire captureAccepted=dut.ca_child_program_access.ca_child_capture_receipt.accepted;
    wire accessActive=dut.ca_child_program_access.ca_child_capture_receipt.accept;
    reg loaderWordPending=0;
    integer captures=0,beforeCaptures,cpuOffers=0,beforeOffers,j,progressWait;
    reg priorPhase;
    integer accepted=0,words=0,writes=0,published=0,cancelledCount=0,storedCount=0,storedReplies=0;
    integer n,beforeAccepted,beforeWords,beforeWrites,beforePublished,beforeCancel,beforeStored;
    always @(posedge observedWorkClock) if(!reset) begin
      if(captureAccepted) captures=captures+1;
      if(request_valid && request_ready) accepted=accepted+1;
      if(wordAccepted) words=words+1;
      if(cancelled) cancelledCount=cancelledCount+1;
      if(storedAccepted) storedCount=storedCount+1;
      if(storedReplyAccepted) storedReplies=storedReplies+1;
      if(sourceDraining && sleepEligible) $fatal(1,"PROGRAM_SOURCE_DRAIN_SLEPT");
    end
    always @(posedge dut.fabric_program_macros_0.CLK)
      if(!reset && !dut.fabric_program_macros_0.CEN && !dut.fabric_program_macros_0.GWEN) writes=writes+1;
    // Classify role from the independent host/CPU driver, not projected DUT state.
    always @(nativeResponsePhase) if(!reset && !systemReset && (nativeClick || nativeResponsePhase)) begin
      if(loaderWordPending) $fatal(1,"PROGRAM_LOADER_UNSOLICITED_CPU_RESPONSE");
      cpuOffers=cpuOffers+1;
    end
    // Observe real native acceptance, including both Click phase polarities.
    always @(publicationAccepted) if(!reset && (nativeClick || publicationAccepted)) published=published+1;
    task send_host; begin
      @(negedge serviceClock); injectedValid=1;
      @(posedge serviceClock); while(!injectedAccepted) @(posedge serviceClock);
      #1; injectedValid=0;
    end endtask
    task host_command(input [7:0] op); begin
      injectedBytes=op; injectedLength=1; send_host();
    end endtask
    task control_done; begin
      // Sample after the active edge: queue removal and outstanding capture
      // settle in separate NBA updates and may briefly make idle combinationally true.
      @(negedge serviceClock); while(!controlIdle) @(negedge serviceClock);
    end endtask
    task host_begin(input [31:0] expectedCrc); begin
      injectedBytes=0; injectedBytes[0+:8]=1; injectedBytes[8+:32]=4;
      injectedBytes[72+:32]=expectedCrc; injectedBytes[104+:32]=32'h00010000;
      injectedBytes[136+:32]=16; injectedBytes[232+:32]=32'h12345678;
      injectedLength=33; send_host();
      control_done();
      if(mode !== 1 || received !== 0 || crc !== 32'hffffffff || lastError)
        $fatal(1,"PROGRAM_SOURCE_BEGIN mode=%d received=%d crc=%h err=%d",mode,received,crc,lastError);
    end endtask
    task host_write(input [31:0] value); begin
      loaderWordPending=1;
      injectedBytes=0; injectedBytes[0+:8]=2; injectedBytes[40+:32]=value;
      injectedLength=9; send_host();
    end endtask
    task two_short_resets; begin
      applicationReset=1; #2; applicationReset=0; #2;
      applicationReset=1; #2; applicationReset=0; #2;
      if(!sourceDebt) $fatal(1,"PROGRAM_SOURCE_MISSED_RESET");
    end endtask
    task idle_check; integer quiet; begin
      quiet=0;
      while(quiet<8) begin
        @(negedge serviceClock);
        if(!sourceDebt && !sourceDraining && !memoryBusy && controlIdle) quiet=quiet+1;
        else quiet=0;
      end
      if(response_valid) $fatal(1,"PROGRAM_SOURCE_STALE_REPLY");
    end endtask
    task offer_read; begin
      loaderWordPending=0;
      @(negedge serviceClock); request_valid=1; request_bits_operation=0;
      request_bits_address=32'h10000000; request_bits_data=0; request_bits_mask=15;
    end endtask
    task admitted; begin
      @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
      #1; request_valid=0;
    end endtask
    task answer(input [31:0] expected,input error); begin
      wait(response_valid);
      if(response_bits_error !== error || (!error && response_bits_data !== expected))
        $fatal(1,"PROGRAM_SOURCE_CPU_RESULT");
      @(negedge serviceClock); response_ready=1; @(posedge serviceClock); #1; response_ready=0;
    end endtask
  """
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture=if(click) new ClickProgramSourceFixture(p) else new BdProgramSourceFixture(p)
    val upload=s"""
      idle_check(); host_begin(32'h${crc(word).toHexString}); host_write(32'h${word.toHexString});
      idle_check(); host_command(3); control_done();
      if(!programmed || received !== 4 || crc !== 32'h${(crc(word)^0xffffffffL).toHexString})
        $$fatal(1,"PROGRAM_SOURCE_UPLOAD programmed=%b received=%d crc=%h error=%d",programmed,received,crc,lastError);
    """
    test(s"$name program source: late loader overtakes a held CPU reservation and drains through repeated reset") {
      ClockedSimulation.run(fixture,name+"-program-late-loader",upload+s"""
        beforeAccepted=accepted; beforeWords=words; beforeWrites=writes;
        beforeStored=storedCount; beforeCancel=cancelledCount;
        holdGrant=1; offer_read(); wait(grantWaiting);
        if(accepted != beforeAccepted || words != beforeWords) $$fatal(1,"PROGRAM_SOURCE_EARLY_CPU_COMMIT");
        fork
          // BEGIN invalidates the image while the word grant is still held.
          // The pending CPU request must fault locally after revalidation.
          begin admitted(); answer(0,1); end
          begin host_begin(32'h${crc(word).toHexString}); host_write(32'h${word.toHexString}); end
        join
        wait(loaderReplyWaiting); @(negedge serviceClock);
        if(accepted-beforeAccepted != 1 || words != beforeWords) $$fatal(1,"PROGRAM_SOURCE_LATE_CPU_EFFECT");
        request_valid=0; holdStored=1; two_short_resets(); holdGrant=0;
        wait(storedWaiting); @(negedge serviceClock); two_short_resets();
        repeat(12) begin @(negedge serviceClock);
          if(!sourceDebt || received || crc !== 32'hffffffff || response_valid)
            $$fatal(1,"PROGRAM_SOURCE_LOADER_RESET_ACCOUNTING");
        end
        if(words-beforeWords != 1 || writes-beforeWrites != 4 || cancelledCount-beforeCancel != 1 ||
           storedCount != beforeStored) $$fatal(1,"PROGRAM_SOURCE_LATE_EFFECT_COUNTS");
        holdStored=0; idle_check();
        if(received !== 4 || crc !== 32'h${(crc(word)^0xffffffffL).toHexString} || storedCount-beforeStored != 1)
          $$fatal(1,"PROGRAM_SOURCE_STORED_EXACTLY_ONCE");
        host_command(3); control_done(); offer_read(); admitted(); answer(32'h${word.toHexString},0);
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_source"))
    }
    test(s"$name program source: accepted loader writes survive every held lane and publication stall before accounting") {
      ClockedSimulation.run(fixture,name+"-program-held-effects",s"""
        for(n=0;n<5;n=n+1) begin
          idle_check(); host_begin(32'h${crc(word).toHexString});
          beforeWords=words; beforeWrites=writes; beforeStored=storedCount; beforePublished=published;
          programLane=n; holdProgramByte=(n<4); holdPublication=(n==4);
          host_write(32'h${word.toHexString});
          if(n<4) wait(programByteWaiting); else wait(programWordWaiting);
          @(negedge serviceClock); two_short_resets();
          repeat(8) begin @(negedge serviceClock);
            if(received || crc !== 32'hffffffff || storedCount != beforeStored || published != beforePublished)
              $$fatal(1,"PROGRAM_SOURCE_PREPUBLICATION_ACCOUNTING");
          end
          applicationReset=1; holdProgramByte=0; holdPublication=0;
          wait(storedReplies == storedCount && received==4); @(negedge serviceClock);
          if(words-beforeWords != 1 || writes-beforeWrites != 4 || storedCount-beforeStored != 1 ||
             published-beforePublished != 1 || crc !== 32'h${(crc(word)^0xffffffffL).toHexString})
            $$fatal(1,"PROGRAM_SOURCE_RESET_EFFECT_COUNTS");
          applicationReset=0; idle_check();
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_source"))
    }
    test(s"$name program source: stale CPU publication fences a new read across repeated short resets") {
      ClockedSimulation.run(fixture,name+"-program-cpu-publication",upload+"""
        for(n=0;n<6;n=n+1) begin
          idle_check(); beforeWords=words; beforeAccepted=accepted;
          holdPublication=1; offer_read(); admitted(); wait(programWordWaiting);
          @(negedge serviceClock); two_short_resets(); offer_read();
          repeat(12) begin @(negedge serviceClock);
            if(!sourceDebt || request_ready || response_valid || words-beforeWords != 1 || accepted-beforeAccepted != 1)
              $fatal(1,"PROGRAM_SOURCE_CPU_REUSE_FENCE");
          end
          two_short_resets(); holdPublication=0; admitted(); answer(32'h89abcdef,0);
          idle_check();
          if(words-beforeWords != 2 || accepted-beforeAccepted != 2) $fatal(1,"PROGRAM_SOURCE_CPU_COUNTS");
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_source"))
    }
    test(s"$name program return: loader never offers native CPU response across role and phase alternation without reset") {
      ClockedSimulation.run(fixture,name+"-program-role-phase-alternation",s"""
        for(n=0;n<4;n=n+1) begin
          idle_check();host_begin(32'h${crc(word).toHexString});
          beforeOffers=cpuOffers;beforeWords=words;beforeWrites=writes;
          beforePublished=published;beforeStored=storedCount;priorPhase=nativeResponsePhase;
          holdPublication=1;holdStored=1;host_write(32'h${word.toHexString});
          wait(programWordWaiting);repeat(40) @(negedge serviceClock);
          if(cpuOffers!=beforeOffers || nativeResponsePhase!==priorPhase || storedCount!=beforeStored || received!==0)
            $$fatal(1,"PROGRAM_LOADER_ROLE_BEFORE_PUBLICATION");
          holdPublication=0;wait(storedWaiting);repeat(40) @(negedge serviceClock);
          if(cpuOffers!=beforeOffers || nativeResponsePhase!==priorPhase || storedCount!=beforeStored || received!==0)
            $$fatal(1,"PROGRAM_LOADER_ROLE_BEFORE_STORED");
          holdStored=0;idle_check();
          if(cpuOffers!=beforeOffers || nativeResponsePhase!==priorPhase || words-beforeWords!=1 ||
             writes-beforeWrites!=4 || published-beforePublished!=1 || storedCount-beforeStored!=1 ||
             received!==4 || crc!==32'h${(crc(word)^0xffffffffL).toHexString})
            $$fatal(1,"PROGRAM_LOADER_ROLE_COMPLETED");
          host_command(3);control_done();
          // One, two, one, two reads put loader words at both retained CPU phases.
          for(j=0;j<(n%2+1);j=j+1) begin
            offer_read();admitted();answer(32'h${word.toHexString},0);idle_check();
          end
          if(cpuOffers-beforeOffers!=(n%2+1) || words-beforeWords!=(n%2+2) ||
             published-beforePublished!=(n%2+2) || storedCount-beforeStored!=1 || writes-beforeWrites!=4)
            $$fatal(1,"PROGRAM_CPU_LOADER_PHASE_COUNTS");
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_return"))
    }
    test(s"$name program capture receipt: loader remains POR-owned through reset release and stopped work clock") {
      ClockedSimulation.run(fixture,name+"-program-loader-capture-reset",s"""
        for(n=0;n<4;n=n+1) begin
          idle_check();host_begin(32'h${crc(word).toHexString});
          beforeWords=words;beforeWrites=writes;beforePublished=published;
          beforeStored=storedCount;beforeCaptures=captures;
          holdCaptureReceipt=(n%2==0);host_write(32'h${word.toHexString});
          wait(captureWaiting);@(negedge serviceClock);
          if(n%2==1) stopWorkClock=1;
          two_short_resets();wait(!systemReset);
          repeat(20) begin @(negedge serviceClock);
            if(!accessActive || !memoryBusy || !sourceDebt || request_ready || response_valid ||
              captures!=beforeCaptures || words-beforeWords!=1 || writes-beforeWrites!=4 || published!=beforePublished)
              $$fatal(1,"PROGRAM_LOADER_CAPTURE_FENCE_OR_EFFECT_COUNT");
          end
          // Prove independent Stored progress, rather than merely permitting it.
          // The stopped-clock case cannot consume a clocked Control command yet.
          if(n%2==0) begin
            progressWait=0;
            while((storedCount-beforeStored!=1 || storedReplies!=storedCount || received!==4) && progressWait<500) begin
              @(negedge serviceClock);progressWait=progressWait+1;
            end
            if(storedCount-beforeStored!=1 || storedReplies!=storedCount || received!==4 ||
               crc!==32'h${(crc(word)^0xffffffffL).toHexString} || captures!=beforeCaptures ||
               published!=beforePublished || !memoryBusy || !accessActive || response_valid)
              $$fatal(1,"PROGRAM_STORED_DEPENDS_ON_CAPTURE_RETURN");
          end
          holdCaptureReceipt=0;stopWorkClock=0;idle_check();
          if(words-beforeWords!=1 || writes-beforeWrites!=4 || captures-beforeCaptures!=1 ||
             published-beforePublished!=1 || storedCount-beforeStored!=1 || received!==4 ||
             crc!==32'h${(crc(word)^0xffffffffL).toHexString})
            $$fatal(1,"PROGRAM_LOADER_CAPTURE_RETURN_COUNTS");
          host_command(3);control_done();offer_read();admitted();answer(32'h${word.toHexString},0);
          idle_check();
          if(captures-beforeCaptures!=2 || published-beforePublished!=2 || storedCount-beforeStored!=1)
            $$fatal(1,"PROGRAM_LOADER_CPU_PHASE_ATTRIBUTION");
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_return"))
    }
    test(s"$name program capture receipt: cancelled CPU word fences fresh read after stopped clock and repeated reset") {
      ClockedSimulation.run(fixture,name+"-program-cpu-capture-reset",upload+"""
        for(n=0;n<4;n=n+1) begin
          idle_check();beforeWords=words;beforeWrites=writes;beforePublished=published;
          beforeStored=storedCount;beforeCaptures=captures;
          holdCaptureReceipt=(n%2==0);offer_read();admitted();
          wait(captureWaiting);@(negedge serviceClock);
          if(n%2==1) stopWorkClock=1;
          two_short_resets();wait(!systemReset);offer_read();
          repeat(20) begin @(negedge serviceClock);
            if(!accessActive || !memoryBusy || !sourceDebt || request_ready || response_valid ||
              captures!=beforeCaptures || words-beforeWords!=1 || writes!=beforeWrites || published!=beforePublished)
              $fatal(1,"PROGRAM_CPU_CAPTURE_FENCE_OR_EFFECT_COUNT");
          end
          two_short_resets();holdCaptureReceipt=0;stopWorkClock=0;
          admitted();answer(32'h89abcdef,0);idle_check();
          if(words-beforeWords!=2 || writes!=beforeWrites || captures-beforeCaptures!=2 ||
             published-beforePublished!=2 || storedCount!=beforeStored)
            $fatal(1,"PROGRAM_CPU_CAPTURE_RETURN_COUNTS");
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_return"))
    }
    test(s"$name program source: WRITE and VERIFY retain busy history on Stored command and reply edges") {
      ClockedSimulation.run(fixture,name+"-program-stored-busy-history",s"""
        for(n=0;n<6;n=n+1) begin
          idle_check(); host_begin(32'h${crc(word).toHexString});
          beforeWords=words; beforeWrites=writes; beforeStored=storedCount;
          holdStored=1; holdStoredReply=1; host_write(32'h${word.toHexString});
          wait(storedWaiting); @(negedge serviceClock);
          injectedBytes=0; injectedBytes[0+:8]=(n<3 ? 2 : 3);
          injectedBytes[8+:32]=4; injectedBytes[40+:32]=32'h12345678;
          injectedLength=(n<3 ? 9 : 1);
          if(n%3==0) begin
            holdStored=0; injectedValid=1;
            @(posedge serviceClock);
            if(!storedAccepted || !injectedAccepted) $$fatal(1,"PROGRAM_SOURCE_STORED_COMMAND_EDGE_NOT_HIT");
            #1; injectedValid=0;
            wait(storedReplyWaiting); @(negedge serviceClock); holdStoredReply=0;
          end else if(n%3==1) begin
            holdStored=0; wait(storedReplyWaiting);
            send_host();
            repeat(4) @(negedge serviceClock);
            // Keep the reply held until physical access is quiet. This isolates
            // admission-time busy history from the independent live busy guard.
            progressWait=0;
            while(memoryBusy && progressWait<500) begin
              @(negedge serviceClock);progressWait=progressWait+1;
            end
            if(memoryBusy) $$fatal(1,"PROGRAM_SOURCE_ACCESS_WAITED_FOR_STORED_REPLY");
            if(!storedReplyWaiting || received !== 0) $$fatal(1,"PROGRAM_SOURCE_STORED_REPLY_NOT_HELD");
            holdStoredReply=0;
          end else begin
            holdStored=0; wait(storedReplyWaiting); @(negedge serviceClock);
            injectedValid=1; holdStoredReply=0;
            @(posedge serviceClock);
            if(!storedReplyAccepted || !injectedAccepted) $$fatal(1,"PROGRAM_SOURCE_STORED_REPLY_EDGE_NOT_HIT");
            #1; injectedValid=0;
          end
          idle_check();
          if(lastError !== 3 || programmed || received !== 4 || crc !== 32'h${(crc(word)^0xffffffffL).toHexString} ||
             words-beforeWords != 1 || writes-beforeWrites != 4 || storedCount-beforeStored != 1)
            $$fatal(1,"PROGRAM_SOURCE_STORED_BUSY_HISTORY error=%d received=%d",lastError,received);
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_source"))
    }
    test(s"$name program source: loader grant and decision stalls preserve the held reply through reset") {
      ClockedSimulation.run(fixture,name+"-program-loader-commit-stalls",s"""
        for(n=0;n<2;n=n+1) begin
          idle_check(); host_begin(32'h${crc(word).toHexString});
          beforeWords=words; beforeWrites=writes; beforeStored=storedCount; beforeCancel=cancelledCount;
          holdGrant=(n==0); holdDecision=(n==1); host_write(32'h${word.toHexString});
          wait(loaderReplyWaiting && grantWaiting); @(negedge serviceClock); two_short_resets();
          repeat(12) begin @(negedge serviceClock);
            if(!loaderReplyWaiting || words != beforeWords || writes != beforeWrites || received ||
               storedCount != beforeStored || cancelledCount != beforeCancel)
              $$fatal(1,"PROGRAM_SOURCE_LOADER_PRECOMMIT_EFFECT");
          end
          applicationReset=1; holdGrant=0; holdDecision=0;
          wait(received==4); @(negedge serviceClock);
          if(words-beforeWords != 1 || writes-beforeWrites != 4 || storedCount-beforeStored != 1 ||
             cancelledCount != beforeCancel || crc !== 32'h${(crc(word)^0xffffffffL).toHexString})
            $$fatal(1,"PROGRAM_SOURCE_LOADER_ATOMIC_COMMIT");
          applicationReset=0; idle_check();
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_program_source"))
    }
  }
}
