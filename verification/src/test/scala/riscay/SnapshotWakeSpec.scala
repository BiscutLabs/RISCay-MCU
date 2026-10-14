// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Production gate for wake cases; a falling-edge test gate only for the
  * explicit stopped-consumer contract test. Source clock continues there.
  */
class BdSnapshotWakeFixture(p: SocParameters, controlledGate: Boolean) extends riscay.bd.FourPhaseSoc(p) {
  val stopWork=IO(Input(Bool()))
  if(controlledGate) {
    val enabled=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(!stopWork,false.B) }
    workClock:=(serviceClock.asBool && enabled).asClock; fabric.io.clockRunning:=enabled
  }
  val observedWorkClock=IO(Output(Clock())); observedWorkClock:=workClock
  val workRunning=IO(Output(Bool())); workRunning:=fabric.io.clockRunning
  val accepted=IO(Output(Bool())); accepted:=host.host.readStart
  val receiptValid=IO(Output(Bool())); receiptValid:=BoringUtils.bore(host.snapshots.out.valid)
  val acknowledge=IO(Output(Bool())); acknowledge:=BoringUtils.bore(host.snapshots.in.ack)
  val nativeRequest=IO(Output(Bool())); nativeRequest:=BoringUtils.bore(host.snapshots.in.req)
  val token=IO(Output(UInt(8.W))); token:=BoringUtils.bore(host.snapshots.in.bits)
  val capturedWord=IO(Output(UInt(32.W))); capturedWord:=BoringUtils.bore(fabric.snapshot(0))
  val captureInput=IO(Output(UInt(32.W))); captureInput:=BoringUtils.bore(fabric.bank(0))
  val hostBusy=IO(Output(Bool())); hostBusy:=host.host.busy
  val nativeClick=IO(Output(Bool())); nativeClick:=false.B
}

class ClickSnapshotWakeFixture(p: SocParameters, controlledGate: Boolean) extends riscay.click.ClickSoc(p) {
  val stopWork=IO(Input(Bool()))
  if(controlledGate) {
    val enabled=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(!stopWork,false.B) }
    workClock:=(serviceClock.asBool && enabled).asClock; fabric.io.clockRunning:=enabled
  }
  val observedWorkClock=IO(Output(Clock())); observedWorkClock:=workClock
  val workRunning=IO(Output(Bool())); workRunning:=fabric.io.clockRunning
  val accepted=IO(Output(Bool())); accepted:=host.host.readStart
  val receiptValid=IO(Output(Bool())); receiptValid:=BoringUtils.bore(host.snapshots.out.valid)
  val acknowledge=IO(Output(Bool())); acknowledge:=BoringUtils.bore(host.snapshots.in.ack)
  val nativeRequest=IO(Output(Bool())); nativeRequest:=BoringUtils.bore(host.snapshots.in.req)
  val token=IO(Output(UInt(8.W))); token:=BoringUtils.bore(host.snapshots.in.bits)
  val capturedWord=IO(Output(UInt(32.W))); capturedWord:=BoringUtils.bore(fabric.snapshot(0))
  val captureInput=IO(Output(UInt(32.W))); captureInput:=BoringUtils.bore(fabric.bank(0))
  val hostBusy=IO(Output(Bool())); hostBusy:=host.host.busy
  val nativeClick=IO(Output(Bool())); nativeClick:=true.B
}

