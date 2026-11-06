// SPDX-License-Identifier: Apache-2.0
package riscay.clocked

import chisel3._
import chisel3.util._
import riscay._

/** One ordered synchronous bus transaction at a time. The shared ISA transform
  * is combinational; this implementation owns its registers and sequencing.
  * Request acceptance and response consumption are on distinct rising edges.
  * Reset cancels the bus epoch; the attached fabric must discard stale replies.
  */
class ClockedCore extends Module {
  val request = IO(Decoupled(new MemoryRequest))
  val response = IO(Flipped(Decoupled(new MemoryResponse)))
  val trace = IO(Output(new Retirement))
  val traceEvent = IO(Output(Bool()))
  val pc = RegInit(0.U(32.W))
  val operation = RegInit(Operation.Fetch.U(2.W))
  val instruction = RegInit(0.U(32.W))
  val address = RegInit(0.U(32.W))
  val storeData = RegInit(0.U(32.W))
  val mask = RegInit(0.U(4.W))
  val registers = RegInit(VecInit(Seq.fill(15)(0.U(32.W))))
  val waiting = RegInit(false.B)
  val halted = RegInit(false.B)
  val retired = RegInit(0.U.asTypeOf(new Retirement))
  retired.valid := false.B

  private val state = Wire(new CoreState)
  state.pc := pc; state.operation := operation; state.instruction := instruction
  state.address := address; state.storeData := storeData; state.mask := mask
  state.writeback := 0.U.asTypeOf(new RegisterWrite)
  private def read(index: UInt): UInt = MuxLookup(index, 0.U(32.W))(
    (1 to 15).map(i => i.U -> registers(i-1)))
  private val result = Execute.step(state, response.bits,
    read(response.bits.data(19,15)), read(response.bits.data(24,20)))

  request.valid := !waiting && !halted && !reset.asBool
  request.bits := Execute.request(state)
  response.ready := waiting && !reset.asBool
  when(request.fire) {
    when(operation === Operation.Halt.U) { halted := true.B }
      .otherwise { waiting := true.B }
  }
  when(response.fire) {
    waiting := false.B
    pc := result.state.pc; operation := result.state.operation
    instruction := result.state.instruction; address := result.state.address
    storeData := result.state.storeData; mask := result.state.mask
    for(i <- 1 to 15) {
      when(result.state.writeback.enable && result.state.writeback.rd === i.U) {
        registers(i-1) := result.state.writeback.data
      }
    }
    retired := result.trace
  }
  trace := retired
  traceEvent := retired.valid && !reset.asBool
}
