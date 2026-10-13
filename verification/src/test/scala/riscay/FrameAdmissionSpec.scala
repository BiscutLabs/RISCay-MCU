// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import java.util.zip.CRC32
import java.nio.file.{Files, Paths}
import scala.jdk.CollectionConverters._

/** Real serial/native publication path; only acceptance and downstream consumption
  * are stalled. The inherited direct ingress test port is deliberately disconnected.
  */
class BdFrameAdmissionFixture(p: SocParameters) extends BdProgramSourceFixture(p,directIngress=false) {
  val holdFrame=IO(Input(Bool())); val holdHostCommands=IO(Input(Bool()))
  val holdSelectedHead=IO(Input(Bool()))
  for(i <- 0 until 4) {
    fabric.io.i2c.heads(i).valid:=host.host.heads(i).valid && !holdSelectedHead
    host.host.heads(i).ready:=fabric.io.i2c.heads(i).ready && !holdSelectedHead
  }
  val workRunning=IO(Output(Bool()))
  val enabled=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(!stopWorkClock,false.B) }
  workRunning:=enabled; workClock:=(serviceClock.asBool && enabled).asClock
  fabric.io.clockRunning:=enabled
  host.frameAcceptEnable:=enabled && !holdFrame
  controlCommandBridge.in.valid:=fabric.io.controlCommand.valid && !holdHostCommands
  fabric.io.controlCommand.ready:=controlCommandBridge.in.ready && !holdHostCommands
  val observedNativeFrame=IO(Output(UInt(337.W)))
  observedNativeFrame:=BoringUtils.bore(host.native.frame.bits).asUInt
  val nativeRequest=IO(Output(Bool())); nativeRequest:=BoringUtils.bore(host.native.frame.req)
  val nativeAcknowledge=IO(Output(Bool())); nativeAcknowledge:=BoringUtils.bore(host.native.frame.ack)
  val copyAcknowledge=IO(Output(Bool())); copyAcknowledge:=BoringUtils.bore(host.frameStore.in.ack)
  val receiptAcknowledge=IO(Output(Bool())); receiptAcknowledge:=BoringUtils.bore(host.frames.in.ack)
  val receiptValid=IO(Output(Bool())); receiptValid:=BoringUtils.bore(host.frames.out.valid)
  val receiptReady=IO(Output(Bool())); receiptReady:=BoringUtils.bore(host.frames.out.ready)
  val originalOffer=IO(Output(Bool())); originalOffer:=host.host.frameOffered
  val currentCancel=IO(Output(Bool())); currentCancel:=fabric.io.applicationCancel
  val currentEpoch=IO(Output(UInt(64.W))); currentEpoch:=BoringUtils.bore(host.resetEpoch)
  val observedFrameSlot=IO(Output(UInt(2.W))); observedFrameSlot:=host.host.frameSlot
  val observedBankFrames=IO(Output(UInt(1348.W)))
  observedBankFrames:=VecInit(host.host.heads.map(_.bits.asUInt)).asUInt
  val observedHeadValid=IO(Output(UInt(4.W))); observedHeadValid:=VecInit(host.host.heads.map(_.valid)).asUInt
  val observedHeadFire=IO(Output(UInt(4.W))); observedHeadFire:=VecInit(host.host.heads.map(_.fire)).asUInt
  val currentReset=IO(Output(Bool())); currentReset:=fabric.io.cpuResetActive
  val currentBusy=IO(Output(Bool())); currentBusy:=host.host.programBusy
  val hostBusy=IO(Output(Bool())); hostBusy:=host.host.busy
  val hostDispatched=IO(Output(Bool()))
  hostDispatched:=fabric.io.controlCommand.fire && fabric.io.controlCommand.bits.kind === ControlKind.Host.U
  val mmioDispatched=IO(Output(Bool()))
  mmioDispatched:=fabric.io.controlCommand.fire && fabric.io.controlCommand.bits.kind === ControlKind.Mmio.U
  val dispatchedFrame=IO(Output(UInt(273.W)))
  val dispatched=Wire(new ControlIngress)
  dispatched.frame:=fabric.io.controlCommand.bits.frame
  dispatched.resetActive:=fabric.io.controlCommand.bits.cpuResetActive
  dispatched.programBusy:=fabric.io.controlCommand.bits.programBusy
  dispatchedFrame:=dispatched.asUInt
}

