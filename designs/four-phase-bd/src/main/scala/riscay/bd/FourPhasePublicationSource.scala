// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util.Cat
import chiselasync.bundled.LongHoldBuffer
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ModelTime}
import chiselasync.primitives.{AsymmetricCElement,ControlGate,EventRegister,GateOperation}
import riscay.soc.PublicationReservation

/** Exclusive service publication receipt; physical timing remains unqualified. */
class FourPhasePublicationSource(domain: ResetDomain) extends AsyncModule(domain) {
  val reserve=fourPhaseInput("reserve",new PublicationReservation)
  val grant=fourPhaseOutput("grant",new PublicationReservation)
  val decision=fourPhaseInput("decision",Bool())
  val publication=fourPhaseInput("publication",Bool())
  val drain=fourPhaseOutput("drain",new PublicationReservation)
  val applicationReset=IO(Input(AsyncReset()))
  val eligible=IO(Output(Bool())); val idle=IO(Output(Bool()))
  val ownerRecovery=IO(Output(Bool())); val recoveryDebt=IO(Output(Bool()))
  Seq(reserve,grant,decision,publication,drain).foreach(dontTouch(_))
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
      "RESET_VALUE"->BigInt(initial)),resetRef,"publication receipt control; qualify complete capture and return paths")
    g.q.asBool
  }
  private def state(id: String,rising: Int,falling: Int): AsymmetricCElement = {
    val g=Module(new AsymmetricCElement(1,rising,falling,cell)); g.reset:=reset
    contract.primitive(id,g,Map("COMMON"->BigInt(1),"RISING"->BigInt(rising),"FALLING"->BigInt(falling),
      "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
      "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,
      "POR receipt identity; full return before source reuse")
    g
  }
  private val reservation=asyncChild("reservation")(d => new LongHoldBuffer(new PublicationReservation,timing,d))
  reservation.in.req:=reserve.req; reservation.in.bits:=reserve.bits
  private val reserved=WireDefault(reservation.in.ack); dontTouch(reserved)
  private val live=Module(new EventRegister(1,cell)); live.reset:=eligibilityReset
  live.trigger:=reservation.in.ack; live.d:=1.U; eligible:=live.q.asBool
  contract.primitive("eligibility",live,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(cell.fs),
    "RESET_VALUE"->BigInt(0)),eligibilityResetRef,
    "application reset revokes eligibility but never POR receipts or accepted effects")
  grant.req:=gate("output_guard",GateOperation.Buffer,reservation.out.req,delay=guard)
  grant.bits:=reservation.out.bits; reservation.out.ack:=grant.ack
  ownerRecovery:=reservation.out.bits.recovery
  private val decisionReady=gate("request_guard",GateOperation.Buffer,decision.req,delay=guard)

  // The ACK fork directly sets seen. Even an immediate producer return takes
  // >=11 ns through request_delay plus >=1 ns through receipt_accept, exceeding
  // seen's 10 ns maximum. Physical fork/routing and pulse width remain open.
  private val seen=state("receipt_seen",1,0)
  private val receipt=state("receipt_accept",2,0)
  private val publicationReady=gate("request_delay",GateOperation.Buffer,publication.req,delay=timing.matchedDelay)
  receipt.common:=publicationReady.asUInt
  receipt.rising:=Cat(reservation.in.ack,!seen.q)
  receipt.falling:=0.U
  publication.ack:=receipt.q
  seen.common:=reserve.req.asUInt; seen.rising:=receipt.q.asUInt; seen.falling:=0.U

  // Hold the offer through reservation return. An early drain ACK cannot vanish
  // while grant return or another retirement prerequisite is still outstanding.
  private val issued=state("drain_issue",3,0)
  issued.common:=reserve.req.asUInt
  issued.rising:=Cat(reservation.in.ack,decisionReady,decision.bits)
  issued.falling:=0.U
  drain.req:=issued.q; drain.bits:=reservation.out.bits
  private val retirement=state("retirement",6,2)
  retirement.common:=reserve.req.asUInt
  retirement.rising:=Cat(reservation.in.ack,decisionReady,
    !decision.bits || (issued.q && drain.ack),
    !decision.bits || seen.q || !eligible,
    !publication.req && !publication.ack,
    !grant.req && !grant.ack)
  retirement.falling:=Cat(decision.req,publication.req)
  decision.ack:=retirement.q
  // decision.bits may return immediately at decision ACK. The retained drain
  // offer proves commitment, while seen proves an actual publication. Both and
  // the retained role survive until reserve.req falls, after the 200 ns guard.
  private val recoveryClear=state("recovery_clear",4,0)
  recoveryClear.common:=retirement.q.asUInt
  recoveryClear.rising:=Cat(ownerRecovery,issued.q,seen.q,eligible)
  recoveryClear.falling:=0.U
  private val debt=Module(new EventRegister(1,cell,1)); debt.reset:=eligibilityReset
  debt.trigger:=recoveryClear.q; debt.d:=0.U; recoveryDebt:=debt.q.asBool
  contract.primitive("debt_storage",debt,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(cell.fs),
    "RESET_VALUE"->BigInt(1)),eligibilityResetRef,
    "reset-dominant recovery debt; only fresh committed publication retirement clears it")
  private val returned=state("reservation_return",0,8)
  returned.common:=retirement.q.asUInt; returned.rising:=1.U
  returned.falling:=Cat(decision.ack,publication.req,publication.ack,
    reservation.in.ack,seen.q,drain.req,drain.ack,recoveryClear.q)
  reserve.ack:=gate("acknowledge_guard",GateOperation.Buffer,returned.q,delay=guard)
  idle:= !reserve.req && !reserve.ack && !decision.req && !decision.ack &&
    !publication.req && !publication.ack && !grant.req && !grant.ack &&
    !reservation.in.ack && !seen.q && !drain.req && !drain.ack && !recoveryClear.q
  contract.endpoint("application_reset",applicationReset)
  contract.endpoint("eligible",eligible); contract.endpoint("idle",idle)
  contract.endpoint("reserved",reserved)
  contract.endpoint("owner_recovery",ownerRecovery); contract.endpoint("recovery_debt",recoveryDebt)
  val recoveryEvent=WireDefault(recoveryClear.q); dontTouch(recoveryEvent)
  contract.endpoint("recovery_event",recoveryEvent)
  // Clear capture has constant D=0. Its C-element pulse is held through the
  // >=200 ns outward guard, versus <=10 ns clear and register cell delays.
  // The qualified application reset holds >=350 ns, beyond clear settlement;
  // a reset after capture reasserts debt without changing the POR receipt.
  contract.capacity(1)
}
