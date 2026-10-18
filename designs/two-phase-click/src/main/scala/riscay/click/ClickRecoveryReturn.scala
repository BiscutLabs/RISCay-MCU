// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ClickTiming,ModelTime}
import chiselasync.primitives.{PassiveDataAllowance,ControlGate,EventRegister,GateOperation,XorGate}

/** Native phase proof transport and input exclusion, with independent history.
  * No four-phase conversion. Digital bounds still need physical qualification.
  */
class ClickRecoveryReturn(domain: ResetDomain) extends AsyncModule(domain) {
  val requested=IO(Input(Bool()));val admitted=IO(Output(Bool()))
  val originalReturned=IO(Input(Bool()));val fresh=IO(Input(Bool()))
  val eligible=IO(Input(Bool()))
  val finalRequest=IO(Output(Bool()));val finalAcknowledge=IO(Input(Bool()))
  val clear=IO(Output(Bool()));val quiet=IO(Output(Bool()))
  val admitting=IO(Output(Bool()))
  private val timing=OwnerTiming.base
  private val cell=timing.controls.fire.model
  private val cleanup=ModelTime.ps(200000)
  private val resetRef=contract.endpoint("reset",reset)
  private def gate(id: String,op: GateOperation.Value,a: Bool,b: Bool=false.B,
      delay: ModelTime=cell,initial: Int=0): Bool = {
    if (Set("target_data_delay","issue_data_delay","complete_data_delay","admission_data_delay")(id)) {
      return PassiveDataAllowance(this,id,a,delay,resetRef)
    }
    val g=Module(new ControlGate(1,op,delay,initial));g.reset:=reset;g.a:=a;g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(1),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),resetRef,"native phase proof selection and feedback; qualify complete paths")
    g.q.asBool
  }
  private def buffer(id: String,a: Bool,delay: ModelTime=cell): Bool = gate(id,GateOperation.Buffer,a,delay=delay)
  private def and(id: String,a: Bool,b: Bool): Bool =
    gate(id,GateOperation.Invert,gate(id+"_or",GateOperation.Or,
      gate(id+"_na",GateOperation.Invert,a,initial=1),
      gate(id+"_nb",GateOperation.Invert,b,initial=1),initial=1))
  private def xor(id: String,a: Bool,b: Bool): Bool = {
    val x=Module(new XorGate(cell));x.reset:=reset;x.a:=a;x.b:=b
    contract.primitive(id,x,Map("DELAY_FS"->BigInt(cell.fs)),resetRef,"independent native proof phase comparison")
    x.q
  }
  private def phase(id: String): EventRegister = {
    val r=Module(new EventRegister(1,timing.controls.inputPhase.model));r.reset:=reset
    contract.primitive(id,r,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(timing.controls.inputPhase.model.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"POR retained phase; never reset by application reset")
    r
  }
  private val accepted=phase("admitted_phase")
  private val target=phase("target_phase")
  private val issued=phase("issued_phase")
  private val completed=phase("completed_phase")
  private val completedDelayed=WireDefault(buffer("acknowledge_guard",completed.q.asBool,cleanup))
  private val nextTarget=WireDefault(!target.q.asBool)
  private val targetData=WireDefault(buffer("target_data_delay",nextTarget,timing.data.model))
  target.trigger:=fresh;target.d:=targetData.asUInt
  private val issuePending=xor("issue_pending",target.q.asBool,issued.q.asBool)
  private val issueSelected=and("issue_selected",issuePending,originalReturned)
  private val issueEvent=WireDefault(buffer("request_delay",issueSelected,timing.requestDelay))
  private val issueData=WireDefault(buffer("issue_data_delay",target.q.asBool,timing.data.model))
  issued.trigger:=issueEvent;issued.d:=issueData.asUInt;finalRequest:=issued.q.asBool
  private val completePending=xor("complete_pending",issued.q.asBool,completedDelayed)
  private val wireReturned=WireDefault(finalRequest === target.q.asBool && finalAcknowledge === target.q.asBool)
  private val completeSelected=and("complete_selected",completePending,
    and("complete_wire",wireReturned,and("complete_source",originalReturned,!issueEvent)))
  private val completeEvent=WireDefault(buffer("return_guard",completeSelected,timing.requestDelay))
  private val completeData=WireDefault(buffer("complete_data_delay",issued.q.asBool,timing.data.model))
  completed.trigger:=completeEvent;completed.d:=completeData.asUInt
  clear:=and("clear",completeEvent,eligible)
  quiet:= !fresh && target.q === issued.q && issued.q === completed.q &&
    completed.q.asBool === completedDelayed && finalAcknowledge === finalRequest &&
    !issueEvent && !completeEvent && !clear
  private val capacity=WireDefault(originalReturned && quiet)
  private val admissionPending=xor("admission_pending",requested,accepted.q.asBool)
  private val admissionSelected=and("admission_selected",admissionPending,capacity)
  admitting:=buffer("request_guard",admissionSelected,timing.requestDelay)
  private val admissionData=WireDefault(buffer("admission_data_delay",requested,timing.data.model))
  accepted.trigger:=admitting;accepted.d:=admissionData.asUInt;admitted:=accepted.q.asBool
  // Admission event does not inhibit itself: phase/slot feedback terminates it.
  // Its setup >=15 ns exceeds 10 ns data + .1 ns setup. Minimum pulse >=15 ns,
  // including the faster capacity-withdrawal path, exceeds each 10 ns cell.
  // Completed-phase feedback is held 200 ns, so clear's <=30 ns path and <=10 ns
  // debt capture settle before cleanup. A POR tail cannot rearm eligibility.
  Seq(completedDelayed,nextTarget,targetData,issueEvent,issueData,wireReturned,
    completeEvent,completeData,capacity,admissionData).foreach(dontTouch(_))
  Seq("requested"->requested,"admitted"->admitted,"original_returned"->originalReturned,
    "fresh"->fresh,"eligible"->eligible,"final_request"->finalRequest,
    "final_acknowledge"->finalAcknowledge,"clear_event"->clear,"quiet"->quiet,"admitting"->admitting,
    "capacity"->capacity,"target_sources"->nextTarget,"target_data"->targetData,
    "issue_event"->issueEvent,"issue_data"->issueData,"wire_returned"->wireReturned,
    "complete_event"->completeEvent,"complete_data"->completeData,
    "admission_data"->admissionData,"cleanup"->completedDelayed).foreach {
      case(id,value) => contract.endpoint(id,value)
    }
  val targetValue=WireDefault(target.q.asBool);val issuedValue=WireDefault(issued.q.asBool)
  val completedValue=WireDefault(completed.q.asBool)
  Seq(targetValue,issuedValue,completedValue).foreach(dontTouch(_))
  contract.endpoint("target",targetValue);contract.endpoint("issued",issuedValue);contract.endpoint("completed",completedValue)
  private val dataTiming=BundledTiming.simulation(dataMax=timing.data.max).copy(dataDelay=timing.data)
  for((id,source,data,event,captured,delay) <- Seq(
      ("target","target_sources","target_data","fresh","target","target_data_delay"),
      ("issue","target","issue_data","issue_event","issued","issue_data_delay"),
      ("complete","issued","complete_data","complete_event","completed","complete_data_delay"),
      ("admission","requested","admission_data","admitting","admitted","admission_data_delay"))) {
    contract.dataPathTiming(id+"_path",source,data,dataTiming,"recovery return "+id+" phase data",delayCell=delay)
    contract.setupHold(id+"_aperture",source,source,data,event,captured,timing.setup,timing.hold)
  }
  contract.capacity(1)
}
