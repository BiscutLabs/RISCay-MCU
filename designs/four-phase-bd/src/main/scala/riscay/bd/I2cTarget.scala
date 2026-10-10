// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation, PhaseRegister, XorGate}
import chiselasync.protocol.FourPhase
import riscay.soc._

/** Explicit sampled-wire/timeout boundary. Protocol state and serialization
  * belong to the native child. The eight retained edge slots avoid a clocked
  * request/acknowledge round trip for every SCL edge.
  */
class I2cTarget(address: Int,idleCycles: Int,domain: ResetDomain) extends ClockedBridge(domain,2) {
  val scl=IO(Input(Bool())); val sda=IO(Input(Bool())); val pullLow=IO(Output(Bool()))
  val host=IO(new I2cHostPort)
  val native=asyncChild("native")(d => new FourPhaseI2c(address,d))
  val frames=asyncChild("frame_bridge")(d => new FourPhaseToDecoupled(new I2cFrame,2,d))
  val snapshots=asyncChild("snapshot_bridge")(d => new FourPhaseToDecoupled(UInt(8.W),2,d))
  frames.clock:=clock; snapshots.clock:=clock
  FourPhase.connect(frames.in,native.frame); FourPhase.connect(snapshots.in,native.snapshot)
  // Publish only after this POR-only service boundary has left reset.
  frames.out.ready:= !localReset.asBool; snapshots.out.ready:= !localReset.asBool
  host.frame.valid:=frames.out.fire; host.frame.bits:=frames.out.bits.ingress
  host.readStart:=snapshots.out.fire
  dontTouch(frames.out); dontTouch(snapshots.out)

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
  val effects=synchronizedControl(native.frame.req || native.frame.ack || native.snapshot.req || native.snapshot.ack)
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
    host.busy:=active || start || stop || effects || frames.out.valid || snapshots.out.valid
    dontTouch(slots); dontTouch(tailGray)
  }
  contract.endpoint("reset",reset)
  private val wireInputs=WireDefault(UInt(2.W),Cat(scl,sda)); dontTouch(wireInputs)
  contract.endpoint("wire_inputs",wireInputs); contract.endpoint("pull_low",pullLow)
}
