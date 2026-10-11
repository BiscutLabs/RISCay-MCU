// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util.Cat
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives.{AsymmetricCElement,ControlGate,GateOperation}

/** POR proof transport and admission exclusion. No periodic clock or payload.
  * Fresh publication is retained until the old slot and final receipt return.
  * Digital delay assumptions require physical qualification.
  */
class FourPhaseRecoveryReturn(domain: ResetDomain) extends AsyncModule(domain) {
  val requested=IO(Input(Bool())); val admitted=IO(Output(Bool()))
  val originalReturned=IO(Input(Bool())); val fresh=IO(Input(Bool()))
  val eligible=IO(Input(Bool()))
  val finalRequest=IO(Output(Bool())); val finalAcknowledge=IO(Input(Bool()))
  val clear=IO(Output(Bool())); val quiet=IO(Output(Bool()))
  private val cell=ModelTime.ps(1000)
  private val cleanup=ModelTime.ps(200000)
  private val resetRef=contract.endpoint("reset",reset)
  private def state(id: String,rising: Int,commonInvert: Int=0,risingInvert: Int=0): AsymmetricCElement = {
    val c=Module(new AsymmetricCElement(1,rising,0,cell,commonInvert=commonInvert,risingInvert=risingInvert))
    c.reset:=reset; c.falling:=0.U
    contract.primitive(id,c,Map("COMMON"->BigInt(1),"RISING"->BigInt(rising),"FALLING"->BigInt(0),
      "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(commonInvert),
      "RISING_INVERT"->BigInt(risingInvert),"FALLING_INVERT"->BigInt(0)),resetRef,
      "retained POR recovery proof and complete return; qualify pulse and feedback paths")
    c
  }
  private def gate(id: String,op: GateOperation.Value,a: Bool,b: Bool=false.B,
      delay: ModelTime=cell,initial: Int=0): Bool = {
    val g=Module(new ControlGate(1,op,delay,initial));g.reset:=reset;g.a:=a;g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(1),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),resetRef,"retained proof offer/clear and cleanup guard")
    g.q.asBool
  }
  private def and(id: String,a: Bool,b: Bool): Bool =
    gate(id,GateOperation.Invert,gate(id+"_or",GateOperation.Or,
      gate(id+"_na",GateOperation.Invert,a,initial=1),
      gate(id+"_nb",GateOperation.Invert,b,initial=1),initial=1))

  private val pending=state("pending",1,commonInvert=1)
  private val issued=state("issued",1)
  private val ackSeen=state("ack_seen",3)
  private val done=state("done",3,risingInvert=3)
  private val delayedDone=WireDefault(gate("acknowledge_guard",GateOperation.Buffer,done.q,delay=cleanup))
  dontTouch(delayedDone)
  pending.common:=delayedDone.asUInt;pending.rising:=fresh.asUInt
  issued.common:=pending.q.asUInt;issued.rising:=originalReturned.asUInt
  private val noAck=gate("offer_ack_invert",GateOperation.Invert,ackSeen.q,initial=1)
  finalRequest:=and("offer",issued.q,noAck)
  ackSeen.common:=pending.q.asUInt
  ackSeen.rising:=Cat(issued.q,finalRequest,finalAcknowledge)
  done.common:=pending.q.asUInt
  done.rising:=Cat(ackSeen.q,finalRequest,finalAcknowledge)
  clear:=and("clear",done.q,eligible)
  quiet:= !fresh && !pending.q && !issued.q && !ackSeen.q && !done.q &&
    !delayedDone && !finalRequest && !finalAcknowledge && !clear
  // Withdrawal of capacity cannot truncate an admitted request. The common
  // input alone authorizes its falling transition; next admission waits cleanup.
  private val admission=state("admission",2)
  admission.common:=requested.asUInt;admission.rising:=Cat(originalReturned,quiet)
  admitted:=admission.q
  Seq("requested"->requested,"admitted"->admitted,"original_returned"->originalReturned,
    "fresh"->fresh,"eligible"->eligible,"final_request"->finalRequest,
    "final_acknowledge"->finalAcknowledge,"clear_event"->clear,"quiet"->quiet,
    "cleanup"->delayedDone).foreach { case(id,value) => contract.endpoint(id,value) }
  // done persists for >=200 ns before pending can fall; the three-cell clear
  // path plus debt Q is <=40 ns. All feedback also returns before admission.
  // Application reset revokes eligible independently; it never resets this tail.
  contract.capacity(1)
}
