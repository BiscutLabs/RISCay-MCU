// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._

/** Wire schemas only. Each design owns its arithmetic and native sequencing. */
class ElapsedScalingPort(lanes: Int) extends Bundle {
  // publicationTarget, single and elapsed describe the publication at valid.
  val target = Input(UInt(32.W)); val consumed = Output(UInt(32.W)); val publicationTarget = Output(UInt(32.W))
  val valid = Output(Bool()); val single = Output(Bool()); val busy = Output(Bool())
  val elapsed = Output(Vec(lanes, UInt(32.W)))
  // Direct retained payload for combinational preparation. Undefined when !valid;
  // every state update depending on this view must be qualified by valid.
  val publicationElapsed = Output(Vec(lanes, UInt(32.W)))
}
class SampleScalingPort extends Bundle {
  // Capture value on done. The held native payload is unspecified when !done.
  val start = Input(Bool()); val raw = Input(UInt(12.W))
  val busy = Output(Bool()); val done = Output(Bool()); val value = Output(UInt(32.W))
}
class ElapsedState(lanes: Int) extends Bundle {
  val consumed = UInt(32.W); val fraction = Vec(lanes, UInt(10.W))
}
class ElapsedLoopState(lanes: Int, modeWidth: Int) extends Bundle {
  // target is the previous consumed count while idle, and the active target
  // while running. Quotients become the held result on the final nibble.
  val target = UInt(32.W); val delta = UInt(32.W)
  val fraction = Vec(lanes, UInt(10.W))
  val quotient = Vec(lanes, UInt(32.W)); val remainder = Vec(lanes, UInt(10.W))
  val index = UInt(3.W); val single = Bool()
  val commandPhase = Bool(); val replyPhase = Bool(); val mode = UInt(modeWidth.W)
}
class ElapsedLoopInput(lanes: Int, modeWidth: Int) extends Bundle {
  val state = new ElapsedLoopState(lanes, modeWidth)
  val target = UInt(32.W); val commandPhase = Bool()
}
class ElapsedResult(lanes: Int) extends Bundle {
  val state = new ElapsedState(lanes)
  val single = Bool(); val elapsed = Vec(lanes, UInt(32.W))
}
class SampleWork(remainderWidth: Int) extends Bundle {
  val raw = UInt(12.W); val quotient = UInt(32.W); val remainder = UInt(remainderWidth.W)
}