class ClickFrameAdmissionFixture(p: SocParameters) extends ClickProgramSourceFixture(p,directIngress=false) {
  val holdFrame=IO(Input(Bool())); val holdHostCommands=IO(Input(Bool()))
  val holdSelectedHead=IO(Input(Bool()))
  for(i <- 0 until 4) {
    fabric.io.i2c.heads(i).valid:=host.host.heads(i).valid && !holdSelectedHead
    host.host.heads(i).ready:=fabric.io.i2c.heads(i).ready && !holdSelectedHead
  }
  val workRunning=IO(Output(Bool()))
  val enabled=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(!stopWorkClock,false.B) }
  workRunning:=enabled; workClock:=(serviceClock.asBool && enabled).asClock
  fabric.io.clockRunning:=enabled
  host.frameAcceptEnable:=enabled && !holdFrame
  controlCommandBridge.in.valid:=fabric.io.controlCommand.valid && !holdHostCommands
  fabric.io.controlCommand.ready:=controlCommandBridge.in.ready && !holdHostCommands
  val observedNativeFrame=IO(Output(UInt(337.W)))
  observedNativeFrame:=BoringUtils.bore(host.native.frame.bits).asUInt
  val nativeRequest=IO(Output(Bool())); nativeRequest:=BoringUtils.bore(host.native.frame.req)
  val nativeAcknowledge=IO(Output(Bool())); nativeAcknowledge:=BoringUtils.bore(host.native.frame.ack)
  val copyAcknowledge=IO(Output(Bool())); copyAcknowledge:=BoringUtils.bore(host.frameStore.in.ack)
  val receiptAcknowledge=IO(Output(Bool())); receiptAcknowledge:=BoringUtils.bore(host.frames.in.ack)
  val receiptValid=IO(Output(Bool())); receiptValid:=BoringUtils.bore(host.frames.out.valid)
  val receiptReady=IO(Output(Bool())); receiptReady:=BoringUtils.bore(host.frames.out.ready)
  val originalOffer=IO(Output(Bool())); originalOffer:=host.host.frameOffered
  val currentCancel=IO(Output(Bool())); currentCancel:=fabric.io.applicationCancel
  val currentEpoch=IO(Output(UInt(64.W))); currentEpoch:=BoringUtils.bore(host.resetEpoch)
  val observedFrameSlot=IO(Output(UInt(2.W))); observedFrameSlot:=host.host.frameSlot
  val observedBankFrames=IO(Output(UInt(1348.W)))
  observedBankFrames:=VecInit(host.host.heads.map(_.bits.asUInt)).asUInt
  val observedHeadValid=IO(Output(UInt(4.W))); observedHeadValid:=VecInit(host.host.heads.map(_.valid)).asUInt
  val observedHeadFire=IO(Output(UInt(4.W))); observedHeadFire:=VecInit(host.host.heads.map(_.fire)).asUInt
  val currentReset=IO(Output(Bool())); currentReset:=fabric.io.cpuResetActive
  val currentBusy=IO(Output(Bool())); currentBusy:=host.host.programBusy
  val hostBusy=IO(Output(Bool())); hostBusy:=host.host.busy
  val hostDispatched=IO(Output(Bool()))
  hostDispatched:=fabric.io.controlCommand.fire && fabric.io.controlCommand.bits.kind === ControlKind.Host.U
  val mmioDispatched=IO(Output(Bool()))
  mmioDispatched:=fabric.io.controlCommand.fire && fabric.io.controlCommand.bits.kind === ControlKind.Mmio.U
  val dispatchedFrame=IO(Output(UInt(273.W)))
  val dispatched=Wire(new ControlIngress)
  dispatched.frame:=fabric.io.controlCommand.bits.frame
  dispatched.resetActive:=fabric.io.controlCommand.bits.cpuResetActive
  dispatched.programBusy:=fabric.io.controlCommand.bits.programBusy
  dispatchedFrame:=dispatched.asUInt
}

/** Context fault injection at the existing service boundary, with real native
  * serial payload/copy/admission. Normal wire tests use the unmodified fixtures.
  */
class BdFrameContextFixture(p: SocParameters) extends BdFrameAdmissionFixture(p) {
  val resetContext=IO(Input(Bool())); val busyContext=IO(Input(Bool()))
  fabric.io.i2c.frame.bits.resetActive:=host.host.frame.bits.resetActive || resetContext
  fabric.io.i2c.frame.bits.programBusy:=host.host.frame.bits.programBusy || busyContext
}
class ClickFrameContextFixture(p: SocParameters) extends ClickFrameAdmissionFixture(p) {
  val resetContext=IO(Input(Bool())); val busyContext=IO(Input(Bool()))
  fabric.io.i2c.frame.bits.resetActive:=host.host.frame.bits.resetActive || resetContext
  fabric.io.i2c.frame.bits.programBusy:=host.host.frame.bits.programBusy || busyContext
}

/** Composed real-wire proof complements the isolated 337-bit receipt campaign.
  * Monitors compare actual descriptors and their native retained payloads.
  */
