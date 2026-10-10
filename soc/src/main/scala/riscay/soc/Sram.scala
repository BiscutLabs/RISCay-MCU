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

/** Shared payloads only. The two designs own their word and macro controllers. */
class SramWork extends Bundle {
  val request = new SramWordRequest
  val result = UInt(32.W)
}
class SramByteRequest extends Bundle {
  val address = UInt(32.W)
  val write = Bool()
  val data = UInt(8.W)
  val enable = Bool()
}
class SramAccessPort extends Bundle {
  val request = Decoupled(new SramWordRequest)
  val response = Flipped(Decoupled(UInt(32.W)))
  val busy = Input(Bool())
  val bytes = Flipped(Vec(4, Decoupled(new SramByteRequest)))
  val completions = Vec(4, Decoupled(UInt(8.W)))
}

/** Shared boundary schema only. The design-specific native owner holds one RAM
  * reservation through commit/publication or cancellation and complete drainage.
  */
class RamSourceBoundaryPort extends Bundle {
  val reserve = Decoupled(Bool()) // Operation write bit.
  val grant = Flipped(Decoupled(Bool()))
  val decision = Decoupled(Bool()) // True iff the CPU and RAM accepted together.
  val publication = Decoupled(Bool()) // Actual response bit zero.
  val eligible = Input(Bool())
  val resetDebt = Input(Bool())
  val draining = Input(Bool())
}

/** Program-source schemas only; retained ownership and Stored phases are native. */
class ProgramSourceBoundaryPort extends Bundle {
  val reserve = Decoupled(Bool()) // True: accepted loader obligation; false: CPU read.
  val grant = Flipped(Decoupled(Bool()))
  val decision = Decoupled(Bool()) // True iff the selected client and word accepted together.
  val publication = Decoupled(Bool()) // Actual response bit zero.
  val stored = Flipped(Decoupled(Bool())) // ACK only on Stored Control command acceptance.
  val ownerLoader = Input(Bool())
  val eligible = Input(Bool())
  val resetDebt = Input(Bool())
  val draining = Input(Bool())
}
