// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Retains the production CPU, work gate and source-wake implementation. */
class BdFrameWakeFixture(p: SocParameters) extends riscay.bd.FourPhaseSoc(p) {
  val holdFrame=IO(Input(Bool()))
  host.frameAcceptEnable:=fabric.io.clockRunning && !holdFrame
  val observedWorkClock=IO(Output(Clock())); observedWorkClock:=workClock
  val workRunning=IO(Output(Bool())); workRunning:=fabric.io.clockRunning
  val frameAccepted=IO(Output(Bool())); frameAccepted:=fabric.io.hostFrameAccepted
  val frameDispatched=IO(Output(Bool()))
  frameDispatched:=fabric.io.controlCommand.fire && fabric.io.controlCommand.bits.kind === ControlKind.Host.U
  val frameOpcode=IO(Output(UInt(8.W))); frameOpcode:=host.host.frame.bits.frame.bytes(0)
  val dispatchedOpcode=IO(Output(UInt(8.W))); dispatchedOpcode:=fabric.io.controlCommand.bits.frame.bytes(0)
  val receiptValid=IO(Output(Bool())); receiptValid:=BoringUtils.bore(host.frames.out.valid)
  val nativeAcknowledge=IO(Output(Bool())); nativeAcknowledge:=BoringUtils.bore(host.native.frame.ack)
  val nativeRequest=IO(Output(Bool())); nativeRequest:=BoringUtils.bore(host.native.frame.req)
  val receiptAcknowledge=IO(Output(Bool())); receiptAcknowledge:=BoringUtils.bore(host.frames.in.ack)
  val copyAcknowledge=IO(Output(Bool())); copyAcknowledge:=BoringUtils.bore(host.frameStore.in.ack)
  val observedNativeFrame=IO(Output(UInt(337.W))); observedNativeFrame:=BoringUtils.bore(host.native.frame.bits).asUInt
  val hostBusy=IO(Output(Bool())); hostBusy:=host.host.busy
  val nativeClick=IO(Output(Bool())); nativeClick:=false.B
}

/** Retains the production CPU, work gate and source-wake implementation. */
class ClickFrameWakeFixture(p: SocParameters) extends riscay.click.ClickSoc(p) {
  val holdFrame=IO(Input(Bool()))
  host.frameAcceptEnable:=fabric.io.clockRunning && !holdFrame
  val observedWorkClock=IO(Output(Clock())); observedWorkClock:=workClock
  val workRunning=IO(Output(Bool())); workRunning:=fabric.io.clockRunning
  val frameAccepted=IO(Output(Bool())); frameAccepted:=fabric.io.hostFrameAccepted
  val frameDispatched=IO(Output(Bool()))
  frameDispatched:=fabric.io.controlCommand.fire && fabric.io.controlCommand.bits.kind === ControlKind.Host.U
  val frameOpcode=IO(Output(UInt(8.W))); frameOpcode:=host.host.frame.bits.frame.bytes(0)
  val dispatchedOpcode=IO(Output(UInt(8.W))); dispatchedOpcode:=fabric.io.controlCommand.bits.frame.bytes(0)
  val receiptValid=IO(Output(Bool())); receiptValid:=BoringUtils.bore(host.frames.out.valid)
  val nativeAcknowledge=IO(Output(Bool())); nativeAcknowledge:=BoringUtils.bore(host.native.frame.ack)
  val nativeRequest=IO(Output(Bool())); nativeRequest:=BoringUtils.bore(host.native.frame.req)
  val receiptAcknowledge=IO(Output(Bool())); receiptAcknowledge:=BoringUtils.bore(host.frames.in.ack)
  val copyAcknowledge=IO(Output(Bool())); copyAcknowledge:=BoringUtils.bore(host.frameStore.in.ack)
  val observedNativeFrame=IO(Output(UInt(337.W))); observedNativeFrame:=BoringUtils.bore(host.native.frame.bits).asUInt
  val hostBusy=IO(Output(Bool())); hostBusy:=host.host.busy
  val nativeClick=IO(Output(Bool())); nativeClick:=true.B
}

