// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel

/** Native toggle bridge: two control synchronizer stages plus a bus settling
  * cycle. Ack toggles only on downstream acceptance; no four-phase machinery.
  */
class ClickToDecoupled[T <: Data](gen: T, domain: ResetDomain) extends ClockedBridge(domain, 2) {
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.twoPhase)); val out = IO(channel.decoupled)
  val request = synchronizedControl(in.req)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W)); val ack = RegInit(false.B)
    val data = RegInit(0.U.asTypeOf(gen))
    in.ack := ack; out.bits := data; out.valid := state === 2.U && !localReset.asBool
    switch(state) {
      is(0.U) { when(request =/= ack) { state := 1.U } }
      is(1.U) { data := in.bits; state := 2.U }
      is(2.U) { when(out.fire) { ack := request; state := 0.U } }
    }
  }
  contract.capacity(1); contract.twoPhaseChannel("in", in, "input")
  contract.clockedChannel("out", out, clock, channel, "output")
  contract.endpoint("reset", reset)
}

class DecoupledToClick[T <: Data](gen: T, domain: ResetDomain) extends ClockedBridge(domain, 2) {
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.decoupled)); val out = IO(channel.twoPhase)
  val ack = synchronizedControl(out.ack)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W)); val request = RegInit(false.B)
    val data = RegInit(0.U.asTypeOf(gen))
    in.ready := state === 0.U && !localReset.asBool; out.bits := data; out.req := request
    switch(state) {
      is(0.U) { when(in.fire) { data := in.bits; state := 1.U } }
      is(1.U) { request := !request; state := 2.U } // Full cycle of data setup.
      is(2.U) { when(ack === request) { state := 0.U } }
    }
  }
  contract.capacity(1); contract.clockedChannel("in", in, clock, channel, "input")
  contract.twoPhaseChannel("out", out, "output"); contract.endpoint("reset", reset)
}
