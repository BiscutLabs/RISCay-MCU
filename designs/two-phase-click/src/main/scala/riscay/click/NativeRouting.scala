// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util.Cat
import chiselasync.bundled.{ClickBuffer, Joined}
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ClickTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ControlGate, GateOperation}
import chiselasync.protocol.{Channel, TwoPhase}

/** Native phase rendezvous: equal phases advance, disagreement retains state.
  * Both operands start at phase zero and transfer once per joined transaction.
  * Digital model assumes atomic cells and ideal forks; physical closure is separate.
  */
private[click] object RoutingCells {
  def rendezvous(owner: AsyncModule, id: String, a: Bool, b: Bool): Bool = {
    val delay = ModelTime.ps(1000)
    val cell = Module(new AsymmetricCElement(2, 0, 0, delay))
    cell.reset := owner.reset
    cell.common := Cat(b, a)
    cell.rising := 1.U
    cell.falling := 0.U
    val reset = owner.contract.endpoint(s"${id}_reset", owner.reset)
    owner.contract.primitive(id, cell, Map("COMMON" -> BigInt(2), "RISING" -> BigInt(0),
      "FALLING" -> BigInt(0), "DELAY_FS" -> BigInt(delay.fs), "RESET_VALUE" -> BigInt(0),
      "COMMON_INVERT" -> BigInt(0), "RISING_INVERT" -> BigInt(0), "FALLING_INVERT" -> BigInt(0)),
      reset, "native two-phase rendezvous; coordinated parity-zero reset; atomic cell and ideal forks")
    cell.q
  }

  def request(owner: AsyncModule, id: String, phase: Bool): Bool = {
    val delay = ModelTime.ps(1000)
    val cell = Module(new ControlGate(1, GateOperation.Buffer, delay))
    cell.reset := owner.reset; cell.a := phase.asUInt; cell.b := 0.U
    val reset = owner.contract.endpoint(s"${id}_reset", owner.reset)
    owner.contract.primitive(id, cell, Map("WIDTH" -> BigInt(1), "OP" -> BigInt(0),
      "DELAY_FS" -> BigInt(delay.fs), "RESET_VALUE" -> BigInt(0)), reset,
      "native two-phase fork request propagation; downstream Click bundling protects payload")
    cell.q.asBool
  }
}

class ClickFork[T <: Data](gen: T, domain: ResetDomain) extends AsyncModule(domain) {
  val in = twoPhaseInput("in", gen)
  val left = twoPhaseOutput("left", gen)
  val right = twoPhaseOutput("right", gen)
  left.bits := in.bits; right.bits := in.bits
  left.req := RoutingCells.request(this, "left_delay", in.req)
  right.req := RoutingCells.request(this, "right_delay", in.req)
  in.ack := RoutingCells.rendezvous(this, "completion", left.ack, right.ack)
}

/** Pair nth left with nth right; one native Click storage slot per input. */
class ClickJoin[A <: Data, B <: Data](a: A, b: B, timing: ClickTiming, domain: ResetDomain)
    extends AsyncModule(domain) {
  val left = twoPhaseInput("left", a)
  val right = twoPhaseInput("right", b)
  val out = twoPhaseOutput("out", new Joined(a, b))
  private val l = asyncChild("left_storage")(d => new ClickBuffer(a, timing, d))
  private val r = asyncChild("right_storage")(d => new ClickBuffer(b, timing, d))
  TwoPhase.connect(l.in, left); TwoPhase.connect(r.in, right)
  out.bits.left := l.out.bits; out.bits.right := r.out.bits
  out.req := RoutingCells.rendezvous(this, "rendezvous", l.out.req, r.out.req)
  l.out.ack := out.ack; r.out.ack := out.ack
}
