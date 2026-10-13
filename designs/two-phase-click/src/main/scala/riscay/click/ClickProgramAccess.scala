// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ClickTiming, ModelTime}
import chiselasync.protocol.TwoPhase
import riscay.soc._

/** Program admission and physical byte crossings. Native word capture
  * releases active independently of publication; full busy also includes the
  * native return owner. effectsDrained excludes that owner to avoid a cycle.
  */
class ProgramAccess(domain: ResetDomain) extends ClockedBridge(domain, 2) {
  val io = IO(Flipped(new ProgramAccessPort))
  dontTouch(io)
  val word=twoPhaseOutput("word",UInt(32.W))
  val captureRequest=IO(Input(Bool())); val captureAcknowledge=IO(Output(Bool()))
  val returnIdle=IO(Input(Bool())); val effectsDrained=IO(Output(Bool()))
  val receipt=asyncChild("capture_receipt")(d => new ClickProgramCaptureReceipt(d))
  receipt.clock:=clock; receipt.request:=captureRequest; captureAcknowledge:=receipt.acknowledge
  val native = asyncChild("native")(d => new ClickSram(d))
  native.start := !localReset.asBool
  val command = asyncChild("command_bridge")(d => new DecoupledToClick(new SramWordRequest, d))
  command.clock := clock
  TwoPhase.connect(native.request,command.out); TwoPhase.connect(word,native.response)
  val requests = (0 until 4).map(i => asyncChild(s"byte_request_$i")(d => new ClickServiceReplyReceipt(new SramByteRequest, d)))
  val replies = (0 until 4).map(i => asyncChild(s"byte_reply_$i")(d => new DecoupledToClick(UInt(8.W), d)))
  for(i <- 0 until 4) {
    requests(i).clock := clock; replies(i).clock := clock
    TwoPhase.connect(requests(i).in, native.byteRequest(i)); TwoPhase.connect(native.byteResponse(i), replies(i).out)
    io.bytes(i) <> requests(i).out; replies(i).in <> io.completions(i)
  }
  private val returned = synchronizedControl(word.req === word.ack)
  private val bytesReturned = requests.map(b => synchronizedControl(b.in.req === b.in.ack)).reduce(_ && _)
  private val ownerReturned=synchronizedControl(returnIdle)
  withClockAndReset(clock, localReset) {
    val active = RegInit(false.B)
    val drained = returned && bytesReturned && command.in.ready && replies.map(_.in.ready).reduce(_ && _) && receipt.idle
    command.in.valid := io.request.valid && !active && drained && ownerReturned
    command.in.bits := io.request.bits; io.request.ready := !active && drained && ownerReturned
    when(command.in.fire) { active := true.B }
    receipt.accept:=active
    when(receipt.accepted) { active:=false.B }
    effectsDrained:= !active && drained && !localReset.asBool
    io.busy:=active || !drained || !ownerReturned || localReset.asBool
    dontTouch(active);contract.endpoint("active",active)

  }
  Seq("capture_request"->captureRequest,"capture_acknowledge"->captureAcknowledge,
    "return_idle"->returnIdle,"effects_drained"->effectsDrained,"reset"->reset).foreach {
    case(id,value) => dontTouch(value);contract.endpoint(id,value)
  }
}
