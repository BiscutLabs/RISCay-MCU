// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util.Cat
import chiselasync.bundled.LongHoldBuffer
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ModelTime}
import chiselasync.primitives.{AsymmetricCElement,ControlGate,EventRegister,GateOperation}

/** Exclusive POR RAM reservation. Application reset removes reply eligibility,
  * never accepted memory effects or the reservation's handshake identity.
  * The boundary must cancel queued/uncommitted reservations after every reset.
  */
class FourPhaseRamSource(domain: ResetDomain) extends AsyncModule(domain) {
  val reserve=fourPhaseInput("reserve",Bool()) // Operation's write bit.
  val grant=fourPhaseOutput("grant",Bool())
  val decision=fourPhaseInput("decision",Bool()) // Committed, otherwise cancelled.
  val publication=fourPhaseInput("publication",Bool())
  val wordDrained=IO(Input(Bool()))
  val applicationReset=IO(Input(AsyncReset()))
  val eligible=IO(Output(Bool())); val idle=IO(Output(Bool()))
  Seq(reserve,grant,decision,publication).foreach(dontTouch(_))
  private val timing=BundledTiming.Simulation
  private val cell=ModelTime.ps(1000)
  private val guard=ModelTime.ps(200000)
  private val resetRef=contract.endpoint("reset",reset)
  private val eligibilityReset=WireDefault((reset.asBool || applicationReset.asBool).asAsyncReset)
  dontTouch(eligibilityReset)
  private val eligibilityResetRef=contract.endpoint("eligibility_reset",eligibilityReset)
  private def gate(id: String,op: GateOperation.Value,a: Bool,b: Bool=false.B,
      delay: ModelTime=cell,initial: Int=0): Bool = {
    val g=Module(new ControlGate(1,op,delay,initial)); g.reset:=reset; g.a:=a.asUInt; g.b:=b.asUInt
    contract.primitive(id,g,Map("WIDTH"->BigInt(1),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),resetRef,"RAM reservation control; qualify complete capture and return paths")
    g.q.asBool
  }
  private def and(id: String,a: Bool,b: Bool): Bool = {
    val na=gate(id+"_na",GateOperation.Invert,a,initial=1)
    val nb=gate(id+"_nb",GateOperation.Invert,b,initial=1)
    gate(id,GateOperation.Invert,gate(id+"_or",GateOperation.Or,na,nb,initial=1))
  }
  private def state(id: String,rising: Int,falling: Int): AsymmetricCElement = {
    val g=Module(new AsymmetricCElement(1,rising,falling,cell)); g.reset:=reset
    contract.primitive(id,g,Map("COMMON"->BigInt(1),"RISING"->BigInt(rising),"FALLING"->BigInt(falling),
      "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
      "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,
      "exclusive reservation; return every selected receipt before source reuse")
    g
  }
  private val reservation=asyncChild("reservation")(d => new LongHoldBuffer(Bool(),timing,d))
  reservation.in.req:=reserve.req; reservation.in.bits:=reserve.bits
  private val reserved=WireDefault(reservation.in.ack); dontTouch(reserved)
  // Do not acknowledge the external reservation when this buffer captures it.
  // Keeping reserve.req high prevents a second reservation until retirement.
  private val live=Module(new EventRegister(1,cell)); live.reset:=eligibilityReset
  live.trigger:=reservation.in.ack; live.d:=1.U; eligible:=live.q.asBool
  contract.primitive("eligibility",live,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(cell.fs),
    "RESET_VALUE"->BigInt(0)),eligibilityResetRef,
    "arm before grant; application reset cancels eligibility without resetting POR ownership")
  grant.req:=gate("output_guard",GateOperation.Buffer,reservation.out.req,delay=guard)
  grant.bits:=reservation.out.bits; reservation.out.ack:=grant.ack
  private val decisionReady=gate("request_guard",GateOperation.Buffer,decision.req,delay=timing.matchedDelay)
  private val retirement=state("retirement",5,2)
  retirement.common:=reserve.req.asUInt
  retirement.rising:=Cat(reservation.in.ack,decisionReady,!decision.bits || publication.req,
    wordDrained,!grant.req && !grant.ack)
  retirement.falling:=Cat(decision.req,decision.bits && publication.req)
  decision.ack:=retirement.q
  publication.ack:=and("publication_ack",retirement.q,decision.bits)
  private val returned=state("reservation_return",0,3)
  returned.common:=retirement.q.asUInt; returned.rising:=1.U
  returned.falling:=Cat(decision.ack,publication.ack,reservation.in.ack)
  reserve.ack:=gate("acknowledge_guard",GateOperation.Buffer,returned.q,delay=guard)
  idle:= !reserve.req && !reserve.ack && !decision.req && !decision.ack &&
    !publication.req && !publication.ack && !grant.req && !grant.ack && !reservation.in.ack
  contract.endpoint("application_reset",applicationReset)
  contract.endpoint("word_drained",wordDrained); contract.endpoint("eligible",eligible)
  contract.endpoint("idle",idle); contract.endpoint("reserved",reserved)
  contract.capacity(1)
}
