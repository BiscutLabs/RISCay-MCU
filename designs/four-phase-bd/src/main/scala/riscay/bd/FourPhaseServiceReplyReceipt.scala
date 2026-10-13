// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel

/** POR-owned receipt of an already retained native service reply.
  * The native producer owns every payload bit through downstream acceptance
  * and complete RTZ. The consumer captures the held bus on out.fire; ACK means
  * that actual capture. No periodic-clock payload bank is inserted here.
  * Keep the previous receiver's control/settling cycles unchanged. Bundled-data
  * setup/hold to the consumer and synchronizer timing remain physical obligations.
  */
class FourPhaseServiceReplyReceipt[T <: Data](gen: T, domain: ResetDomain)
    extends ClockedBridge(domain, 2) {
  dontTouch(localReset)
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.bundled)); val out = IO(channel.decoupled)
  private val request = synchronizedControl(in.req)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W))
    val acknowledge = RegInit(false.B)
    in.ack := acknowledge; out.bits := in.bits
    out.valid := state === 2.U && !localReset.asBool
    switch(state) {
      is(0.U) { when(request) { state := 1.U } }
      is(1.U) { state := 2.U }
      is(2.U) { when(out.fire) { acknowledge := true.B; state := 3.U } }
      is(3.U) { when(!request) { acknowledge := false.B; state := 0.U } }
    }
    contract.endpoint("state", state)
    contract.endpoint("acknowledge", acknowledge)
  }
  contract.capacity(1)
  contract.channel("in", in, "input")
  contract.clockedChannel("out", out, clock, channel, "output")
  contract.endpoint("request_sync", request)
  contract.endpoint("local_reset", localReset)
  contract.endpoint("reset", reset)
}
