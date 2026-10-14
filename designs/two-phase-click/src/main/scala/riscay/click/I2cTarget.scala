// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation, PhaseRegister, XorGate}
import chiselasync.protocol.TwoPhase
import riscay.soc._

/** Explicit sampled-wire/timeout boundary. Protocol state and serialization
  * belong to the native child. The eight retained edge slots avoid a clocked
  * request/acknowledge round trip for every SCL edge.
  */
class I2cTarget(address: Int,idleCycles: Int,domain: ResetDomain) extends ClockedBridge(domain,2) {
  val scl=IO(Input(Bool())); val sda=IO(Input(Bool())); val pullLow=IO(Output(Bool()))
  val host=IO(new I2cHostPort)
  val frameAcceptEnable=IO(Input(Bool()))
  val snapshotAcceptEnable=IO(Input(Bool()))
  val native=asyncChild("native")(d => new ClickI2c(address,d))
  val frames=asyncChild("frame_bridge")(d => new ClickFrameReceipt(d))
  val frameStore=asyncChild("frame_store")(d => new ClickFrameStore(d))
  val frameHeads=Seq.tabulate(4)(i => asyncChild(s"frame_head${i}_bridge")(d => new ClickFrameReceipt(d)))
  val snapshots=asyncChild("snapshot_bridge")(d => new ClickServiceReplyReceipt(UInt(8.W), d))
  frames.clock:=clock; snapshots.clock:=clock
  frameHeads.foreach(_.clock:=clock)
  // Native copy and original clocked acceptance own independent ordinals.
  // The publisher retains its payload until both have acknowledged.
  frameStore.in.req:=native.frame.req; frameStore.in.bits:=native.frame.bits
  val frameSlot=withClockAndReset(clock,localReset) {
    val tail=RegInit(0.U(2.W)); when(frames.out.fire) { tail:=tail+1.U }; tail
  }
  host.frameSlot:=frameSlot
  for(i <- 0 until 4) {
    TwoPhase.connect(frameHeads(i).in,frameStore.banks(i))
    host.heads(i) <> frameHeads(i).out
    // Preserve the complete declared internal port ABI for strict export.
    dontTouch(host.heads(i).bits.ingress.resetActive)
    dontTouch(host.heads(i).bits.ingress.programBusy)
  }
  val frameAckJoin=Module(new AsymmetricCElement(2,0,0,ModelTime.ps(1000)))
  frameAckJoin.reset:=reset
  frameAckJoin.common:=Cat(frameStore.in.ack,frames.in.ack)
  frameAckJoin.rising:=1.U; frameAckJoin.falling:=0.U
  contract.primitive("frame_completion",frameAckJoin,Map("COMMON"->BigInt(2),"RISING"->BigInt(0),
    "FALLING"->BigInt(0),"DELAY_FS"->BigInt(1000000),"RESET_VALUE"->BigInt(0),
    "COMMON_INVERT"->BigInt(0),"RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),
    contract.endpoint("frame_completion_reset",reset),
    "join independently ordered native bank copy and original mailbox acceptance")
  frames.in.req:=native.frame.req; frames.in.bits:=native.frame.bits
  native.frame.ack:=frameAckJoin.q
  TwoPhase.connect(snapshots.in,native.snapshot)
  // Publish only after this POR-only service boundary has left reset.
  // Receipt ACK and mailbox enqueue share a real work-clock edge. A held frame
  // still contributes ungated busy/wake demand while the work gate is stopped.
  frames.out.ready:= !localReset.asBool && frameAcceptEnable
  // The receipt runs on service clock; its snapshot consumer uses work clock.
  // ACK is permitted only when that consumer will see this same rising edge.
  snapshots.out.ready:= !localReset.asBool && snapshotAcceptEnable
  host.frame.valid:=frames.out.fire; host.frame.bits:=frames.out.bits.ingress
  host.readStart:=snapshots.out.fire
  dontTouch(frames.out); dontTouch(snapshots.out)
  dontTouch(host.frame.bits.frame)
  native.start:= !localReset.asBool
  // Preserve a complete watchdog episode while a completed frame is queued.
  // Epoch state and every transport slot are POR-only; coincident assertion
  // belongs to the new epoch. Wrap is outside the supported lifetime.
  val resetEpoch=withClockAndReset(clock,localReset) {
    val epoch=RegInit(0.U(64.W)); val previous=RegNext(host.resetActive,false.B)
    val rising=host.resetActive && !previous
    when(rising) { assert(!epoch.andR,"I2C_RESET_EPOCH_WRAP"); epoch:=epoch+1.U }
    Mux(rising,epoch+1.U,epoch)
  }
  host.frame.bits.resetActive:=frames.out.bits.ingress.resetActive || host.resetActive ||
    frames.out.bits.resetEpoch =/= resetEpoch
  host.currentEpoch:=resetEpoch
  val frameStoreBusy=synchronizedControl(frameStore.busy)
  val headGray=withClockAndReset(clock,localReset) {
    val first=RegNext(native.observed.headGray,0.U); RegNext(first,0.U)
  }
  val active=synchronizedControl(native.observed.active)
  val selected=synchronizedControl(native.observed.active && !native.observed.addressByte && native.observed.ack)
  val rejectedLevel=synchronizedControl(native.observed.rejected)
  // Wake policy consumes a rejection event, not a retained level. A sticky
  // rejection must not cancel a later START while native START is in flight.
  val rejected=withClockAndReset(clock,localReset) {
    val previous=RegNext(rejectedLevel,false.B); rejectedLevel && !previous
  }
  val effects=synchronizedControl(native.frame.req =/= native.frame.ack || native.snapshot.req =/= native.snapshot.ack)
  pullLow:=native.observed.drive
  host.wordIndex:=((native.observed.sent +& 1.U) >> 2)(3,0)
  host.selected:=selected; host.rejected:=rejected
  withClockAndReset(clock,localReset) {
    val sclSync=RegInit(3.U(2.W)); sclSync:=Cat(sclSync(0),scl)
    val sdaSync=RegInit(3.U(2.W)); sdaSync:=Cat(sdaSync(0),sda)
    val lastScl=RegNext(sclSync(1),true.B); val lastSda=RegNext(sdaSync(1),true.B)
    val rise=sclSync(1) && !lastScl; val fall= !sclSync(1) && lastScl
    val start=sclSync(1) && lastScl && !sdaSync(1) && lastSda
    val stop=sclSync(1) && lastScl && sdaSync(1) && !lastSda
    val changed=sclSync(1) =/= lastScl || sdaSync(1) =/= lastSda
    val idle=RegInit(0.U(log2Ceil(idleCycles).W)); val expired=RegInit(false.B)
    val timeout=active && !changed && !expired && idle === (idleCycles-1).U
    // Measure inactivity from the sampled wire, without adding native state
    // publication latency to the configured abandonment interval.
    when(changed) { idle:=0.U; expired:=false.B }
      .elsewhen(timeout) { expired:=true.B }
      .elsewhen(idle =/= (idleCycles-1).U) { idle:=idle+1.U }
    when(!active) { expired:=false.B }
    val slots=RegInit(0.U.asTypeOf(Vec(8,new I2cEdge)))
    val tail=RegInit(0.U(4.W)); val tailGray=RegInit(0.U(4.W))
    // The extra pointer bit distinguishes a full ring from an empty ring.
    val full=tailGray === (headGray ^ "b1100".U)
    val event=rise || fall || start || stop || timeout
    when(event) {
      assert(!full,"I2C_EDGE_RING_OVERFLOW")
      val edge=Wire(new I2cEdge)
      edge.rise:=rise; edge.fall:=fall; edge.start:=start; edge.stop:=stop; edge.timeout:=timeout
      edge.sda:=sdaSync(1); edge.readWord:=host.readWord
      edge.resetEpoch:=resetEpoch
      edge.resetActive:=host.resetActive; edge.programBusy:=host.programBusy
      slots(tail(2,0)):=edge
      val next=tail+1.U; tail:=next; tailGray:=next ^ (next >> 1)
    }
    native.edges:=slots; native.tailGray:=tailGray
    // Inactive foreign payload edges must not sustain clock demand. START/STOP
    // pulse the existing seven-edge drain guard; an accepted transaction and
    // held effects retain demand independently of the ring occupancy.
    host.busy:=active || start || stop || effects || frames.out.valid || snapshots.out.valid || frameStoreBusy
    dontTouch(slots); dontTouch(tailGray)
  }
  contract.endpoint("frame_accept_enable",frameAcceptEnable)
  contract.endpoint("snapshot_accept_enable",snapshotAcceptEnable)
  contract.endpoint("reset",reset)
  private val wireInputs=WireDefault(UInt(2.W),Cat(scl,sda)); dontTouch(wireInputs)
  contract.endpoint("wire_inputs",wireInputs); contract.endpoint("pull_low",pullLow)
}
