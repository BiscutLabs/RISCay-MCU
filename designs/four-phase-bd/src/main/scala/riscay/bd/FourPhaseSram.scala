// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.protocol.FourPhase
import riscay.soc._

/** One retained word, one byte crossing and one native sequencing token.
  * The macro clock stays at the physical boundary. All four byte completions,
  * including disabled lanes, return fully before reusing the byte channel.
  */
class FourPhaseSram(domain: ResetDomain, addressBits: Int = 32) extends AsyncModule(domain) {
  require(addressBits >= 2 && addressBits <= 32)
  val request = fourPhaseInput("request", new SramWordRequest)
  val response = fourPhaseOutput("response", UInt(32.W))
  val byteRequest = Seq(fourPhaseOutput("byte_request_0", new SramByteRequest))
  val byteResponse = Seq(fourPhaseInput("byte_response_0", UInt(8.W)))
  private val timing = OwnerTiming.base
  private val cell = ModelTime.ps(1000)
  private val resetRef = contract.endpoint("reset", reset)
  // A seeded control token plus a bubble. No payload circulates in this ring.
  private val idle=0; private val first=1; private val issue=2; private val capture=3
  private val advance=4; private val last=5; private val publish=6; private val retire=7
  private val owner=asyncChild("owner")(d => new FourPhaseFifo(UInt(3.W),1,timing,Seq(idle.U(3.W)),cell,d))
  private val lane=Module(new chiselasync.primitives.EventRegister(2,cell))
  private val state=owner.out.bits
  private val step=asyncChild("step")(d => new FourPhaseStage(UInt(4.W),UInt(3.W),
    (x: UInt) => MuxLookup(x(2,0),idle.U(3.W))(Seq(
      idle.U -> first.U, first.U -> capture.U, issue.U -> capture.U,
      capture.U -> Mux(x(3),last.U,advance.U), advance.U -> issue.U,
      last.U -> publish.U, publish.U -> retire.U, retire.U -> idle.U)),timing,d))
  private val available=MuxLookup(state,false.B)(Seq(
    idle.U -> request.req,
    first.U -> (byteRequest.head.ack && byteResponse.head.req),
    issue.U -> (byteRequest.head.ack && byteResponse.head.req),
    capture.U -> (!byteRequest.head.ack && !byteResponse.head.req),
    advance.U -> !byteResponse.head.ack, last.U -> !byteResponse.head.ack,
    publish.U -> response.ack, retire.U -> (!request.req && !response.ack)))
  step.in.bits:=Cat(lane.q === 3.U,state)
  step.in.req:=owner.out.req && available; owner.out.ack:=step.in.ack
  FourPhase.connect(owner.in,step.out)

