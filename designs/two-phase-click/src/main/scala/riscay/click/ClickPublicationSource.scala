// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util.Cat
import chiselasync.bundled.ClickBuffer
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ClickTiming,ModelTime}
import chiselasync.primitives.{ControlGate,EventRegister,GateOperation,XorGate}

/** Native exclusive publication receipt; physical timing remains unqualified. */
class ClickPublicationSource(domain: ResetDomain) extends AsyncModule(domain) {
  val reserve=twoPhaseInput("reserve",Bool())
  val grant=twoPhaseOutput("grant",Bool())
  val decision=twoPhaseInput("decision",Bool())
  val publication=twoPhaseInput("publication",Bool())
  val drain=twoPhaseOutput("drain",Bool())
  val applicationReset=IO(Input(AsyncReset()))
  val eligible=IO(Output(Bool())); val idle=IO(Output(Bool()))
  Seq(reserve,grant,decision,publication,drain).foreach(dontTouch(_))
  private val timing=ClickTiming.Simulation
  private val cell=timing.controls.fire.model
  private val guard=ModelTime(timing.controls.inputPhase.max.fs+timing.requestDelay.fs+
    22*timing.controls.fire.max.fs+timing.clockSkew.fs+math.max(timing.hold.fs,timing.pulseLow.fs)+1)
  private val resetRef=contract.endpoint("reset",reset)
  private val eligibilityReset=WireDefault((reset.asBool || applicationReset.asBool).asAsyncReset)
  dontTouch(eligibilityReset)
  private val eligibilityResetRef=contract.endpoint("eligibility_reset",eligibilityReset)
  private def gate(id: String,op: GateOperation.Value,d: UInt,b: UInt=0.U,
      width: Int=1,delay: ModelTime=cell,initial: Int=0): UInt = {
    val g=Module(new ControlGate(width,op,delay,initial)); g.reset:=reset; g.a:=d; g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),resetRef,"native publication receipt; qualify capture, selection and feedback")
    g.q
  }
  private def buffer(id: String,d: UInt,width: Int=1,delay: ModelTime=cell): UInt =
    gate(id,GateOperation.Buffer,d,width=width,delay=delay)
  private def and(id: String,a: Bool,b: Bool): Bool = {
    val na=gate(id+"_na",GateOperation.Invert,a.asUInt,initial=1)
    val nb=gate(id+"_nb",GateOperation.Invert,b.asUInt,initial=1)
    gate(id,GateOperation.Invert,gate(id+"_or",GateOperation.Or,na,nb,initial=1)).asBool
  }
  private def phase(id: String,width: Int=1): EventRegister = {
    val g=Module(new EventRegister(width,timing.controls.inputPhase.model)); g.reset:=reset
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"DELAY_FS"->BigInt(timing.controls.inputPhase.model.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"POR phase identity; native independent publication and drain histories")
    g
  }
  private def xor(id: String,a: Bool,b: Bool): Bool = {
    val g=Module(new XorGate(cell)); g.reset:=reset; g.a:=a; g.b:=b
    contract.primitive(id,g,Map("DELAY_FS"->BigInt(cell.fs)),resetRef,"native source phase comparator"); g.q
  }
  private val reservation=asyncChild("reservation")(d => new ClickBuffer(Bool(),timing,d))
  reservation.in.req:=reserve.req; reservation.in.bits:=reserve.bits
  private val reserved=WireDefault(reservation.in.ack); dontTouch(reserved)
  private val published=phase("publication_phase")
  private val issued=phase("drain_phase")
  private val armed=phase("armed_phase",3)
  private val publicationTarget=armed.q(1); private val drainTarget=armed.q(2)
  private val armPending=xor("arm_pending",reservation.in.ack,armed.q(0))
  private val armEvent=WireDefault(buffer("request_guard",armPending.asUInt,delay=timing.requestDelay).asBool)
  private val armSources=WireDefault(UInt(3.W),Cat(!issued.q.asBool,!published.q.asBool,reservation.in.ack))
  private val armData=WireDefault(UInt(3.W),buffer("arm_data_delay",armSources,width=3,delay=timing.data.model))
  dontTouch(armSources); dontTouch(armData)
  armed.trigger:=armEvent; armed.d:=armData
  private val live=Module(new EventRegister(1,timing.payload.model)); live.reset:=eligibilityReset
  live.trigger:=armEvent; live.d:=1.U; eligible:=live.q.asBool
  contract.primitive("eligibility",live,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(timing.payload.model.fs),
    "RESET_VALUE"->BigInt(0)),eligibilityResetRef,
    "arm before grant; application reset revokes CPU eligibility without changing POR receipt history")
  grant.req:=buffer("output_guard",reservation.out.req.asUInt,delay=guard).asBool
  grant.bits:=reservation.out.bits; reservation.out.ack:=grant.ack
  private val retired=phase("retired_phase"); private val decided=phase("decision_phase")
  private val owned=xor("owned",reservation.in.ack,retired.q.asBool)
  private val armMatches=armed.q(0) === reservation.in.ack
  private val decisionPhase=buffer("return_guard",decision.req.asUInt,delay=guard).asBool
  private val decisionPending=xor("decision_pending",decisionPhase,decided.q.asBool)

  // Publication ACK comes from retained capture, independently of retirement.
  // Each slot may consume its immutable target once, including after reset.
  private val publicationPhase=buffer("request_delay",publication.req.asUInt,delay=timing.requestDelay).asBool
  private val publicationPending=xor("publication_pending",publicationPhase,published.q.asBool)
  private val publicationUnused=xor("publication_unused",publicationTarget,published.q.asBool)
  private val publicationFire=WireDefault(and("publication_fire",
    and("publication_owner",owned,armMatches),
    and("publication_committed",and("publication_selected",publicationPending,publicationUnused),
      and("publication_decision",decisionPending,decision.bits))))
  private val publicationData=WireDefault(UInt(1.W),buffer("publication_data_delay",publication.req.asUInt,delay=timing.data.model))
  published.trigger:=publicationFire; published.d:=publicationData

  // No eligibility gate here: every committed decision must issue its drain,
  // even if reset erased a staged Telemetry commit before service dispatch.
  private val drainUnused=xor("drain_unused",drainTarget,issued.q.asBool)
  private val drainFire=WireDefault(and("drain_fire",and("drain_owner",owned,armMatches),
    and("drain_selected",and("drain_decision",decisionPending,decision.bits),drainUnused)))
  private val drainData=WireDefault(UInt(1.W),buffer("drain_data_delay",drainTarget.asUInt,delay=timing.data.model))
  issued.trigger:=drainFire; issued.d:=drainData
  drain.req:=issued.q.asBool; drain.bits:=reservation.out.bits
  private val drained=issued.q.asBool === drainTarget && drain.ack === drainTarget
  private val seen=published.q.asBool === publicationTarget
  private val ready=Cat(owned,armMatches,decisionPending,
    !decision.bits || drained,!decision.bits || seen || !eligible,
    publication.req === publication.ack,
    grant.req === reservation.in.ack && grant.ack === reservation.in.ack,
    !publicationFire && !drainFire)
  private val capture=WireDefault(and("retire_fire",
    and("retire_left",and("retire_source",ready(0),ready(1)),and("retire_effect",ready(2),ready(3))),
    and("retire_right",and("retire_decision",ready(4),ready(5)),and("retire_owner",ready(6),ready(7)))))
  private val retirementSources=WireDefault(UInt(2.W),Cat(decision.req,reservation.in.ack))
  private val data=WireDefault(UInt(2.W),buffer("data_delay",retirementSources,width=2,delay=timing.data.model))
  retired.trigger:=capture; retired.d:=data(0); decided.trigger:=capture; decided.d:=data(1)
  private val captured=WireDefault(UInt(2.W),Cat(decided.q,retired.q))
  private val acknowledged=buffer("acknowledge_guard",Cat(published.q,captured),width=3,delay=guard)
  reserve.ack:=acknowledged(0); decision.ack:=acknowledged(1); publication.ack:=acknowledged(2)
  idle:=reserve.req === reserve.ack && reservation.in.ack === reserve.ack &&
    decision.req === decision.ack && publication.req === publication.ack &&
    grant.req === grant.ack && drain.req === drain.ack &&
    !capture && !armEvent && !publicationFire && !drainFire

  // Balanced capture trees have at most three 3-cell AND levels. Including a
  // phase cell, comparator and 11 ns guard gives <=121.2 ns feedback settlement;
  // the 241.200001 ns outward/decision guards exceed that digital envelope.
  // Recheck selector and capture pulse bounds with independent min/max skew.
  // No physical timing closure is implied by these simulation values.
  contract.endpoint("application_reset",applicationReset)
  contract.endpoint("eligible",eligible); contract.endpoint("idle",idle); contract.endpoint("reserved",reserved)
  val armedValue=WireDefault(UInt(3.W),armed.q); dontTouch(armedValue)
  val publishedValue=WireDefault(UInt(1.W),published.q); dontTouch(publishedValue)
  val issuedValue=WireDefault(UInt(1.W),issued.q); dontTouch(issuedValue)
  Seq("arm_sources"->armSources,"arm_data"->armData,"arm_event"->armEvent,"armed"->armedValue,
    "publication_phase_data"->publicationData,"publication_event"->publicationFire,"publication_captured"->publishedValue,
    "drain_target"->drainTarget,"drain_phase_data"->drainData,"drain_event"->drainFire,"drain_issued"->issuedValue,
    "retirement_sources"->retirementSources,"register_data"->data,"capture_event"->capture,"captured"->captured)
    .foreach { case(id,value) => contract.endpoint(id,value) }
  private val dataTiming=BundledTiming.simulation(dataMax=timing.data.max).copy(dataDelay=timing.data)
  contract.dataPathTiming("arm_path","arm_sources","arm_data",dataTiming,
    "publication source reservation and independent next targets",delayCell="arm_data_delay")
  contract.setupHold("arm_aperture","reserved","arm_sources","arm_data","arm_event","armed",timing.setup,timing.hold)
  contract.dataPathTiming("publication_path","publication_request","publication_phase_data",dataTiming,
    "independent publication phase capture",delayCell="publication_data_delay")
  contract.setupHold("publication_aperture","publication_request","publication_request","publication_phase_data",
    "publication_event","publication_captured",timing.setup,timing.hold)
  contract.dataPathTiming("drain_path","drain_target","drain_phase_data",dataTiming,
    "committed drain target before issue",delayCell="drain_data_delay")
  contract.setupHold("drain_aperture","decision_request","decision_data","drain_phase_data",
    "drain_event","drain_issued",timing.setup,timing.hold)
  contract.dataPathTiming("retirement_path","retirement_sources","register_data",dataTiming,
    "publication source retirement phase feedback")
  contract.setupHold("retirement_aperture","decision_request","decision_data","register_data",
    "capture_event","captured",timing.setup,timing.hold)
  contract.capacity(1)
}
