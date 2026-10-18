// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util.Cat
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ClickTiming,ModelTime}
import chiselasync.primitives.{PassiveDataAllowance,AsymmetricCElement,ControlGate,EventRegister,GateOperation}
import riscay.soc.RamReturnResponse

/** Native four-phase retained word and independently returning branches.
  * POR capture acknowledges the SRAM word independently of publication. Only
  * application presentation is cancelled by application reset. All four-phase
  * branches return independently before ownership is released.
  */
class FourPhaseRamReturn(domain: ResetDomain) extends AsyncModule(domain) {
  val word=fourPhaseInput("word",UInt(32.W))
  val publication=fourPhaseOutput("publication",Bool())
  val captureRequest=IO(Output(Bool()));val captureAcknowledge=IO(Input(Bool()))
  val response=IO(new RamReturnResponse)
  val applicationReset=IO(Input(AsyncReset()));val eligible=IO(Input(Bool()))
  val presentationSettled=IO(Output(Bool()));val idle=IO(Output(Bool()))
  Seq(word,publication,response).foreach(dontTouch(_))
  private val timing=OwnerTiming.base
  private val cell=ModelTime.ps(1000)
  private val guard=ModelTime.ps(200000)
  private val resetRef=contract.endpoint("reset",reset)
  private val presentationReset=WireDefault((reset.asBool || applicationReset.asBool).asAsyncReset)
  dontTouch(presentationReset)
  private val presentationResetRef=contract.endpoint("presentation_reset",presentationReset)
  private def gate(id: String,op: GateOperation.Value,d: UInt,b: UInt=0.U,width: Int=1,
      delay: ModelTime=cell,initial: Int=0,application: Boolean=false): UInt = {
    if (Set("data_delay","permission_data_delay")(id)) {
      return PassiveDataAllowance(this,id,d,delay,resetRef)
    }
    val g=Module(new ControlGate(width,op,delay,initial));g.reset:= (if(application) presentationReset else reset)
    g.a:=d;g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),if(application) presentationResetRef else resetRef,
      "native RAM return offer/withdrawal and capture feedback; qualify complete paths")
    g.q
  }
  private def buffer(id: String,d: UInt,width: Int=1,delay: ModelTime=cell,application: Boolean=false): UInt =
    gate(id,GateOperation.Buffer,d,width=width,delay=delay,application=application)
  private def and(id: String,a: Bool,b: Bool,application: Boolean=false): Bool =
    gate(id,GateOperation.Invert,gate(id+"_or",GateOperation.Or,
      gate(id+"_na",GateOperation.Invert,a.asUInt,initial=1,application=application),
      gate(id+"_nb",GateOperation.Invert,b.asUInt,initial=1,application=application),
      initial=1,application=application),application=application).asBool
  private def state(id: String,rising: Int,commonInvert: Int=0,application: Boolean=false): AsymmetricCElement = {
    val c=Module(new AsymmetricCElement(1,rising,0,cell,commonInvert=commonInvert))
    c.reset:= (if(application) presentationReset else reset);c.falling:=0.U
    contract.primitive(id,c,Map("COMMON"->BigInt(1),"RISING"->BigInt(rising),"FALLING"->BigInt(0),
      "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(commonInvert),
      "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),
      if(application) presentationResetRef else resetRef,"retained native acceptance/withdrawal/return proof")
    c
  }
  private def register(id: String,width: Int=1,application: Boolean=false): EventRegister = {
    val r=Module(new EventRegister(width,cell));r.reset:= (if(application) presentationReset else reset)
    contract.primitive(id,r,Map("WIDTH"->BigInt(width),"DELAY_FS"->BigInt(cell.fs),
      "RESET_VALUE"->BigInt(0)),if(application) presentationResetRef else resetRef,
      if(application) "per-word application-reset permission" else "POR retained word; input may change after capture acknowledgment")
    r
  }
  private val pending=state("pending",2,commonInvert=1)
  private val released=state("released",4)
  private val cleanup=WireDefault(buffer("acknowledge_guard",released.q.asUInt,delay=guard).asBool)
  private val capacity=Wire(Bool())
  private val inputRequest=buffer("request_guard",word.req.asUInt,delay=timing.matchedDelay).asBool
  pending.common:=cleanup.asUInt;pending.rising:=Cat(inputRequest,capacity)
  private val armEvent=WireDefault(pending.q)
  private val inputData=WireDefault(UInt(32.W),buffer("data_delay",word.bits,width=32,delay=timing.dataDelay.model))
  private val payload=register("payload",32);payload.trigger:=armEvent;payload.d:=inputData
  private val permissionData=WireDefault(UInt(1.W),buffer("permission_data_delay",eligible.asUInt,
    delay=timing.dataDelay.model))
  private val permission=register("permission",application=true)
  permission.trigger:=armEvent;permission.d:=permissionData
  // A fastest producer can offer the next REQ immediately after ACK falls.
  // Retain old REQ withdrawal before lowering ACK; old return then depends on
  // that history and actual ACK low, never on a possibly newer request level.
  private val armed=buffer("output_guard",pending.q.asUInt,delay=guard).asBool
  private val historyCommon=gate("history_common",GateOperation.Or,pending.q.asUInt,armed.asUInt).asBool
  private val issued=state("issued",1);issued.common:=pending.q.asUInt;issued.rising:=armed.asUInt
  private val inputSeen=state("input_seen",1)
  private val inputWithdrawn=state("input_withdrawn",2)
  private val inputReturned=state("input_returned",2)
  inputSeen.common:=historyCommon.asUInt;inputSeen.rising:=word.ack.asUInt
  inputWithdrawn.common:=historyCommon.asUInt;inputWithdrawn.rising:=Cat(inputSeen.q,!word.req)
  private val inputOffer=and("input_offer",pending.q,!inputWithdrawn.q)
  word.ack:=buffer("output_delay",inputOffer.asUInt,delay=ModelTime.ps(32000)).asBool
  inputReturned.common:=pending.q.asUInt;inputReturned.rising:=Cat(inputWithdrawn.q,!word.ack)
  // This guarded arm is POR-only. Reset cannot truncate it or revive permission.
  private val applicationSeen=state("application_seen",2,application=true)
  private val applicationOffer=and("application_offer",issued.q,permission.q.asBool,application=true)
  response.req:=and("application_request",applicationOffer,!applicationSeen.q,application=true)
  response.bits.data:=payload.q;response.bits.error:=false.B
  applicationSeen.common:=historyCommon.asUInt;applicationSeen.rising:=Cat(response.req,response.ack)
  private val normal=permission.q.asBool && applicationSeen.q && !response.req && !response.ack
  private val cancelled= !permission.q.asBool && !response.req && !response.ack
  private val terminal=state("terminal",2)
  terminal.common:=pending.q.asUInt;terminal.rising:=Cat(issued.q,normal || cancelled)
  private def branch(id: String,request: Bool,ack: Bool): (Bool,Bool) = {
    val seen=state(id+"_seen",2);seen.common:=historyCommon.asUInt;seen.rising:=Cat(request,ack)
    val returned=state(id+"_returned",3);returned.common:=pending.q.asUInt
    returned.rising:=Cat(seen.q,!request,!ack)
    request:=and(id+"_offer",issued.q,!seen.q)
    (seen.q,returned.q)
  }
  private val (publicationSeen,publicationReturned)=branch("publication",publication.req,publication.ack)
  private val (receiptSeen,receiptReturned)=branch("receipt",captureRequest,captureAcknowledge)
  publication.bits:=payload.q(0)
  released.common:=pending.q.asUInt
  released.rising:=Cat(terminal.q,inputReturned.q,publicationReturned,receiptReturned)
  capacity:= !pending.q && !released.q && !cleanup && !armed && !historyCommon && !issued.q && !terminal.q &&
    !inputSeen.q && !inputWithdrawn.q && !inputReturned.q && !word.ack && !inputOffer &&
    !publicationSeen && !publicationReturned && !publication.req && !publication.ack &&
    !receiptSeen && !receiptReturned && !captureRequest && !captureAcknowledge &&
    !applicationSeen.q && !response.req && !response.ack && !applicationOffer
  idle:=capacity && !word.req
  presentationSettled:= !pending.q || terminal.q
  val payloadValue=WireDefault(UInt(32.W),payload.q);val permissionValue=WireDefault(UInt(1.W),permission.q)
  val terminalValue=WireDefault(terminal.q);val issuedValue=WireDefault(issued.q)
  Seq("capture_request"->captureRequest,"capture_acknowledge"->captureAcknowledge,"application_reset"->applicationReset,"eligible"->eligible,"response_request"->response.req,
    "response_acknowledge"->response.ack,"response_data"->response.bits,
    "presentation_settled"->presentationSettled,"idle"->idle,"capacity"->capacity,
    "arm_event"->armEvent,"input_data"->inputData,"retained_word"->payloadValue,
    "permission_data"->permissionData,"word_permission"->permissionValue,
    "history_hold"->historyCommon,"issued_identity"->issuedValue,"terminal_proof"->terminalValue,"cleanup"->cleanup).foreach {
      case(id,value) => dontTouch(value);contract.endpoint(id,value)
    }
  private val captureTiming=ClickTiming.Simulation
  for((id,source,data,captured,delay) <- Seq(
      ("word","word_data","input_data","retained_word","data_delay"),
      ("permission","eligible","permission_data","word_permission","permission_data_delay"))) {
    contract.dataPathTiming(id+"_path",source,data,timing,"native RAM return "+id+" capture",delayCell=delay)
    contract.setupHold(id+"_aperture",source,source,data,"arm_event",captured,captureTiming.setup,captureTiming.hold)
  }
  contract.capacity(1)
}
