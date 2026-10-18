// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel
import riscay.soc.TelemetryReply

/** POR-owned native-phase receipt of an already retained payload.
  * The producer owns every payload bit until downstream acceptance. ACK records
  * that capture's phase; there is no RTZ conversion or periodic-clock payload
  * bank. Preserve the previous receiver's control/settling cycles. The complete
  * producer-to-consumer setup/hold and synchronization path still needs physical
  * qualification, including the earliest payload release after ACK.
  */
class ClickServiceReplyReceipt[T <: Data](gen: T, domain: ResetDomain)
    extends ClockedBridge(domain, 2) {
  dontTouch(localReset)
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.twoPhase)); val out = IO(channel.decoupled)
  private val request = synchronizedControl(in.req)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W)); val ack = RegInit(false.B)
    in.ack := ack; out.bits := in.bits
    out.valid := state === 2.U && !localReset.asBool
    switch(state) {
      is(0.U) { when(request =/= ack) { state := 1.U } }
      is(1.U) { state := 2.U }
      is(2.U) { when(out.fire) { ack := request; state := 0.U } }
    }
    contract.endpoint("state", state)
    contract.endpoint("acknowledge", ack)
  }
  contract.capacity(1)
  contract.twoPhaseChannel("in", in, "input")
  contract.clockedChannel("out", out, clock, channel, "output")
  contract.endpoint("request_sync", request)
  contract.endpoint("local_reset", localReset)
  contract.endpoint("reset", reset)
}

/** Authorization travels beside the accepted phase and stays until the next
  * receipt. The native bank consumes both ACK polarities, even when revoked.
  */
class ClickTelemetryReceipt(gen: TelemetryReply,domain: ResetDomain)
    extends ClickServiceReplyReceipt(gen,domain) {
  val applyBank=IO(Input(Bool()));val bankApply=IO(Output(Bool()))
  withClockAndReset(clock,localReset) {
    val accepted=RegInit(false.B)
    when(out.fire) { accepted:=applyBank }
    bankApply:=accepted
  }
  contract.endpoint("apply_bank",applyBank);contract.endpoint("bank_apply",bankApply)
}