class FrameWakeSpec extends AnyFunSuite {
  private val config=McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"frame-wake",Vector.empty,Vector.empty))
  private val monitor="""
    integer accepted=0,dispatched=0,beforeAccepted,beforeDispatched,sourceStops=0,joinedAcks=0;
    realtime lastAccepted=-1000;
    reg [336:0] heldFrame;
    reg heldAck;
    always @(posedge observedWorkClock) if(!reset) begin
      if(frameAccepted) begin
        if(!workRunning || frameOpcode!==9) $fatal(1,"FRAME_WAKE_CAPTURE_IDENTITY");
        accepted=accepted+1;lastAccepted=$realtime;
      end
      if(frameDispatched) begin
        if(dispatchedOpcode!==9) $fatal(1,"FRAME_WAKE_DISPATCH_IDENTITY");
        dispatched=dispatched+1;
      end
    end
    always @(receiptAcknowledge) if(!reset && (nativeClick || receiptAcknowledge)) begin
      #0.001;
      if($realtime-lastAccepted > 0.01) $fatal(1,"FRAME_WAKE_ACK_WITHOUT_WORK_CAPTURE");
    end
    // The receipt ACK remains tied to the actual work edge. The publisher ACK
    // now follows the native completion join (1..10 ns digital cell envelope).
    always @(nativeAcknowledge) if(!reset && (nativeClick || nativeAcknowledge)) begin
      #0.001;
      if(joinedAcks>=accepted || $realtime-lastAccepted > 10.01 ||
         receiptAcknowledge!==nativeAcknowledge || copyAcknowledge!==nativeAcknowledge)
        $fatal(1,"FRAME_WAKE_PUBLISHER_ACK_WITHOUT_BOTH_CONSUMERS");
      joinedAcks=joinedAcks+1;
    end
    always @(sleeping) if(!reset && serviceClock !== 0) $fatal(1,"FRAME_WAKE_GATE_CHANGED_HIGH");
    task source_stopped; begin
      if(CHECK_SOURCE_STOP) begin
        wait(!serviceClockEnable); #250;
        if(serviceClockEnable || serviceClock !== 0) $fatal(1,"FRAME_WAKE_SOURCE_DID_NOT_STOP");
        sourceStops=sourceStops+1;
      end
    end endtask
  """
  for(click <- Seq(false,true); stopSource <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name frame admission: production retained gate and source stop=$stopSource preserve wake and exact capture") {
      val lp=LowPowerParameters.gf180Slow.copy(stopServiceClock=stopSource)
      val p=SocParameters(config,watchdogCycles=1000000,lowPower=Some(lp),serviceHz=8000000)
      def fixture: SocTop=if(click) new ClickFrameWakeFixture(p) else new BdFrameWakeFixture(p)
      ClockedSimulation.run(fixture,name+"-frame-wake", """
        wait(sleeping); source_stopped();
        // The helper issues the documented harmless wake probe when the
        // production source-stopping configuration needs oscillator startup.
        command(9); #5000;
        if(accepted!=1 || dispatched!=1) $fatal(1,"FRAME_WAKE_SHORTEST_WRITE_LOST");
        wait(sleeping); beforeAccepted=accepted;beforeDispatched=dispatched;
        holdFrame=1; command(9); wait(receiptValid);
        heldFrame=observedNativeFrame;heldAck=nativeAcknowledge;
        repeat(20) begin
          @(negedge serviceClock); #1;
          if(!hostBusy || !workRunning || !serviceClockEnable || nativeAcknowledge!==heldAck ||
             observedNativeFrame!==heldFrame || accepted!=beforeAccepted)
            $fatal(1,"FRAME_WAKE_HELD_NATIVE_DEMAND_LOST");
        end
        @(negedge serviceClock); #1;holdFrame=0;
        wait(accepted==beforeAccepted+1 && dispatched==beforeDispatched+1);
        wait(sleeping); source_stopped();
        #1000;
        if(accepted!=2 || dispatched!=2 || programmed || locked || mode!=0 || (CHECK_SOURCE_STOP && sourceStops!=2))
          $fatal(1,"FRAME_WAKE_REPLAY_OR_BOOT_STATE");
      """,s"\nlocalparam CHECK_SOURCE_STOP=${if(stopSource) 1 else 0};\n"+monitor,onChipOscillator=true,chipParameters=lp,
        serviceModelHz=8000000,serviceHalfPeriodNs=62.5,referenceHalfPeriodNs=100000,
        deadlineNs=5000000)
    }
  }
}
