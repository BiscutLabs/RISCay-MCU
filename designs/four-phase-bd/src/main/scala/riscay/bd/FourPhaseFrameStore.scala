// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled.LongHoldBuffer
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.primitives.{ControlGate, EventRegister, GateOperation}
import chiselasync.protocol.FourPhase
import riscay.soc.I2cFrame

/** Local binding of the library's pinned atomic AND primitive. */
private class FrameRouteAnd(delay: ModelTime)
    extends ExtModule(Map("INPUTS" -> IntParam(2), "DELAY_FS" -> IntParam(delay.fs), "INVERT" -> IntParam(0))) {
  override def desiredName = "ChiselAsyncAnd_v1"
  val reset=IO(Input(AsyncReset())); val d=IO(Input(UInt(2.W))); val q=IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncAnd_v1.sv")
}

/** Four physical payload banks; logical admission still has exactly two credits.
  * The caller observes the original offer independently and acknowledges it at A.
  * This borrowed copy must complete before A (>=100 ns after O at 20 MHz).
  * slot is prequalified before O and advances at A. The native route capture
  * keeps that old tag through the source's entire four-phase return.
  * All delays are digital bounds, not physical timing qualification.
  */
class FourPhaseFrameStore(domain: ResetDomain) extends AsyncModule(domain) {
  val in=fourPhaseInput("in",new I2cFrame)
  val slot=IO(Input(UInt(2.W)))
  val banks=Seq.tabulate(4)(i => fourPhaseOutput(s"bank$i",new I2cFrame))
  val available=IO(Output(Vec(4,Bool())))
  dontTouch(available)
  val busy=IO(Output(Bool()))
  private val resetRef=contract.endpoint("reset",reset)
  private val cell=ModelTime.ps(1000)
  private def gate(id: String, data: UInt, width: Int, delay: ModelTime): UInt = {
    val g=Module(new ControlGate(width,GateOperation.Buffer,delay)); g.reset:=reset; g.a:=data; g.b:=0.U
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(0),
      "DELAY_FS"->BigInt(delay.fs),"RESET_VALUE"->BigInt(0)),resetRef,
      "frame-bank route/return digital bound; complete physical path unqualified")
    g.q
  }
  private val tag=Module(new EventRegister(2,cell)); tag.reset:=reset
  contract.primitive("route",tag,Map("WIDTH"->BigInt(2),"DELAY_FS"->BigInt(cell.fs),
    "RESET_VALUE"->BigInt(0)),resetRef,"capture original O tag; retain through source RTZ")
  private val tagData=gate("data_delay",slot,2,ModelTime.ps(10000))
  private val tagCapture=gate("request_delay",in.req.asUInt,1,ModelTime.ps(11000)).asBool
  tag.d:=tagData; tag.trigger:=tagCapture
  // Route Q <=21 ns, decode <=31 ns. The preserved 32 ns request guard
  // leaves >=1 ns before the atomic route gate; bank capture/ACK <=83 ns.
  private val selection=gate("route_decode",UIntToOH(tag.q,4),4,cell)
  private val offered=gate("request_guard",in.req.asUInt,1,ModelTime.ps(32000)).asBool
  private val storage=Seq.tabulate(4)(i => asyncChild(s"storage$i")(d =>
    new LongHoldBuffer(new I2cFrame,BundledTiming.Simulation,d)))
  private val idleBanks=Wire(Vec(4,Bool()))
  private val settledBanks=gate("return_guard",idleBanks.asUInt,4,ModelTime.ps(32000))
  for(i <- 0 until 4) {
    val route=Module(new FrameRouteAnd(cell)); route.reset:=reset; route.d:=Cat(selection(i),offered)
    contract.primitive(s"route$i",route,Map("INPUTS"->BigInt(2),"DELAY_FS"->BigInt(cell.fs),
      "INVERT"->BigInt(0)),resetRef,"atomic qualified route; selection retained through RTZ")
    storage(i).in.req:=route.q; storage(i).in.bits:=in.bits
    FourPhase.connect(banks(i),storage(i).out)
    idleBanks(i):= !storage(i).in.req && !storage(i).in.ack && !banks(i).req && !banks(i).ack
    // Include the final internal b/long-hold feedback after external RTZ.
    available(i):=settledBanks(i) && idleBanks(i)
  }
  in.ack:=MuxLookup(tag.q,false.B)(storage.indices.map(i => i.U -> storage(i).in.ack))
  busy:=in.req || in.ack || !available.asUInt.andR
  // Local aliases preserve source identity in the exported probe ABI.
  private val routeDataProbe=WireDefault(UInt(2.W),tagData)
  private val routeValueProbe=WireDefault(UInt(2.W),tag.q)
  Seq(routeDataProbe,routeValueProbe).foreach(dontTouch(_))
  contract.endpoint("slot",slot); contract.endpoint("available",available)
  contract.endpoint("busy",busy); contract.endpoint("route_data",routeDataProbe)
  contract.endpoint("route_capture",tagCapture); contract.endpoint("route_value",routeValueProbe)
  contract.dataPathTiming("route_path","slot","route_data",BundledTiming.Simulation,
    "temporary slot to retained native route; 10 ns complete data budget")
  contract.setupHold("route_aperture","in_request","slot","route_data","route_capture","route_value",
    ModelTime.ps(100),ModelTime.ps(100))
  contract.capacity(4)
}
