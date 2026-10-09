// SPDX-License-Identifier: Apache-2.0
package riscay.click

import riscay.soc._

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance

object ConstantScaling {
  // One radix-2 step in mixed quotient/remainder form. Bounds permit at most
  // two subtractions. All divisions here are Scala elaboration-time constants.
  def step(q: UInt, r: UInt, bit: Bool, numerator: Int, denominator: Int): (UInt, UInt) = {
    val total = (r << 1) +& Mux(bit, (numerator % denominator).U, 0.U)
    val carry = Mux(total >= (2L * denominator).U, 2.U, Mux(total >= denominator.U, 1.U, 0.U))
    val remainder = Mux(carry === 2.U, total - (2L * denominator).U,
      Mux(carry === 1.U, total - denominator.U, total))
    (((q << 1) + Mux(bit, (numerator / denominator).U, 0.U) + carry)(31,0), remainder)
  }
}

/** Three exact fractional accumulators. One new tick takes one edge; missed
  * ticks use a bounded 32-edge binary walk, then publish one coalesced update.
  */
class ElapsedTicks(micros: Seq[Int]) extends Module with InlineInstance {
  val io = IO(new Bundle {
    val target = Input(UInt(32.W)); val consumed = Output(UInt(32.W))
    val valid = Output(Bool()); val single = Output(Bool()); val busy = Output(Bool())
    val elapsed = Output(Vec(micros.size, UInt(32.W)))
  })
  val consumed = RegInit(0.U(32.W)); io.consumed := consumed
  val fraction = RegInit(VecInit(Seq.fill(micros.size)(0.U(10.W))))
  val busy = RegInit(false.B); val bits = Reg(UInt(32.W)); val left = Reg(UInt(5.W))
  val target = Reg(UInt(32.W))
  val quotients = Reg(Vec(micros.size, UInt(32.W)))
  val remainders = Reg(Vec(micros.size, UInt(10.W)))
  val delta = io.target - consumed
  io.busy := busy || delta =/= 0.U
  io.valid := false.B; io.single := false.B; io.elapsed := 0.U.asTypeOf(io.elapsed)
  when(!busy && delta =/= 0.U) {
    when(delta === 1.U) {
      io.valid := true.B; io.single := true.B; consumed := io.target
      for((us,i) <- micros.zipWithIndex) {
        val next = fraction(i) +& (us % 1000).U
        val carry = next >= 1000.U
        fraction(i) := Mux(carry, next - 1000.U, next)
        io.elapsed(i) := (us / 1000).U +& carry
      }
    }.otherwise {
      busy := true.B; bits := delta; left := 31.U; target := io.target
      quotients.foreach(_ := 0.U); remainders.foreach(_ := 0.U)
    }
  }
  when(busy) {
    bits := bits << 1; left := left - 1.U
    for((us,i) <- micros.zipWithIndex) {
      val (q,r) = ConstantScaling.step(quotients(i), remainders(i), bits(31), us, 1000)
      quotients(i) := q; remainders(i) := r
      when(left === 0.U) {
        val sum = r +& fraction(i); val carry = sum >= 1000.U
        fraction(i) := Mux(carry, sum - 1000.U, sum)
        io.elapsed(i) := q + carry
      }
    }
    when(left === 0.U) { busy := false.B; io.valid := true.B; consumed := target }
  }
}

/** Exact constant rational scaling without a combinational multiply/divide. */
class SampleScaler(numerator: Int, denominator: Int) extends Module with InlineInstance {
  val io = IO(new Bundle {
    val start = Input(Bool()); val raw = Input(UInt(12.W))
    val busy = Output(Bool()); val done = Output(Bool()); val value = Output(UInt(32.W))
  })
  val active = RegInit(false.B); val raw = Reg(UInt(12.W)); val left = Reg(UInt(4.W))
  val quotient = Reg(UInt(32.W)); val remainder = Reg(UInt(log2Ceil(denominator).max(1).W))
  val (q,r) = ConstantScaling.step(quotient, remainder, raw(11), numerator, denominator)
  io.busy := active; io.done := active && left === 0.U; io.value := q
  when(io.start && !active) { active := true.B; raw := io.raw; left := 11.U; quotient := 0.U; remainder := 0.U }
  when(active) {
    raw := raw << 1; left := left - 1.U; quotient := q; remainder := r
    when(left === 0.U) { active := false.B }
  }
}