class FrameAdmissionSpec extends AnyFunSuite {
  private val config=McuConfiguration(16,32,1,Vector.empty,
    ApplicationProfile(1,1,"frame-admission",Vector.empty,Vector.empty))
  private def params(hz: Int)=SocParameters(config,serviceHz=hz,watchdogCycles=10000000)
  private val word=0x89abcdefL
  private val crcValue={ val c=new CRC32; (0 until 4).foreach(i=>c.update(((word >>> (i*8)) & 255).toInt)); c.getValue }
  private def packed(slot: String): String = {
    val base="dut.fabric_hostFrames_"+slot+"_"
    Seq(base+"bank",base+"resetActive",base+"programBusy").mkString("{",",","}")
  }
  private val monitors=s"""
    wire [3:0] descriptorFirst=${packed("first")};
    wire [3:0] descriptorSecond=${packed("second")};
    wire [336:0] nativeBanks[0:3];
    assign nativeBanks[0]=observedBankFrames[0+:337];
    assign nativeBanks[1]=observedBankFrames[337+:337];
    assign nativeBanks[2]=observedBankFrames[674+:337];
    assign nativeBanks[3]=observedBankFrames[1011+:337];
    wire [272:0] mailboxFirst={nativeBanks[descriptorFirst[3:2]][336:66],descriptorFirst[1:0]};
    wire [272:0] mailboxSecond={nativeBanks[descriptorSecond[3:2]][336:66],descriptorSecond[1:0]};
    wire [1:0] mailboxCount=dut.fabric_hostFrames_count;
    integer admissions=0,dispatches=0,firstCaptures=0,secondCaptures=0,simultaneous=0;
    integer mmioDispatches=0,hostsBeforeMmio=0;
    integer q=0,beforeAdmissions,beforeDispatches,n,j,storedEdges=0,replyEdges=0;
    reg [272:0] expectedFirst=0,expectedSecond=0,arrival;
    reg [336:0] expectedNativeFirst=0,expectedNativeSecond=0;
    reg [3:0] expectedDescriptorFirst=0,expectedDescriptorSecond=0,arrivalDescriptor;
    reg [3:0] liveBanks=0;
    reg offeredReset=0,offeredBusy=0;
    integer nextBank=0;
    integer bankAdmissions[0:3];
    initial begin bankAdmissions[0]=0;bankAdmissions[1]=0;bankAdmissions[2]=0;bankAdmissions[3]=0;end
    reg [336:0] heldNative;
    reg heldAck;
    reg [263:0] sendBytes;
    reg [5:0] sendLength;
    integer checkCount;
    always @(posedge observedWorkClock) if(!reset) begin
      if(mailboxCount !== q) $$fatal(1,"FRAME_ADMISSION_PRE_COUNT");
      if(originalOffer) begin
        offeredReset=offeredReset || observedNativeFrame[65] || currentCancel ||
          observedNativeFrame[63:0]!=currentEpoch;
        offeredBusy=offeredBusy || observedNativeFrame[64] || currentBusy;
      end
      if(mmioDispatched) begin mmioDispatches=mmioDispatches+1;hostsBeforeMmio=dispatches;end
      if(observedHeadFire !== (hostDispatched ? (4'b0001 << expectedDescriptorFirst[3:2]) : 4'b0000))
        $$fatal(1,"FRAME_ADMISSION_HEAD_RETIRE_IDENTITY");
      if(hostDispatched) begin
        if(q==0 || !observedHeadValid[expectedDescriptorFirst[3:2]])
          $$fatal(1,"FRAME_ADMISSION_DISPATCH_WITHOUT_HEAD");
        // The source epoch, rather than clocked reset debt, retains every
        // reset after A. Data and busy history keep the admitted identity.
        if(dispatchedFrame[272:2] !== expectedFirst[272:2] ||
           dispatchedFrame[0] !== expectedFirst[0] ||
           dispatchedFrame[1] !== (expectedFirst[1] || currentReset ||
             expectedNativeFirst[63:0] != currentEpoch)) $$fatal(1,"FRAME_ADMISSION_DISPATCH_IDENTITY");
        if(nativeBanks[expectedDescriptorFirst[3:2]] !== expectedNativeFirst)
          $$fatal(1,"FRAME_ADMISSION_DISPATCH_NATIVE_IDENTITY");
        liveBanks[expectedDescriptorFirst[3:2]]=0;
        dispatches=dispatches+1;
      end
      if(injectedAccepted) begin
        if(!receiptValid || !receiptReady || !workRunning) $$fatal(1,"FRAME_ADMISSION_WITHOUT_WORK_CAPTURE");
        if(observedFrameSlot !== nextBank || liveBanks[observedFrameSlot])
          $$fatal(1,"FRAME_ADMISSION_BANK_ROTATION_OR_OVERWRITE");
        if(nativeBanks[observedFrameSlot] !== observedNativeFrame)
          $$fatal(1,"FRAME_ADMISSION_NATIVE_COPY_BEFORE_A");
        arrival=observedNativeFrame[336:64];
        arrival[1]=offeredReset || observedNativeFrame[65] || currentCancel || (observedNativeFrame[63:0] != currentEpoch);
        arrival[0]=offeredBusy || observedNativeFrame[64] || currentBusy;
        arrivalDescriptor={observedFrameSlot,arrival[1:0]};
        liveBanks[observedFrameSlot]=1; bankAdmissions[observedFrameSlot]=bankAdmissions[observedFrameSlot]+1;
        nextBank=(nextBank+1)%4;
        admissions=admissions+1;
        if(storedAccepted) storedEdges=storedEdges+1;
        if(storedReplyAccepted) replyEdges=replyEdges+1;
        if(hostDispatched) begin
          expectedFirst=arrival;expectedNativeFirst=observedNativeFrame;expectedDescriptorFirst=arrivalDescriptor;
          simultaneous=simultaneous+1;firstCaptures=firstCaptures+1;
        end else if(q==0) begin
          expectedFirst=arrival;expectedNativeFirst=observedNativeFrame;expectedDescriptorFirst=arrivalDescriptor;
          q=1;firstCaptures=firstCaptures+1;
        end else if(q==1) begin
          expectedSecond=arrival;expectedNativeSecond=observedNativeFrame;expectedDescriptorSecond=arrivalDescriptor;
          q=2;secondCaptures=secondCaptures+1;
        end
        else $$fatal(1,"FRAME_ADMISSION_TEST_OVERFLOW");
        offeredReset=0;offeredBusy=0;
      end else if(hostDispatched) begin
        expectedFirst=expectedSecond;expectedNativeFirst=expectedNativeSecond;expectedDescriptorFirst=expectedDescriptorSecond;
        q=q-1;
      end
      #0.1;
      // Descriptor Q is checked even when unused. Only live descriptors own a
      // bank: an unused descriptor may point at a legitimately recycled payload.
      if(mailboxCount !== q || descriptorFirst !== expectedDescriptorFirst || descriptorSecond !== expectedDescriptorSecond ||
         (q>0 && (mailboxFirst !== expectedFirst || nativeBanks[descriptorFirst[3:2]] !== expectedNativeFirst)) ||
         (q>1 && (mailboxSecond !== expectedSecond || nativeBanks[descriptorSecond[3:2]] !== expectedNativeSecond)))
        $$fatal(1,"FRAME_ADMISSION_ACTUAL_MAILBOX_CAPTURE");
    end
    // ACK is permitted only on a real work edge, and the sender must hold all
    //337 source bits through destination capture. Physical timing is unqualified.
    always @(posedge serviceClock) if(!reset && !workRunning && receiptValid) begin
      if(receiptReady || injectedAccepted) $$fatal(1,"FRAME_ADMISSION_STOPPED_WORK_ACK");
    end
    task control_done; begin
      @(negedge serviceClock); while(!controlIdle) @(negedge serviceClock);
    end endtask
    task native_return; begin
      if(nativeClick) wait(nativeRequest==nativeAcknowledge);
      else wait(!nativeRequest && !nativeAcknowledge);
      repeat(4) @(negedge serviceClock);
    end endtask
    task release_frame; begin
      @(negedge serviceClock); #1; holdFrame=0;
      @(posedge observedWorkClock); while(!injectedAccepted) @(posedge observedWorkClock);
      #1; native_return();
    end endtask
    task held_command(input [7:0] opcode); begin
      @(negedge serviceClock); #1; holdFrame=1;
      if(opcode==2) put_word(4,32'h12345678); else command(opcode);
      wait(receiptValid); @(negedge serviceClock);
      if(!hostBusy || nativeRequest==nativeAcknowledge) $$fatal(1,"FRAME_ADMISSION_NATIVE_HOLD_PRECONDITION");
      heldNative=observedNativeFrame; heldAck=nativeAcknowledge;
    end endtask
    task send_frame; integer b; begin
      start_bus(); write_byte(8'h6a);
      for(b=0;b<sendLength;b=b+1) write_byte(sendBytes[b*8+:8]);
      stop_bus();
    end endtask
  """
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(hz: Int): SocTop=if(click) new ClickFrameAdmissionFixture(params(hz)) else new BdFrameAdmissionFixture(params(hz))
    val slowCopy=Map(("ca_child_i2c.ca_child_frame_store",if(click) "request_delay" else "request_guard") -> 8000000000L)
    if(!click) test("bd frame admission: source return waits for actual copy-low observation") {
      ClockedSimulation.run(fixture(20000000),"bd-frame-admission-copy-rearm","""
        control_done();holdHostCommands=1;
        fork
          command(9);
          begin
            wait(injectedAccepted);@(posedge observedWorkClock);#0.001;
            // Delay the actual retained synchronizer's return observation.
            // Other receipt clocks and both raw native return paths keep running.
            force dut.ca_child_i2c.copied=1'b1;
            wait(nativeAcknowledge);
            wait(!nativeRequest && !copyAcknowledge && !receiptAcknowledge);
            repeat(8) begin
              @(posedge serviceClock);#0.001;
              if(!nativeAcknowledge || nativeRequest || injectedAccepted ||
                 admissions!=1 || observedFrameSlot!=1)
                $fatal(1,"FRAME_BD_COPY_REARM_RELEASED_EARLY");
            end
            release dut.ca_child_i2c.copied;
            wait(!nativeAcknowledge);
          end
        join
        @(negedge serviceClock);#1;holdHostCommands=0;control_done();
        command(9);native_return();control_done();
        if(admissions!=2 || dispatches!=2 || mailboxCount || liveBanks)
          $fatal(1,"FRAME_BD_COPY_REARM_REPLAY_OR_LOSS");
      """,monitors,serviceHalfPeriodNs=25,maximumDelaySubtree=Some("i2c"),deadlineNs=500000)
    }
    test(s"$name frame admission: original-offer context remains after it clears before late copy") {
      def contextFixture: SocTop=if(click) new ClickFrameContextFixture(params(20000000)) else new BdFrameContextFixture(params(20000000))
      ClockedSimulation.run(contextFixture,name+"-frame-admission-late-context","""
        @(negedge serviceClock);while(!controlIdle) @(negedge serviceClock);
        #1;holdHostCommands=1;command(9);wait(receiptValid);@(negedge serviceClock);
        if(!originalOffer || copyAcknowledge===nativeRequest || receiptReady ||
           observedNativeFrame[65:64] || currentCancel || currentBusy)
          $fatal(1,"FRAME_LATE_CONTEXT_PRECONDITION");
        // A one-edge boundary observation disappears before the actual copy.
        // Neither the retained source payload nor its epoch supplies this fact.
        #1;resetContext=1;busyContext=1;
        @(posedge observedWorkClock);
        if(!originalOffer || injectedAccepted) $fatal(1,"FRAME_LATE_CONTEXT_OFFER_NOT_OBSERVED");
        @(negedge serviceClock);#1;resetContext=0;busyContext=0;
        wait(injectedAccepted);@(posedge observedWorkClock);#1;
        if(resetContext || busyContext || observedNativeFrame[65:64] ||
           observedNativeFrame[63:0]!=currentEpoch || currentCancel || currentBusy)
          $fatal(1,"FRAME_LATE_CONTEXT_NOT_CLEARED_BEFORE_A");
        if(!dut.fabric_hostFrames_first_resetActive)
          $fatal(1,"FRAME_LATE_CONTEXT_RESET_HISTORY_LOST");
        if(!dut.fabric_hostFrames_first_programBusy)
          $fatal(1,"FRAME_LATE_CONTEXT_BUSY_HISTORY_LOST");
        @(negedge serviceClock);#1;holdHostCommands=0;
        wait(hostDispatched);
        if(dispatchedFrame[1:0]!==2'b11)
          $fatal(1,"FRAME_LATE_CONTEXT_DISPATCH_LOST");
        @(posedge observedWorkClock);#1;
        @(negedge serviceClock);while(!controlIdle) @(negedge serviceClock);
      """,serviceHalfPeriodNs=25,deadlineNs=500000,primitiveDelayOverrides=slowCopy,powerOnResetNs=20000)
    }
    test(s"$name frame admission: late native copy holds slot and publisher through stopped work") {
      // Deliberately make capture much slower than the old two-clock assumption.
      // The injected 8 us cell also delays reset, so only these fault-injection
      // fixtures use a 20 us POR. Production pulse tests keep their old durations.
      ClockedSimulation.run(fixture(20000000),name+"-frame-admission-late-copy","""
        control_done();
        for(n=0;n<8;n=n+1) begin
          @(negedge serviceClock);#1;holdHostCommands=1;
          beforeAdmissions=admissions;beforeDispatches=dispatches;
          command(9);wait(receiptValid);@(negedge serviceClock);
          heldNative=observedNativeFrame;heldAck=nativeAcknowledge;
          if(copyAcknowledge===nativeRequest || receiptReady || injectedAccepted ||
             observedFrameSlot!==n%4 || mailboxCount)
            $fatal(1,"FRAME_LATE_COPY_STALL_NOT_EXERCISED");
          repeat(6) begin
            @(posedge observedWorkClock);
            if(copyAcknowledge===nativeRequest || receiptReady || injectedAccepted ||
               admissions!=beforeAdmissions || observedFrameSlot!==n%4 ||
               observedNativeFrame!==heldNative || nativeAcknowledge!==heldAck)
              $fatal(1,"FRAME_LATE_COPY_EARLY_ADMISSION_OR_RELEASE");
          end
          // Native copy must finish even while work is stopped. Acceptance and
          // descriptor rotation still require the real destination work edge.
          @(negedge serviceClock);#1;stopWorkClock=1;
          repeat(3) @(negedge serviceClock);
          if(workRunning) $fatal(1,"FRAME_LATE_COPY_WORK_STOP_PRECONDITION");
          wait(copyAcknowledge===nativeRequest);
          repeat(4) @(negedge serviceClock);
          if(receiptReady || injectedAccepted || admissions!=beforeAdmissions ||
             observedFrameSlot!==n%4 || observedNativeFrame!==heldNative ||
             nativeAcknowledge!==heldAck || !hostBusy)
            $fatal(1,"FRAME_LATE_COPY_STOPPED_WORK_RELEASE");
          @(negedge serviceClock);#1;stopWorkClock=0;
          wait(admissions==beforeAdmissions+1);native_return();
          if(mailboxCount!=1 || dispatches!=beforeDispatches || mailboxFirst!==heldNative[336:64])
            $fatal(1,"FRAME_LATE_COPY_CAPTURE_IDENTITY");
          @(negedge serviceClock);#1;holdHostCommands=0;control_done();
          if(dispatches!=admissions || mailboxCount || liveBanks)
            $fatal(1,"FRAME_LATE_COPY_REPLAY_OR_LOSS");
        end
        for(j=0;j<4;j=j+1) if(bankAdmissions[j]!=2)
          $fatal(1,"FRAME_LATE_COPY_BANK_OR_PHASE_COVERAGE");
      """,monitors,serviceHalfPeriodNs=25,deadlineNs=2000000,primitiveDelayOverrides=slowCopy,powerOnResetNs=20000)
    }
    for(hz <- Seq(3200000,20000000)) {
      test(s"$name frame admission: native held frame survives stopped work and repeated reset at $hz Hz") {
        ClockedSimulation.run(fixture(hz),name+"-frame-admission-reset",s"""
          control_done(); holdHostCommands=1; held_command(5); beforeAdmissions=admissions;
          @(negedge serviceClock); #1; stopWorkClock=1;
          repeat(3) @(negedge serviceClock);
          if(workRunning) $$fatal(1,"FRAME_ADMISSION_WORK_STOP_PRECONDITION");
          holdFrame=0;
          for(n=0;n<3;n=n+1) begin
            applicationReset=1; repeat(12) @(negedge serviceClock); applicationReset=0;
            repeat(12) @(negedge serviceClock);
            if(observedNativeFrame !== heldNative || nativeAcknowledge !== heldAck ||
               admissions != beforeAdmissions || !receiptValid || !hostBusy)
              $$fatal(1,"FRAME_ADMISSION_RESET_LOST_HELD_SOURCE");
          end
          if(currentEpoch==heldNative[63:0]) $$fatal(1,"FRAME_ADMISSION_RESET_EPOCH_NOT_ADVANCED");
          @(negedge serviceClock); #1; stopWorkClock=0;
          wait(admissions==beforeAdmissions+1); native_return();
          if(!mailboxFirst[1] || mailboxCount != 1) $$fatal(1,"FRAME_ADMISSION_EPOCH_NOT_CAPTURED");
          @(negedge serviceClock); #1; holdHostCommands=0; control_done();
          if(mode != 0 || admissions != beforeAdmissions+1 || dispatches != admissions)
            $$fatal(1,"FRAME_ADMISSION_RESET_REPLAY");
        """,monitors,serviceHalfPeriodNs=5.0e8/hz,maximumDelaySubtree=Some("i2c"),deadlineNs=3000000)
      }
      test(s"$name frame admission: both mailbox slots and simultaneous dequeue retain full wire payload at $hz Hz") {
        ClockedSimulation.run(fixture(hz),name+"-frame-admission-slots","""
          control_done(); holdHostCommands=1;
          // Every serial byte bit sees both polarities, including unused byte32.
          for(n=0;n<2;n=n+1) begin
            sendLength=33;
            for(j=0;j<33;j=j+1) sendBytes[j*8+:8]=(n==0 ? (8'h96 ^ j) : ~(8'h96 ^ j));
            send_frame(); native_return();
          end
          if(admissions!=2 || mailboxCount!=2 || firstCaptures!=1 || secondCaptures!=1)
            $fatal(1,"FRAME_ADMISSION_TWO_SLOT_COVERAGE");
          holdHostCommands=0; control_done();
          if(dispatches!=2 || mailboxCount!=0) $fatal(1,"FRAME_ADMISSION_TWO_SLOT_ORDER");
          // Leave one head queued, then arrange D and A on the same work edge.
          @(negedge serviceClock); #1; holdHostCommands=1; command(9); native_return();
          held_command(10);
          @(negedge serviceClock); #1; holdFrame=0; holdHostCommands=0;
          @(posedge observedWorkClock);
          if(!hostDispatched || !injectedAccepted) $fatal(1,"FRAME_ADMISSION_SIMULTANEOUS_EDGE_NOT_HIT");
          #1; native_return(); control_done();
          if(admissions!=4 || dispatches!=4 || simultaneous!=1 || mailboxCount!=0)
            $fatal(1,"FRAME_ADMISSION_SIMULTANEOUS_ORDER");
        """,monitors,serviceHalfPeriodNs=5.0e8/hz,maximumDelaySubtree=Some("i2c"),deadlineNs=5000000)
      }
    }
    test(s"$name frame admission: four native banks retain identity through two continuous reuse wraps") {
      ClockedSimulation.run(fixture(20000000),name+"-frame-admission-bank-reuse","""
        control_done();
        for(n=0;n<12;n=n+1) begin
          if(n%2==0) begin @(negedge serviceClock);#1;holdHostCommands=1;end
          // Distinct generations, with both logical slots occupied before D.
          sendLength=3;sendBytes=0;sendBytes[0+:8]=9;
          sendBytes[8+:8]=8'h96 ^ n;sendBytes[16+:8]=~(8'h96 ^ n);
          send_frame();native_return();
          if(n%2==1) begin
            if(mailboxCount!=2 || admissions!=n+1 || dispatches!=n-1)
              $fatal(1,"FRAME_ADMISSION_REUSE_TWO_SLOT_PRECONDITION");
            @(negedge serviceClock);#1;holdHostCommands=0;control_done();
          end
        end
        for(j=0;j<4;j=j+1) if(bankAdmissions[j]!=3)
          $fatal(1,"FRAME_ADMISSION_REUSE_BANK_COVERAGE");
        if(admissions!=12 || dispatches!=12 || mailboxCount || liveBanks || programmed || mode!=0)
          $fatal(1,"FRAME_ADMISSION_REUSE_ORDER_OR_EFFECT");
      """,monitors,serviceHalfPeriodNs=25,maximumDelaySubtree=Some("i2c"),deadlineNs=2000000)
    }
    test(s"$name frame admission: queued native epochs retain reset history after completed watchdog episodes") {
      ClockedSimulation.run(fixture(20000000),name+"-frame-admission-queued-epoch","""
        control_done();holdHostCommands=1;
        command(5);native_return();command(5);native_return();
        if(mailboxCount!=2 || admissions!=2 || dispatches || mailboxFirst[1] || mailboxSecond[1])
          $fatal(1,"FRAME_ADMISSION_QUEUED_EPOCH_PRECONDITION");
        for(n=0;n<3;n=n+1) begin
          @(negedge serviceClock);#1;applicationReset=1;
          repeat(12) @(negedge serviceClock);
          #1;applicationReset=0;repeat(20) @(negedge serviceClock);
          if(currentReset || mailboxCount!=2 || admissions!=2 || dispatches ||
             expectedNativeFirst[63:0]==currentEpoch || expectedNativeSecond[63:0]==currentEpoch)
            $fatal(1,"FRAME_ADMISSION_QUEUED_EPOCH_LOST");
        end
        #1;holdHostCommands=0;control_done();
        if(admissions!=2 || dispatches!=2 || mailboxCount || programmed || mode!=0)
          $fatal(1,"FRAME_ADMISSION_QUEUED_EPOCH_REPLAY");
      """,monitors,serviceHalfPeriodNs=25,maximumDelaySubtree=Some("i2c"),deadlineNs=1000000)
    }
    test(s"$name frame admission: a queued native head keeps its dispatch turn while its receipt is held") {
      ClockedSimulation.run(fixture(20000000),name+"-frame-admission-host-before-mmio","""
        control_done();holdSelectedHead=1;
        command(9);native_return();wait(observedHeadValid[0]);
        if(mailboxCount!=1 || admissions!=1 || dispatches || mmioDispatches)
          $fatal(1,"FRAME_ADMISSION_HELD_HEAD_PRECONDITION");
        @(negedge serviceClock);#1;
        request_bits_operation=1;request_bits_address=32'h30000004;
        request_bits_data=0;request_bits_mask=15;request_valid=1;response_ready=0;
        repeat(20) begin
          @(posedge observedWorkClock);
          if(hostDispatched || mmioDispatched || request_ready || response_valid ||
             mailboxCount!=1 || !observedHeadValid[0])
            $fatal(1,"FRAME_ADMISSION_MMIO_OVERTOOK_HELD_HOST");
        end
        @(negedge serviceClock);#1;holdSelectedHead=0;
        @(posedge observedWorkClock);while(!request_ready) @(posedge observedWorkClock);
        #1;request_valid=0;
        wait(response_valid);
        if(response_bits_error || dispatches!=1 || mmioDispatches!=1 || hostsBeforeMmio!=1)
          $fatal(1,"FRAME_ADMISSION_HOST_MMIO_ORDER_OR_RESPONSE");
        @(negedge serviceClock);response_ready=1;
        @(posedge observedWorkClock);#1;response_ready=0;control_done();
        if(admissions!=1 || dispatches!=1 || mailboxCount || liveBanks)
          $fatal(1,"FRAME_ADMISSION_HOST_MMIO_REPLAY");
      """,monitors,serviceHalfPeriodNs=25,maximumDelaySubtree=Some("i2c"),deadlineNs=1000000)
    }
    for(dequeue <- Seq(false,true); lateCopy <- Seq(false,true)) test(s"$name frame admission: full mailbox rejects native offer with simultaneous dequeue=$dequeue late copy=$lateCopy") {
      val error=intercept[IllegalArgumentException] {
        ClockedSimulation.run(fixture(20000000),name+"-frame-admission-overflow",s"""
          @(negedge serviceClock); while(!controlIdle) @(negedge serviceClock);
          #1; holdHostCommands=1;
          command(9); ${if(lateCopy) "wait(dut.fabric_hostFrames_count==1);" else ""} #5000;
          if(dut.fabric_hostFrames_count!=1) $$fatal(1,"FRAME_OVERFLOW_FIRST_SLOT_NOT_FILLED");
          command(10); ${if(lateCopy) "wait(dut.fabric_hostFrames_count==2);" else ""} #5000;
          if(dut.fabric_hostFrames_count!=2) $$fatal(1,"FRAME_OVERFLOW_SECOND_SLOT_NOT_FILLED");
          @(negedge serviceClock); #1; holdFrame=1;
          command(11); wait(receiptValid); @(negedge serviceClock); #1;
          holdFrame=0; holdHostCommands=${if(dequeue) 0 else 1}; #1;
          // The queue's full pre-edge state cannot acquire extra capacity from D.
          if(dut.fabric_hostFrames_count!=2 || !receiptValid || receiptReady!==${if(lateCopy) 0 else 1} ||
             injectedAccepted || hostDispatched!==${if(dequeue) 1 else 0})
            $$fatal(1,"FRAME_OVERFLOW_PREEDGE_NOT_EXERCISED");
          if(${if(lateCopy) 1 else 0} && copyAcknowledge===nativeRequest)
            $$fatal(1,"FRAME_OVERFLOW_COPY_STALL_NOT_EXERCISED");
          @(posedge observedWorkClock); #1;
          $$fatal(1,"FRAME_OVERFLOW_ASSERTION_MISSING");
        """,serviceHalfPeriodNs=25,maximumDelaySubtree=if(lateCopy) None else Some("i2c"),deadlineNs=1000000,
          primitiveDelayOverrides=if(lateCopy) slowCopy else Map.empty,powerOnResetNs=if(lateCopy) 20000 else 2000)
      }
      // Bind the expected failure to this fresh emitted assertion's actual fatal
      // line; unrelated failures or a matching diagnostic display do not count.
      val base="""Simulation failure: (.+)[/\\]simulation.log""".r.findFirstMatchIn(error.getMessage)
        .map(m=>Paths.get(m.group(1))).getOrElse(fail(error.getMessage))
      val rtl=base.resolve(if(click) "ClickFrameAdmissionFixture.sv" else "BdFrameAdmissionFixture.sv")
      val lines=Files.readAllLines(rtl).asScala.toVector
      val assertion=lines.indexWhere(_.contains("Assertion failed: CONTROL_HOST_MAILBOX_OVERFLOW"))
      assert(assertion>=0,"MISSING_EMITTED_MAILBOX_ASSERTION")
      val fatal=lines.indexWhere(_.contains("$fatal"),assertion)
      assert(fatal>assertion && fatal<=assertion+3,"MISSING_EMITTED_MAILBOX_FATAL")
      val log=Files.readString(base.resolve("simulation.log"))
      assert(log.contains("Assertion failed: CONTROL_HOST_MAILBOX_OVERFLOW"),log)
      assert(log.linesIterator.count(_.startsWith("FATAL:"))==1,log)
      assert(log.contains(s"FATAL: $rtl:${fatal+1}:"),log)
    }
    test(s"$name frame admission: real native frame captures on Stored command and reply edges") {
      ClockedSimulation.run(fixture(20000000),name+"-frame-admission-stored",s"""
        for(n=0;n<4;n=n+1) begin
          control_done();
          begin_image(4,0,32'h${crcValue.toHexString},32'h00010000); control_done();
          holdStored=1; holdStoredReply=1; put_word(0,32'h${word.toHexString});
          wait(storedWaiting); held_command(n<2 ? 2 : 3);
          // Native publication has settled; only the actual receipt is held.
          if(n%2==0) begin
            @(negedge serviceClock); #1; holdStored=0; holdFrame=0;
            @(posedge observedWorkClock);
            if(!storedAccepted || !injectedAccepted) $$fatal(1,"FRAME_ADMISSION_STORED_COMMAND_EDGE_NOT_HIT");
            #1; native_return(); wait(storedReplyWaiting);
            @(negedge serviceClock); #1; holdStoredReply=0;
          end else begin
            @(negedge serviceClock); #1; holdStored=0; wait(storedReplyWaiting);
            @(negedge serviceClock); #1; holdStoredReply=0; holdFrame=0;
            @(posedge observedWorkClock);
            if(!storedReplyAccepted || !injectedAccepted) $$fatal(1,"FRAME_ADMISSION_STORED_REPLY_EDGE_NOT_HIT");
            #1; native_return();
          end
          control_done();
          if(lastError !== 3 || programmed || received !== 4 || crc !== 32'h${(crcValue ^ 0xffffffffL).toHexString})
            $$fatal(1,"FRAME_ADMISSION_STORED_BUSY_HISTORY error=%d received=%d",lastError,received);
        end
        if(storedEdges!=2 || replyEdges!=2) $$fatal(1,"FRAME_ADMISSION_STORED_EDGE_COVERAGE");
      """,monitors,serviceHalfPeriodNs=25,maximumDelaySubtree=Some("i2c"),deadlineNs=10000000)
    }
  }
}