  private class Word extends Bundle {
    val address=UInt((addressBits-2).max(1).W)
    val write=Bool(); val data=UInt(32.W); val mask=UInt(4.W)
  }
  private def register(id: String,width: Int): chiselasync.primitives.EventRegister = {
    val r=Module(new chiselasync.primitives.EventRegister(width,cell)); r.reset:=reset
    contract.primitive(id,r,Map("WIDTH"->BigInt(width),"DELAY_FS"->BigInt(cell.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"closed SRAM word-loop storage; POR only")
    r.trigger:=owner.out.req; r
  }
  private val wordType=new Word
  private val held=register("request_bank",wordType.getWidth)
  private val word=held.q.asTypeOf(wordType)
  private val incoming=Wire(new Word)
  incoming.address:= (if(addressBits>2) request.bits.address(addressBits-1,2) else 0.U)
  incoming.write:=request.bits.write; incoming.data:=request.bits.data; incoming.mask:=request.bits.mask
  private def allowance(id: String,data: UInt,width: Int,operands: UInt): UInt = {
    val source=WireDefault(UInt(operands.getWidth.W),operands)
    val transformed=WireDefault(UInt(width.W),data)
    val delayed=chiselasync.primitives.PassiveDataAllowance(this,id,transformed,timing.dataDelay.model,resetRef)
    contract.endpoint(id+"_source",source); contract.endpoint(id+"_data",delayed)
    contract.dataPathTiming(id+"_path",id+"_source",id+"_data",timing,
      "SRAM loop capture transform; physical alias, complete source/capture/return composition required",delayCell=id)
    delayed
  }
  held.d:=allowance("request_data_delay",Mux(state === first.U,incoming.asUInt,held.q),wordType.getWidth,Cat(state,request.bits.asUInt,held.q))
  lane.reset:=reset; lane.trigger:=owner.out.req
  lane.d:=allowance("lane_data_delay",Mux(state === first.U,0.U,Mux(state === issue.U,lane.q+1.U,lane.q)),2,Cat(state,lane.q))
  contract.primitive("lane",lane,Map("WIDTH"->BigInt(2),"DELAY_FS"->BigInt(cell.fs),
    "RESET_VALUE"->BigInt(0)),resetRef,"advance only after the old byte request/response complete return")
  private val assembly=register("assembly",32)
  private val bytes=Wire(Vec(4,UInt(8.W))); bytes:=assembly.q.asTypeOf(bytes)
  when(state === capture.U && !word.write) { bytes(lane.q):=byteResponse.head.bits }
  assembly.d:=allowance("assembly_data_delay",Mux(state === first.U,0.U,bytes.asUInt),32,Cat(state,word.write,lane.q,byteResponse.head.bits,assembly.q))

  // Closed history is the only external control source. Its capture event is
  // owner publication, never a transparent token's changing state decode.
  private val history=register("history",4)
  history.d:=allowance("history_data_delay",Cat(state === publish.U,state === capture.U,
    state === first.U || state === issue.U,state =/= idle.U),4,state)
  private val controls=Module(new chiselasync.primitives.ControlGate(4,
    chiselasync.primitives.GateOperation.Buffer,ModelTime.ps(32000)))
  controls.reset:=reset; controls.a:=history.q; controls.b:=0.U
  contract.primitive("output_guard",controls,Map("WIDTH"->BigInt(4),"OP"->BigInt(0),
    "DELAY_FS"->BigInt(32000000),"RESET_VALUE"->BigInt(0)),resetRef,
    "relative capture-to-ACK and request/data publication; size this owner's actual paths at each corner")
  request.ack:=controls.q(0); byteRequest.head.req:=controls.q(1)
  byteResponse.head.ack:=controls.q(2); response.req:=controls.q(3)
  private val byteData=Wire(new SramByteRequest)
  byteData.address:=Cat(word.address,lane.q).pad(32)
  byteData.write:=word.write
  byteData.data:=(word.data >> (lane.q << 3))(7,0)
  byteData.enable:= !word.write || word.mask(lane.q)
  // This is a retained-source bus into a qualified clocked receipt, not a
  // native capture allowance. The receipt's valid/fire proof owns its use.
  byteRequest.head.bits:=byteData
  contract.endpoint("byte_data",byteRequest.head.bits)
  response.bits:=assembly.q
  Seq("publication_event"->owner.out.req,"state"->state,"retained_request"->held.q,
    "lane_value"->lane.q,"assembled_word"->assembly.q,"history_value"->history.q,
    "guarded_controls"->controls.q).foreach { case(id,value) => dontTouch(value);contract.endpoint(id,value) }
  contract.endpoint("loop_launch",step.out.req)
  contract.endpoint("request_offer",request.req); contract.endpoint("byte_offer",byteResponse.head.req)
  for((id,launch,captured) <- Seq(("request","request_offer","retained_request"),
      ("lane","loop_launch","lane_value"),("assembly","byte_offer","assembled_word"),
      ("history","loop_launch","history_value"))) {
    contract.setupHold(id+"_aperture",launch,id+"_data_delay_source",id+"_data_delay_data",
      "publication_event",captured,ModelTime.ps(100),ModelTime.ps(100))
  }
  contract.capacity(1)
}

/** Explicit word admission/publication and per-byte macro crossings. The
  * service clock tracks admission and drainage; lane sequencing and read
  * assembly live in the native child.
  */
class SramAccess(domain: ResetDomain) extends ClockedBridge(domain, 2) {
  val io = IO(Flipped(new SramAccessPort(1)))
  // Services uses busy for admission and always accepts the final reply. Keep
  // the complete crossing ABI even when those ports are constant.
  dontTouch(io)
  val native = asyncChild("native")(d => new FourPhaseSram(d))

  val command = asyncChild("command_bridge")(d => new DecoupledToFourPhase(new SramWordRequest, 2, d))
  val reply = asyncChild("reply_bridge")(d => new FourPhaseServiceReplyReceipt(UInt(32.W), d))
  command.clock := clock; reply.clock := clock
  FourPhase.connect(native.request, command.out); FourPhase.connect(reply.in, native.response)
  val requests = (0 until 1).map(i => asyncChild(s"byte_request_$i")(d => new FourPhaseRetainedReceipt(new SramByteRequest, d)))
  val replies = (0 until 1).map(i => asyncChild(s"byte_reply_$i")(d => new DecoupledToFourPhase(UInt(8.W), 2, d)))
  for(i <- 0 until 1) {
    requests(i).clock := clock; replies(i).clock := clock
    FourPhase.connect(requests(i).in, native.byteRequest(i)); FourPhase.connect(native.byteResponse(i), replies(i).out)
    io.bytes(i) <> requests(i).out; replies(i).in <> io.completions(i)
  }
  private val returned = synchronizedControl(!reply.in.req) && !reply.in.ack
  private val bytesReturned = requests.map(b => synchronizedControl(!b.in.req) && !b.in.ack).reduce(_ && _)
  withClockAndReset(clock, localReset) {
    val active = RegInit(false.B)
    val drained = returned && bytesReturned && command.in.ready && replies.map(_.in.ready).reduce(_ && _)
    command.in.valid := io.request.valid && !active && drained
    command.in.bits := io.request.bits; io.request.ready := !active && drained
    when(command.in.fire) { active := true.B }
    io.response.valid := reply.out.valid && active; io.response.bits := reply.out.bits
    reply.out.ready := io.response.ready && active
    when(io.response.fire) { active := false.B }
    io.busy := active || !drained || localReset.asBool
  }
  contract.endpoint("reset", reset)
}
