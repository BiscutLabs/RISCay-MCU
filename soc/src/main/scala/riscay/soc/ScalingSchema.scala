// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._

/** Wire schemas only. Each design owns its arithmetic and native sequencing. */
class ElapsedScalingPort(lanes: Int) extends Bundle {
  val target = Input(UInt(32.W)); val consumed = Output(UInt(32.W))
  val valid = Output(Bool()); val single = Output(Bool()); val busy = Output(Bool())
  val elapsed = Output(Vec(lanes, UInt(32.W)))
}
class SampleScalingPort extends Bundle {
  val start = Input(Bool()); val raw = Input(UInt(12.W))
  val busy = Output(Bool()); val done = Output(Bool()); val value = Output(UInt(32.W))
}
class ElapsedState(lanes: Int) extends Bundle {
  val consumed = UInt(32.W); val fraction = Vec(lanes, UInt(10.W))
}
class ElapsedWork(lanes: Int) extends Bundle {
  val state = new ElapsedState(lanes)
  val target = UInt(32.W); val delta = UInt(32.W)
  val quotient = Vec(lanes, UInt(32.W)); val remainder = Vec(lanes, UInt(10.W))
}
class ElapsedResult(lanes: Int) extends Bundle {
  val state = new ElapsedState(lanes)
  val single = Bool(); val elapsed = Vec(lanes, UInt(32.W))
}
class SampleWork(remainderWidth: Int) extends Bundle {
  val raw = UInt(12.W); val quotient = UInt(32.W); val remainder = UInt(remainderWidth.W)
}
