// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._
import riscay.soc._

/** Independent reference clock. A timeout asserts application reset for a
  * bounded interval, including the CPU and its bus endpoints, not power policy.
  * Reason is retained in this POR-only domain until external reset.
  */
class Watchdog(limit: Int, holdCycles: Int) extends Module with InlineInstance {
  val io = IO(new Bundle {
    val heartbeat = Input(Bool())
    val expired = Output(Bool())
    val reason = Output(Bool())
    val acknowledge = Output(Bool())
  })
  val sync = RegInit(0.U(2.W)); sync := Cat(sync(0), io.heartbeat)
  val seen = RegInit(false.B)
  val count = RegInit(0.U(log2Ceil(limit + 1).W))
  val hold = RegInit(0.U(log2Ceil(holdCycles + 1).W))
  val reason = RegInit(false.B)
  when(hold =/= 0.U) { hold := hold - 1.U; count := 0.U; seen := sync(1) }
    .elsewhen(sync(1) =/= seen) { seen := sync(1); count := 0.U }
    .elsewhen(count === (limit - 1).U) { hold := holdCycles.U; reason := true.B; count := 0.U }
    .otherwise { count := count + 1.U }
  io.expired := hold =/= 0.U
  io.reason := reason
  io.acknowledge := seen
}
