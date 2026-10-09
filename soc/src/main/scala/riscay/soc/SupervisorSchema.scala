// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._

/** Wire schemas only. Ingress records input history; each native design owns
  * sample state, qualification counters and permanent power decisions.
  */
class SupervisorCapture extends Bundle {
  val seen = Bool(); val count = UInt(32.W); val hadValid = Bool()
  val valid = Bool(); val calibrated = Bool(); val value = UInt(32.W)
  val tailAge = UInt(32.W); val firstAge = UInt(32.W); val maximumGap = UInt(32.W)
  val minimum = UInt(32.W); val maximum = UInt(32.W); val failed = Bool()
}
class SupervisorCommand extends Bundle {
  val now = UInt(32.W); val tick = Bool(); val elapsedUpper = UInt(32.W)
  val observationMs = UInt(32.W); val firstObservationMs = UInt(32.W)
  val observationGap = Bool(); val gpio = UInt(32.W); val gpioChanged = UInt(32.W)
  val power = Bool(); val shutdown = Bool()
  val capture = new SupervisorCapture
}
class SupervisorState extends Bundle {
  val sensingFault = Bool()
  val mode = UInt(2.W); val fault = UInt(3.W); val timeouts = UInt(2.W)
  val offAt = UInt(32.W); val shutdownAt = UInt(32.W); val qualified = Bool()
  val waitRun = Bool(); val waitOff = Bool(); val waitShutdown = Bool()
  // high, low, restart voltage/inactive, low voltage
  val counts = Vec(4, UInt(32.W)); val observed = Vec(4, Bool())
  val sample = new Sample
}
object SupervisorState {
  def initial: SupervisorState = (new SupervisorState).Lit(
    _.sensingFault -> false.B, _.mode -> 0.U, _.fault -> 0.U, _.timeouts -> 0.U, _.offAt -> 0.U,
    _.shutdownAt -> 0.U, _.qualified -> false.B,
    _.waitRun -> false.B, _.waitOff -> false.B, _.waitShutdown -> false.B,
    _.counts -> Vec.Lit(Seq.fill(4)(0.U(32.W)): _*),
    _.observed -> Vec.Lit(Seq.fill(4)(false.B): _*),
    _.sample -> (new Sample).Lit(_.value -> 0.U, _.valid -> false.B,
      _.calibrated -> false.B, _.age -> 0.U, _.sequence -> 0.U,
      _.never -> true.B, _.fault -> false.B))
}
class BoardResult extends Bundle {
  val outputs = UInt(32.W)
  val registers = Vec(6, UInt(32.W))
}
