// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ClickTiming
import chiselasync.protocol.TwoPhase
import riscay._
import riscay.soc._

/** POR-owned native telemetry token. Application reset is a command; sample
  * records survive it. Clocked ingress carries observations, never full state.
  */
class ClickTelemetry(p: SocParameters, words: Vector[Int], domain: ResetDomain) extends AsyncModule(domain) {
  val command = twoPhaseInput("command", new TelemetryCommand(p.config.measurements.size))
  val reply = twoPhaseOutput("reply", new TelemetryReply(p.config.measurements.size, words.size))
  val start = IO(Input(Bool()))
  private val timing = ClickTiming.Simulation
  private val state = asyncChild("state")(d => new PhaseDecoupledClickBuffer(new TelemetryState(p.config.measurements.size, words.size),
    timing, Some(TelemetryState.initial(p, words.size)), d))
  private val join = asyncChild("join")(d => new ClickJoin(new TelemetryState(p.config.measurements.size, words.size), new TelemetryCommand(p.config.measurements.size), timing, d))
  private val update = asyncChild("update")(d => new ClickStage(new Joined(new TelemetryState(p.config.measurements.size, words.size), new TelemetryCommand(p.config.measurements.size)),
    new TelemetryReply(p.config.measurements.size, words.size), (x: Joined[TelemetryState, TelemetryCommand]) => transition(x.left, x.right), timing, d))
  private val fork = asyncChild("fork")(d => new ClickFork(new TelemetryReply(p.config.measurements.size, words.size), d))
  // The registered fork contract describes its complete payload on both branches.
  // Retain the fields that the state feedback branch does not consume.
  dontTouch(fork.left)
  state.start.get := start
  TwoPhase.connect(join.left, state.out); TwoPhase.connect(join.right, command)
  TwoPhase.connect(update.in, join.out); TwoPhase.connect(fork.in, update.out)
  state.in.bits := fork.left.bits.state; state.in.req := fork.left.req; fork.left.ack := state.in.ack
  TwoPhase.connect(reply, fork.right)
  contract.endpoint("start", start)

  private def transition(s: TelemetryState, c: TelemetryCommand): TelemetryReply = {
    val r = WireDefault(0.U.asTypeOf(new TelemetryReply(p.config.measurements.size, words.size)))
    r.kind := c.kind; r.state := s
    r.recovery := c.recovery
    val n = r.state
    when(c.kind === TelemetryKind.ResetApplication.U) {
      n.output := TelemetryState.initial(p, words.size).output
      n.enable := TelemetryState.initial(p, words.size).enable
      n.application.foreach(_.foreach(_ := 0.U))
    }
    n.pending := (Mux(c.kind === TelemetryKind.ResetApplication.U, 0.U, s.pending) & ~c.clear) | c.events
    when(c.kind === TelemetryKind.Commit.U) {
      switch(c.offset) {
        is(24.U) { n.output := c.data }
        is(28.U) { n.enable := c.data }
        is(52.U) { for((word,index) <- words.zipWithIndex) {
          when(c.appIndex === word.U) { n.application.get(index) := c.data }
        } }
      }
    }
    for(i <- p.config.measurements.indices) {
      val capture = c.captures.get(i)
      val old = s.samples.get(i); val next = n.samples.get(i)
      val aged = old.age +& c.elapsedUpper
      next.age := Mux(aged(32), "hffffffff".U, aged(31,0))
      when(capture.seen) {
        next.sequence := old.sequence + capture.count
        next.valid := capture.valid; next.fault := !capture.valid
        next.calibrated := capture.valid && capture.calibrated
      }
      when(capture.hadValid) {
        next.value := capture.value; next.never := false.B; next.age := capture.tailAge
      }
    }
    r
  }
}
