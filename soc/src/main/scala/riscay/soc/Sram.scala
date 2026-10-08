// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import java.nio.file.{Files, Path}
import riscay.McuConfiguration

/** Technology inventory accompanies the library's unchanged async contract. */
object SramInventory {
  val macroName = "gf180mcu_ocd_ip_sram__sram1024x8m8wm1"
  def write(base: Path, config: McuConfiguration): Unit = {
    val top = ujson.read(Files.readString(base.resolve("contract.json")))("manifest")("top").str
    val instances = Seq("program" -> config.programBytes, "ram" -> config.workingRamBytes).flatMap {
      case(bank, bytes) => (0 until (bytes + 1023) / 1024).map(i =>
        ujson.Obj("path" -> s"$top.fabric_${bank}_macros_$i", "bank" -> bank, "index" -> i))
    }
    Files.writeString(base.resolve("sram.json"), ujson.write(ujson.Obj(
      "schema" -> "riscay-gf180-sram-v1", "macro" -> macroName,
      "program_bytes" -> config.programBytes, "working_ram_bytes" -> config.workingRamBytes,
      "instances" -> ujson.Arr.from(instances)), indent=2) + "\n")
  }
}

/** Fixed physical macro, with the pinned upstream model for event simulation.
  * SYNTHESIS selects its empty physical view, never a synthesized register array.
  */
class Gf180Sram1KiB extends ExtModule {
  override def desiredName = SramInventory.macroName
  val io = FlatIO(new Bundle {
    val CLK = Input(Clock())
    val CEN = Input(Bool()); val GWEN = Input(Bool()); val WEN = Input(UInt(8.W))
    val A = Input(UInt(10.W)); val D = Input(UInt(8.W)); val Q = Output(UInt(8.W))
  })
  def resource(suffix: String): String = {
    val stream = Option(getClass.getResourceAsStream(s"/riscay/sram/$desiredName$suffix"))
      .getOrElse(sys.error(s"Missing SRAM view: $suffix"))
    try new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8) finally stream.close()
  }
  // Upstream initializes its behavioral array to zero; physical SRAM has no
  // such guarantee. Poison only that simulation initializer, keeping the
  // vendored source byte-for-byte intact and its timing/access logic unchanged.
  val model = resource(".v")
  require(model.sliding("mem[i] = 8'd0;".length).count(_ == "mem[i] = 8'd0;") == 1)
  setInline(s"$desiredName.sv", "`ifdef SYNTHESIS\n" + resource(".blackbox.v") +
    "\n`else\n" + model.replace("mem[i] = 8'd0;", "mem[i] = 8'bx;") + "\n`endif\n")
}

class SramWordRequest extends Bundle {
  val address = UInt(32.W) // byte offset; low two bits identify lanes, not another word
  val write = Bool()
  val data = UInt(32.W)
  val mask = UInt(4.W)
}

/** One outstanding word, four byte accesses through synchronous 1 KiB macros.
  * The service clock drives CLK directly; CEN suppresses inactive operations.
  * A separate capture edge allows a full cycle for macro clock-to-Q. Contents
  * have no reset. POR aborts the controller; application reset does not reach it.
  */
class SramBank(bytes: Int) extends Module with InlineInstance {
  require(bytes > 0 && bytes % 4 == 0)
  val io = IO(new Bundle {
    val request = Flipped(Decoupled(new SramWordRequest))
    val response = Decoupled(UInt(32.W))
    val busy = Output(Bool())
  })
  val idle :: access :: capture :: answer :: Nil = Enum(4)
  val state = RegInit(idle)
  // The fabric checks the full byte address before submitting a request.
  // Retain only its word index; lane selection is owned by this controller.
  val wordIndex = Reg(UInt(log2Ceil(bytes / 4).max(1).W))
  val savedWrite = Reg(Bool())
  val savedData = Reg(UInt(32.W))
  val savedMask = Reg(UInt(4.W))
  val lane = RegInit(0.U(2.W))
  val result = Reg(Vec(4, UInt(8.W)))
  val offset = Cat(wordIndex, lane).pad(11)
  val bankIndex = offset >> 10
  val macros = Seq.fill((bytes + 1023) / 1024)(Module(new Gf180Sram1KiB))
  val reading = !savedWrite
  // Launch macro inputs on falling edges: satisfy nonzero input hold after
  // the rising access edge, and allow half a cycle for input setup/routing.
  val falling = (!clock.asBool).asClock
  val address = withClock(falling) { RegNext(offset(9, 0)) }
  val data = withClock(falling) { RegNext((savedData >> (lane << 3))(7, 0)) }
  val gwen = withClock(falling) { RegNext(!savedWrite, true.B) }
  for((macroCell, index) <- macros.zipWithIndex) {
    macroCell.io.CLK := clock
    macroCell.io.CEN := withClock(falling) {
      RegNext(!(state === access && bankIndex === index.U &&
        (reading || savedMask(lane))), true.B)
    }
    macroCell.io.GWEN := gwen
    macroCell.io.WEN := 0.U
    macroCell.io.A := address
    macroCell.io.D := data
  }
  val byte = MuxLookup(bankIndex, 0.U(8.W))(
    macros.zipWithIndex.map { case(m, i) => i.U -> m.io.Q })
  io.request.ready := state === idle && !reset.asBool
  io.response.valid := state === answer && !reset.asBool
  io.response.bits := Mux(savedWrite, 0.U, result.asUInt)
  io.busy := state =/= idle
  when(io.request.fire) {
    wordIndex := (if(bytes == 4) 0.U else io.request.bits.address >> 2)
    savedWrite := io.request.bits.write
    savedData := io.request.bits.data; savedMask := io.request.bits.mask
    lane := 0.U; state := access
  }
  when(state === access) { state := capture }
  when(state === capture) {
    when(reading) { result(lane) := byte }
    when(lane === 3.U) { state := answer }
      .otherwise { lane := lane + 1.U; state := access }
  }
  when(io.response.fire) { state := idle }
}