class SnapshotWakeSpec extends AnyFunSuite {
  private val config=McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"snapshot-wake",Vector.empty,Vector.empty))
  private val monitor="""
    integer captures=0,acks=0,sourceStops=0,beforeCaptures;
    realtime lastCapture=-1000;
    reg [31:0] sampledInput;
    reg [7:0] heldToken,value;
    reg heldAck,heldRequest;
    always @(posedge observedWorkClock) if(!reset && accepted) begin
      if(!workRunning || token!==8'h6b) $fatal(1,"SNAPSHOT_WAKE_CAPTURE_IDENTITY");
      sampledInput=captureInput; captures=captures+1;lastCapture=$realtime;
      #0.001;
      if(capturedWord!==sampledInput) $fatal(1,"SNAPSHOT_WAKE_STORAGE_NOT_CAPTURED");
    end
    always @(acknowledge) if(!reset && (nativeClick || acknowledge)) begin
      #0.002;
      if(acks>=captures || $realtime-lastCapture > 0.01)
        $fatal(1,"SNAPSHOT_WAKE_ACK_WITHOUT_WORK_CAPTURE");
      acks=acks+1;
    end
    task source_stopped; begin
      if(CHECK_SOURCE_STOP) begin
        wait(!serviceClockEnable); #250;
        if(serviceClockEnable || serviceClock!==0) $fatal(1,"SNAPSHOT_WAKE_SOURCE_NOT_STOPPED");
        sourceStops=sourceStops+1;
      end
    end endtask
    // Device ABI_VERSION is independently fixed at 0x00010000, little endian.
    task read_version; integer b; begin
      if(EXTERNAL_SOURCE && CHECK_SOURCE_STOP) wake_probe();
      start_bus(); write_byte(8'h6b);
      for(b=0;b<4;b=b+1) begin
        read_byte(value,b==3);
        if(value!==((32'h00010000 >> (8*b)) & 255)) $fatal(1,"SNAPSHOT_WAKE_ABI_READ");
      end
      stop_bus();
    end endtask
    task select_loader; begin
      if(EXTERNAL_SOURCE && CHECK_SOURCE_STOP) wake_probe();
      start_bus(); write_byte(8'h6a); write_byte(0); write_byte(1); write_byte(0); write_byte(0); stop_bus();
      wait(captureInput===0);
      if(capturedWord!==32'h00010000) $fatal(1,"SNAPSHOT_UPDATED_WITHOUT_READ");
    end endtask
    task read_mode; integer b; begin
      if(EXTERNAL_SOURCE && CHECK_SOURCE_STOP) wake_probe();
      start_bus(); write_byte(8'h6b);
      for(b=0;b<4;b=b+1) begin
        read_byte(value,b==3);
        if(value!==0) $fatal(1,"SNAPSHOT_WAKE_STALE_MODE_READ");
      end
      stop_bus();
    end endtask
  """
  for(click <- Seq(false,true); stopSource <- Seq(false,true); hz <- Seq(3200000,8000000,20000000); maximum <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name snapshot wake: source stop=$stopSource at $hz Hz maximum=$maximum captures on actual work edge") {
      val lp=LowPowerParameters.gf180Slow.copy(stopServiceClock=stopSource)
      val p=SocParameters(config,watchdogCycles=1000000,lowPower=Some(lp),serviceHz=hz)
      // The specified on-chip oscillator is 8..20 MHz. Exercise the slower
      // sampled-wire boundary using an external demand-following test source;
      // do not weaken the oscillator's real interface range to admit this case.
      val external=hz < 8000000
      val sourceModel=if(external) """
        always @(negedge serviceClockEnable) if(CHECK_SOURCE_STOP) begin
          if(serviceClock) @(negedge serviceClock);
          #0.001; clockEnabled=0;
        end
        always @(posedge serviceClockEnable) if(CHECK_SOURCE_STOP) begin
          #500; clockEnabled=1;
        end
      """ else ""
      def fixture: SocTop=if(click) new ClickSnapshotWakeFixture(p,false) else new BdSnapshotWakeFixture(p,false)
      ClockedSimulation.run(fixture,s"$name-snapshot-wake-$stopSource-$hz-$maximum", """
        wait(sleeping); source_stopped(); read_version();
        // A real SELECT changes bank(0) from ABI_VERSION to boot MODE. A
        // skipped second capture must not pass by reusing the first snapshot.
        select_loader(); wait(sleeping); source_stopped(); read_mode();
        wait(sleeping); #1000;
        if(captures!=2 || acks!=2 || programmed || locked || mode!=0 || (CHECK_SOURCE_STOP && sourceStops!=2))
          $fatal(1,"SNAPSHOT_WAKE_REPLAY_OR_BOOT_STATE");
      """,s"\nlocalparam CHECK_SOURCE_STOP=${if(stopSource) 1 else 0}; localparam EXTERNAL_SOURCE=${if(external) 1 else 0};\n"+
        monitor+(if(external || !stopSource) ClockedSimulation.wakeProbe else "")+sourceModel,
        onChipOscillator= !external,chipParameters=lp,serviceModelHz=hz,serviceHalfPeriodNs=5.0e8/hz,referenceHalfPeriodNs=100000,
        deadlineNs=5000000,maximumDelaySubtree=if(maximum) Some("i2c") else None)
    }
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name snapshot receipt holds native payload and ACK with consumer clock deliberately stopped") {
      val p=SocParameters(config,watchdogCycles=1000000,serviceHz=20000000)
      def fixture: SocTop=if(click) new ClickSnapshotWakeFixture(p,true) else new BdSnapshotWakeFixture(p,true)
      ClockedSimulation.run(fixture,name+"-snapshot-stopped-consumer", """
        // First capture gives the monitored storage a known architectural value.
        read_version(); #5000;
        select_loader();
        @(negedge serviceClock); #1; stopWork=1; wait(!workRunning);
        beforeCaptures=captures;
        start_bus(); write_byte(8'h6b); wait(receiptValid);
        heldToken=token;heldAck=acknowledge;heldRequest=nativeRequest;
        repeat(20) begin @(negedge serviceClock); #1;
          if(workRunning || accepted || !hostBusy || captures!=beforeCaptures ||
             token!==heldToken || acknowledge!==heldAck || nativeRequest!==heldRequest)
            $fatal(1,"SNAPSHOT_STOPPED_CONSUMER_RELEASED");
        end
        @(negedge serviceClock); #1; stopWork=0;
        wait(captures==beforeCaptures+1); #1000;
        read_byte(value,1); stop_bus(); #5000;
        if(value!==0 || captures!=2 || acks!=2) $fatal(1,"SNAPSHOT_STOPPED_CONSUMER_RECOVERY");
      ""","\nlocalparam CHECK_SOURCE_STOP=0; localparam EXTERNAL_SOURCE=0;\n"+monitor+ClockedSimulation.wakeProbe,serviceHalfPeriodNs=25,
        deadlineNs=3000000,maximumDelaySubtree=Some("i2c"))
    }
  }
}
