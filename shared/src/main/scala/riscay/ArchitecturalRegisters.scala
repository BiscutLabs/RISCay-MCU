// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives.EventRegister

// The library's Scala wrapper is package-private; reuse its published primitive
// and timing model rather than synthesizing a combinational gated event in Scala.
private class RegisterWriteAnd(delay: ModelTime) extends ExtModule(Map(
  "INPUTS" -> IntParam(2), "DELAY_FS" -> IntParam(delay.fs), "INVERT" -> IntParam(0))) {
  override def desiredName = "ChiselAsyncAnd_v1"
  val reset = IO(Input(AsyncReset())); val d = IO(Input(UInt(2.W)))
  val q = IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncAnd_v1.sv")
}

/** One copy of x1..x15. A stable state-token writeback is captured once on
  * arrival, before the next memory response can launch operand evaluation.
  * Only the selected bank receives a write pulse; x0 has no storage.
  */
class ArchitecturalRegisters(domain: ResetDomain) extends AsyncModule(domain) {
  val arrival = IO(Input(Bool()))
  val write = IO(Input(new RegisterWrite))
  val rs1 = IO(Input(UInt(5.W))); val rs2 = IO(Input(UInt(5.W)))
  val a = IO(Output(UInt(32.W))); val b = IO(Output(UInt(32.W)))
  private val delay = ModelTime.ps(1000)
  private val resetRef = contract.endpoint("reset",reset)
  private val banks = (1 to 15).map { index =>
    val gate = Module(new RegisterWriteAnd(delay))
    gate.reset := reset
    gate.d := Cat(write.enable && write.rd === index.U,arrival)
    contract.primitive(s"select$index",gate,Map("INPUTS"->BigInt(2),"INVERT"->BigInt(0),
      "DELAY_FS"->BigInt(delay.fs)),resetRef,
      "decode and data stable before arrival pulse and through token acknowledgement")
    val bank = Module(new EventRegister(32,delay))
    bank.reset := reset; bank.trigger := gate.q; bank.d := write.data
    contract.primitive(s"x$index",bank,Map("WIDTH"->BigInt(32),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,
      "one selected architectural register written per retirement; no replicated register-file token")
    // Primitive registration already exports the gate/register port probes.
    index.U -> bank.q
  }
  a := MuxLookup(rs1,0.U(32.W))(banks); b := MuxLookup(rs2,0.U(32.W))(banks)
  contract.endpoint("arrival",arrival)
  contract.endpoint("write_enable",write.enable)
  contract.endpoint("write_index",write.rd); contract.endpoint("write_data",write.data)
  contract.endpoint("read_index_a",rs1); contract.endpoint("read_index_b",rs2)
  contract.endpoint("read_a",a); contract.endpoint("read_b",b)
}
