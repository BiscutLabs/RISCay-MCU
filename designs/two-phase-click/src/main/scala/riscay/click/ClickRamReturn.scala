// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util.Cat
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ClickTiming,ModelTime}
import chiselasync.primitives.{PassiveDataAllowance,AsymmetricCElement,ControlGate,EventRegister,GateOperation,XorGate}
import riscay.soc.RamReturnResponse

/** POR word capture and publication, with independently reset native application
  * presentation. Each incoming phase has exactly one unconditional issue event;
  * cancelled words consume POR ownership without toggling application phase.
  * Digital timing assumptions require physical qualification.
  */
class ClickRamReturn(domain: ResetDomain) extends AsyncModule(domain) {
  val word=twoPhaseInput("word",UInt(32.W))
  val publication=twoPhaseOutput("publication",Bool())
  val captureRequest=IO(Output(Bool()));val captureAcknowledge=IO(Input(Bool()))
  val response=IO(new RamReturnResponse)
  val applicationReset=IO(Input(AsyncReset()));val eligible=IO(Input(Bool()))
  val presentationSettled=IO(Output(Bool()));val idle=IO(Output(Bool()))
  Seq(word,publication,response).foreach(dontTouch(_))
  private val timing=OwnerTiming.base
  private val cell=timing.controls.fire.model
  private val guard=ModelTime.ps(200000)
  private val resetRef=contract.endpoint("reset",reset)
  private val presentationReset=WireDefault((reset.asBool || applicationReset.asBool).asAsyncReset)
  dontTouch(presentationReset)
  private val presentationResetRef=contract.endpoint("presentation_reset",presentationReset)
  private def gate(id: String,op: GateOperation.Value,d: UInt,b: UInt=0.U,width: Int=1,
      delay: ModelTime=cell,initial: Int=0,application: Boolean=false): UInt = {
    if (Set("application_data_delay","data_delay","finish_data_delay","issue_data_delay","permission_data_delay","target_data_delay")(id)) {
      return PassiveDataAllowance(this,id,d,delay,resetRef)
    }
    val g=Module(new ControlGate(width,op,delay,initial));g.reset:= (if(application) presentationReset else reset)
    g.a:=d;g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),if(application) presentationResetRef else resetRef,
      "native RAM return selection and guarded capture/feedback; qualify complete paths")
    g.q
  }
  private def buffer(id: String,d: UInt,width: Int=1,delay: ModelTime=cell,application: Boolean=false): UInt =
    gate(id,GateOperation.Buffer,d,width=width,delay=delay,application=application)
  private def and(id: String,a: Bool,b: Bool): Bool =
    gate(id,GateOperation.Invert,gate(id+"_or",GateOperation.Or,
      gate(id+"_na",GateOperation.Invert,a.asUInt,initial=1),
      gate(id+"_nb",GateOperation.Invert,b.asUInt,initial=1),initial=1)).asBool
  private def xor(id: String,a: Bool,b: Bool): Bool = {
    val x=Module(new XorGate(cell));x.reset:=reset;x.a:=a;x.b:=b
    contract.primitive(id,x,Map("DELAY_FS"->BigInt(cell.fs)),resetRef,"independent native POR phase history")
    x.q
  }
  private def register(id: String,width: Int=1,application: Boolean=false): EventRegister = {
    val r=Module(new EventRegister(width,timing.payload.model));r.reset:= (if(application) presentationReset else reset)
    contract.primitive(id,r,Map("WIDTH"->BigInt(width),"DELAY_FS"->BigInt(timing.payload.model.fs),
      "RESET_VALUE"->BigInt(0)),if(application) presentationResetRef else resetRef,
      if(application) "application-reset permission/target/presentation only" else "retained POR word/phase; unaffected by application reset")
    r
  }
  private val received=register("received_phase")
  private val payload=register("payload",32)
  private val permission=register("permission",application=true)
  private val target=register("application_target",application=true)
  private val applicationPhase=register("application_phase",application=true)
  private val issued=register("issued_phase")
  private val completed=register("completed_phase")
  private val completedDelayed=WireDefault(buffer("acknowledge_guard",completed.q,delay=guard).asBool)
  private val pending=xor("owned",received.q.asBool,completedDelayed)
  private val terminal=Module(new AsymmetricCElement(1,3,0,cell));terminal.reset:=reset
  contract.primitive("terminal",terminal,Map("COMMON"->BigInt(1),"RISING"->BigInt(3),"FALLING"->BigInt(0),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,
    "retained presentation proof; reset/ACK withdrawal cannot truncate POR completion capture")
  private val capacity=Wire(Bool())
  private val incoming=xor("incoming",word.req,received.q.asBool)
  private val armSelected=and("arm_selected",incoming,capacity)
  private val armEvent=WireDefault(buffer("request_guard",armSelected.asUInt,delay=timing.requestDelay).asBool)
  private val inputSources=WireDefault(UInt(33.W),Cat(word.req,word.bits))
  private val inputData=WireDefault(UInt(33.W),buffer("data_delay",inputSources,width=33,delay=timing.data.model))
  private val permissionData=WireDefault(UInt(1.W),buffer("permission_data_delay",eligible.asUInt,delay=timing.data.model))
  private val targetSource=WireDefault(!applicationPhase.q.asBool)
  private val targetData=WireDefault(UInt(1.W),buffer("target_data_delay",targetSource.asUInt,delay=timing.data.model))
  received.trigger:=armEvent;received.d:=inputData(32)
  payload.trigger:=armEvent;payload.d:=inputData(31,0)
  permission.trigger:=armEvent;permission.d:=permissionData
  target.trigger:=armEvent;target.d:=targetData
  word.ack:=buffer("output_delay",received.q,delay=timing.acknowledgeDelay).asBool
  private val published=buffer("output_guard",received.q,delay=guard).asBool
  publication.req:=published;publication.bits:=payload.q(0)
  captureRequest:=published
  private val issuePending=xor("issue_pending",received.q.asBool,issued.q.asBool)
  private val issueEvent=WireDefault(buffer("request_delay",issuePending.asUInt,delay=guard).asBool)
  // Retain actual issue history: stale phase equality/permission immediately
  // after capture must never be mistaken for a cancelled new word.
  private val issueSeen=Module(new AsymmetricCElement(1,1,0,cell));issueSeen.reset:=reset
  issueSeen.common:=pending.asUInt;issueSeen.rising:=issueEvent.asUInt;issueSeen.falling:=0.U
  contract.primitive("issue_seen",issueSeen,Map("COMMON"->BigInt(1),"RISING"->BigInt(1),"FALLING"->BigInt(0),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,"retain actual unconditional issue before terminal proof")
  private val issueData=WireDefault(UInt(1.W),buffer("issue_data_delay",received.q,delay=timing.data.model))
  private val applicationSource=WireDefault(UInt(1.W),Mux(permission.q.asBool,target.q,applicationPhase.q))
  private val applicationData=WireDefault(UInt(1.W),buffer("application_data_delay",applicationSource,delay=timing.data.model))
  issued.trigger:=issueEvent;issued.d:=issueData
  applicationPhase.trigger:=issueEvent;applicationPhase.d:=applicationData
  response.req:=applicationPhase.q.asBool;response.bits.data:=payload.q;response.bits.error:=false.B
  private val accepted=permission.q.asBool && response.req === target.q.asBool && response.ack === target.q.asBool
  private val cancelled= !permission.q.asBool && response.req === response.ack
  terminal.common:=pending.asUInt;terminal.rising:=Cat(issueSeen.q && !issuePending,!issueEvent,accepted || cancelled)
  terminal.falling:=0.U
  private val publicationReturned=WireDefault(publication.req === received.q.asBool && publication.ack === received.q.asBool)
  private val receiptReturned=WireDefault(captureRequest === received.q.asBool && captureAcknowledge === received.q.asBool)
  private val finishSelected=and("finish_selected",terminal.q,
    and("branches_returned",publicationReturned,receiptReturned))
  private val finishEvent=WireDefault(buffer("return_guard",finishSelected.asUInt,delay=timing.requestDelay).asBool)
  private val finishData=WireDefault(UInt(1.W),buffer("finish_data_delay",received.q,delay=timing.data.model))
  completed.trigger:=finishEvent;completed.d:=finishData
  capacity:= !pending && received.q === issued.q && issued.q === completed.q &&
    completed.q.asBool === completedDelayed && !terminal.q && !issueSeen.q && !armEvent && !issueEvent && !finishEvent &&
    publicationReturned && receiptReturned && word.ack === received.q.asBool
  idle:=capacity && word.req === word.ack
  presentationSettled:= !pending || terminal.q
  val receivedValue=WireDefault(UInt(1.W),received.q);val issuedValue=WireDefault(UInt(1.W),issued.q)
  val completedValue=WireDefault(UInt(1.W),completed.q);val permissionValue=WireDefault(UInt(1.W),permission.q)
  val targetValue=WireDefault(UInt(1.W),target.q);val payloadValue=WireDefault(UInt(32.W),payload.q)
  val terminalValue=WireDefault(terminal.q)
  val captured=WireDefault(UInt(33.W),Cat(received.q,payload.q))
  Seq("capture_request"->captureRequest,"capture_acknowledge"->captureAcknowledge,"application_reset"->applicationReset,"eligible"->eligible,"response_request"->response.req,
    "response_acknowledge"->response.ack,"response_data"->response.bits,"presentation_settled"->presentationSettled,
    "idle"->idle,"capacity"->capacity,"arm_event"->armEvent,"input_sources"->inputSources,
    "input_data"->inputData,"captured"->captured,"permission_data"->permissionData,"word_permission"->permissionValue,
    "target_source"->targetSource,"target_data"->targetData,"target"->targetValue,
    "received"->receivedValue,"retained_word"->payloadValue,"issue_event"->issueEvent,"issue_data"->issueData,
    "issued_identity"->issuedValue,"application_source"->applicationSource,"application_data"->applicationData,
    "terminal_proof"->terminalValue,"finish_event"->finishEvent,"finish_data"->finishData,
    "completed"->completedValue,"cleanup"->completedDelayed,"publication_returned"->publicationReturned,
    "receipt_returned"->receiptReturned).foreach { case(id,value) => dontTouch(value);contract.endpoint(id,value) }
  private val dataTiming=BundledTiming.simulation(dataMax=timing.data.max).copy(dataDelay=timing.data)
  for((id,source,data,event,captured,delay) <- Seq(
      ("word","input_sources","input_data","arm_event","captured","data_delay"),
      ("permission","eligible","permission_data","arm_event","word_permission","permission_data_delay"),
      ("target","target_source","target_data","arm_event","target","target_data_delay"),
      ("issue","received","issue_data","issue_event","issued_identity","issue_data_delay"),
      ("application","application_source","application_data","issue_event","response_request","application_data_delay"),
      ("finish","received","finish_data","finish_event","completed","finish_data_delay"))) {
    contract.dataPathTiming(id+"_path",source,data,dataTiming,"native RAM return "+id+" capture",delayCell=delay)
    contract.setupHold(id+"_aperture",source,source,data,event,captured,timing.setup,timing.hold)
  }
  contract.capacity(1)
}
