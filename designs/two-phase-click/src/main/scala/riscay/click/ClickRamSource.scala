// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util.Cat
import chiselasync.bundled.ClickBuffer
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ClickTiming,ModelTime}
import chiselasync.primitives.{ControlGate,EventRegister,GateOperation,XorGate}

/** One native phase reservation, retained through committed publication or
  * uncommitted cancellation. Application reset never resets POR channel phases.
  */
class ClickRamSource(domain: ResetDomain) extends AsyncModule(domain) {
  val reserve=twoPhaseInput("reserve",Bool())
  val grant=twoPhaseOutput("grant",Bool())
  val decision=twoPhaseInput("decision",Bool())
  val publication=twoPhaseInput("publication",Bool())
  val wordDrained=IO(Input(Bool()))
  val applicationReset=IO(Input(AsyncReset()))
  val eligible=IO(Output(Bool())); val idle=IO(Output(Bool()))
  Seq(reserve,grant,decision,publication).foreach(dontTouch(_))
  private val timing=ClickTiming.Simulation
  private val cell=timing.controls.fire.model
  private val guard=ModelTime(timing.controls.inputPhase.max.fs+timing.requestDelay.fs+
    20*timing.controls.fire.max.fs+timing.clockSkew.fs+math.max(timing.hold.fs,timing.pulseLow.fs)+1)
  private val resetRef=contract.endpoint("reset",reset)
  private val eligibilityReset=WireDefault((reset.asBool || applicationReset.asBool).asAsyncReset)
  dontTouch(eligibilityReset)
  private val eligibilityResetRef=contract.endpoint("eligibility_reset",eligibilityReset)
  private def gate(id: String,op: GateOperation.Value,d: UInt,b: UInt=0.U,
      width: Int=1,delay: ModelTime=cell,initial: Int=0): UInt = {
    val g=Module(new ControlGate(width,op,delay,initial)); g.reset:=reset; g.a:=d; g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),resetRef,"native RAM source guard; qualify capture and phase feedback")
    g.q
  }
  private def buffer(id: String,d: UInt,width: Int=1,delay: ModelTime=cell): UInt =
    gate(id,GateOperation.Buffer,d,width=width,delay=delay)
  private def and(id: String,a: Bool,b: Bool): Bool = {
    val na=gate(id+"_na",GateOperation.Invert,a.asUInt,initial=1)
    val nb=gate(id+"_nb",GateOperation.Invert,b.asUInt,initial=1)
    gate(id,GateOperation.Invert,gate(id+"_or",GateOperation.Or,na,nb,initial=1)).asBool
  }
  private def phase(id: String): EventRegister = {
    val g=Module(new EventRegister(1,timing.controls.inputPhase.model)); g.reset:=reset
    contract.primitive(id,g,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(timing.controls.inputPhase.model.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"POR phase identity; capture and return without RTZ conversion"); g
  }
  private def xor(id: String,a: Bool,b: Bool): Bool = {
    val g=Module(new XorGate(cell)); g.reset:=reset; g.a:=a; g.b:=b
    contract.primitive(id,g,Map("DELAY_FS"->BigInt(cell.fs)),resetRef,"native source phase comparator"); g.q
  }
  private val reservation=asyncChild("reservation")(d => new ClickBuffer(Bool(),timing,d))
  reservation.in.req:=reserve.req; reservation.in.bits:=reserve.bits
  private val reserved=WireDefault(reservation.in.ack); dontTouch(reserved)
  private val armed=phase("armed_phase")
  private val armPending=xor("arm_pending",reservation.in.ack,armed.q.asBool)
  private val armEvent=WireDefault(buffer("request_guard",armPending.asUInt,delay=timing.requestDelay).asBool)
  private val armData=WireDefault(UInt(1.W),buffer("arm_data_delay",reservation.in.ack.asUInt,delay=timing.data.model))
  dontTouch(armData)
  armed.trigger:=armEvent; armed.d:=armData
  private val live=Module(new EventRegister(1,timing.payload.model)); live.reset:=eligibilityReset
  live.trigger:=armEvent; live.d:=1.U; eligible:=live.q.asBool
  contract.primitive("eligibility",live,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(timing.payload.model.fs),
    "RESET_VALUE"->BigInt(0)),eligibilityResetRef,
    "arm with POR reservation phase before grant; application reset cancels CPU eligibility only")
  grant.req:=buffer("output_guard",reservation.out.req.asUInt,delay=guard).asBool
  grant.bits:=reservation.out.bits; reservation.out.ack:=grant.ack
  private val retired=phase("retired_phase")
  private val decided=phase("decision_phase")
  private val published=phase("publication_phase")
  private val owned=xor("owned",reservation.in.ack,retired.q.asBool)
  // A commit changes the default cancel selector while its phase arrives. The
  // selection cone must settle before that phase can enable retirement: data
  // max + requestDelay + nine fire maxima + skew/hold = 111.2 ns, below guard.
  // Delay the incoming phase, not XOR feedback; decided.q must promptly remove
  // the capture event before the outward ACK permits reuse (<= 121.2 ns).
  private val decisionPhase=buffer("return_guard",decision.req.asUInt,delay=guard).asBool
  private val decisionPending=xor("decision_pending",decisionPhase,decided.q.asBool)
  private val publicationPending=xor("publication_pending",publication.req,published.q.asBool)
  private val ready=buffer("request_delay",Cat(owned,decisionPending,!decision.bits || publicationPending,
    wordDrained,grant.req === reservation.in.ack && grant.ack === reservation.in.ack,
    armed.q.asBool === reservation.in.ack),width=6,delay=timing.requestDelay)
  private val sourceReady=and("source_ready",ready(0),ready(1))
  private val effectReady=and("effect_ready",ready(2),ready(3))
  private val ownershipReady=and("ownership_ready",ready(4),ready(5))
  private val capture=WireDefault(and("retire_fire",and("settled",sourceReady,effectReady),ownershipReady))
  private val inputs=Cat(Mux(decision.bits,publication.req,published.q.asBool),decision.req,reservation.in.ack)
  private val data=WireDefault(UInt(3.W),buffer("data_delay",inputs,width=3,delay=timing.data.model))
  retired.trigger:=capture; retired.d:=data(0)
  decided.trigger:=capture; decided.d:=data(1)
  published.trigger:=capture; published.d:=data(2)
  private val captured=WireDefault(UInt(3.W),Cat(published.q,decided.q,retired.q))
  private val ack=buffer("acknowledge_guard",captured,width=3,delay=guard)
  reserve.ack:=ack(0); decision.ack:=ack(1); publication.ack:=ack(2)
  idle:=reserve.req === reserve.ack && reservation.in.ack === reserve.ack &&
    decision.req === decision.ack && publication.req === publication.ack &&
    grant.req === grant.ack && !capture && !armEvent
  contract.endpoint("application_reset",applicationReset)
  contract.endpoint("word_drained",wordDrained); contract.endpoint("eligible",eligible)
  contract.endpoint("idle",idle); contract.endpoint("reserved",reserved)
  contract.endpoint("arm_data",armData); contract.endpoint("arm_event",armEvent)
  val armedValue=WireDefault(UInt(1.W),armed.q); dontTouch(armedValue)
  contract.endpoint("armed",armedValue)
  contract.dataPathTiming("arm_path","reserved","arm_data",
    BundledTiming.simulation(dataMax=timing.data.max).copy(dataDelay=timing.data),
    "RAM reservation phase before eligibility arm",delayCell="arm_data_delay")
  contract.setupHold("arm_aperture","reserved","reserved","arm_data","arm_event","armed",timing.setup,timing.hold)
  contract.endpoint("retire_sources",Cat(decision.bits,publication.req,decision.req,reservation.in.ack,published.q))
  contract.endpoint("register_data",data); contract.endpoint("capture_event",capture)
  contract.endpoint("captured",captured)
  contract.dataPathTiming("retirement_path","retire_sources","register_data",
    BundledTiming.simulation(dataMax=timing.data.max).copy(dataDelay=timing.data),
    "RAM selected publication and reservation phase feedback before retirement")
  contract.setupHold("retirement_aperture","decision_request","decision_data","register_data",
    "capture_event","captured",timing.setup,timing.hold)
  contract.capacity(1)
}
