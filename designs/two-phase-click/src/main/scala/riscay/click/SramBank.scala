// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay.soc._

/** One synchronous byte access with falling-edge launch and full-cycle Q
  * capture. Word ownership, lane progression and assembly are native. The
  * lane ports are mutually exclusive by native execution-credit ordering.
  * CLK remains the service clock; there is no request-derived clock generator.
  */
class SramBank(bytes: Int) extends Module with InlineInstance {
  require(bytes > 0 && bytes % 4 == 0)
  val io = IO(new Bundle {
    val request = Flipped(Vec(4, Decoupled(new SramByteRequest)))
    val response = Vec(4, Decoupled(UInt(8.W)))
  })
  val idle :: access :: capture :: answer :: Nil = Enum(4)
  val state = RegInit(idle)
  val selected = PriorityEncoder(VecInit(io.request.map(_.valid)).asUInt)
  val tag = Reg(UInt(2.W))
  val saved = Reg(new SramByteRequest)
  val result = Reg(UInt(8.W))
  val macros = Seq.fill((bytes + 1023) / 1024)(Module(new Gf180Sram1KiB))
  val bankIndex = saved.address >> 10
  val falling = (!clock.asBool).asClock
  val address = withClock(falling) { RegNext(saved.address(9,0)) }
  val data = withClock(falling) { RegNext(saved.data) }
  val gwen = withClock(falling) { RegNext(!saved.write, true.B) }
  for((macroCell, index) <- macros.zipWithIndex) {
    macroCell.io.CLK := clock
    macroCell.io.CEN := withClock(falling) {
      RegNext(!(state === access && bankIndex === index.U && saved.enable), true.B)
    }
    macroCell.io.GWEN := gwen; macroCell.io.WEN := 0.U
    macroCell.io.A := address; macroCell.io.D := data
  }
  for(i <- 0 until 4) {
    io.request(i).ready := state === idle && selected === i.U && !reset.asBool
    io.response(i).valid := state === answer && tag === i.U && !reset.asBool
    io.response(i).bits := result
  }
  when(state === idle && io.request(selected).fire) {
    assert(io.request(selected).bits.address < bytes.U)
    assert(PopCount(VecInit(io.request.map(_.valid))) === 1.U)
    saved := io.request(selected).bits; tag := selected; state := access
  }
  when(state === access) { state := capture }
  when(state === capture) {
    result := Mux(saved.write || !saved.enable, 0.U, MuxLookup(bankIndex, 0.U(8.W))(
      macros.zipWithIndex.map { case(m,i) => i.U -> m.io.Q }))
    state := answer
  }
  when(state === answer && io.response(tag).fire) { state := idle }
}
