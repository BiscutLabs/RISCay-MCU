// SPDX-License-Identifier: Apache-2.0
// One exact fixed macro per isolated native owner; no production wiring.
package riscay

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ExportDesign
import riscay.soc.{Gf180Sram1KiB, SramByteRequest}
import java.nio.file.{Files, Path, Paths}
import riscay.bd.experimental.FourPhaseMacroByteOwner
import riscay.click.experimental.ClickMacroByteOwner
import riscay.soc.experimental.{ByteModelTiming, MacroByteObservations}

class FourPhaseMacroByteFixture(t: ByteModelTiming) extends AsyncModule(new ResetDomain("bootstrap")) {
  val request = fourPhaseInput("request", new SramByteRequest)
  val result = fourPhaseOutput("result", UInt(8.W))
  val stopRequest = IO(Input(Bool())); val rearm = IO(Input(Bool()))
  val sourceQuiescent = IO(Input(Bool()))
  val observe = IO(Output(new MacroByteObservations))
  val owner = asyncChild("byte_owner")(d => new FourPhaseMacroByteOwner(d, t))
  owner.request.req := request.req; owner.request.bits := request.bits; request.ack := owner.request.ack
  result.req := owner.result.req; result.bits := owner.result.bits; owner.result.ack := result.ack
  owner.stopRequest := stopRequest; owner.rearm := rearm; owner.sourceQuiescent := sourceQuiescent
  observe := owner.observe
  val macroCell = Module(new Gf180Sram1KiB)
  macroCell.suggestName("fixed_macro")
  macroCell.io.CLK := owner.pins.CLK.asClock; macroCell.io.CEN := owner.pins.CEN
  macroCell.io.GWEN := owner.pins.GWEN; macroCell.io.WEN := owner.pins.WEN
  macroCell.io.A := owner.pins.A; macroCell.io.D := owner.pins.D; owner.pins.Q := macroCell.io.Q
}

class ClickMacroByteFixture(t: ByteModelTiming) extends AsyncModule(new ResetDomain("bootstrap")) {
  val request = twoPhaseInput("request", new SramByteRequest)
  val result = twoPhaseOutput("result", UInt(8.W))
  val stopRequest = IO(Input(Bool())); val rearm = IO(Input(Bool()))
  val sourceQuiescent = IO(Input(Bool()))
  val observe = IO(Output(new MacroByteObservations))
  val owner = asyncChild("byte_owner")(d => new ClickMacroByteOwner(d, t))
  owner.request.req := request.req; owner.request.bits := request.bits; request.ack := owner.request.ack
  result.req := owner.result.req; result.bits := owner.result.bits; owner.result.ack := result.ack
  owner.stopRequest := stopRequest; owner.rearm := rearm; owner.sourceQuiescent := sourceQuiescent
  observe := owner.observe
  val macroCell = Module(new Gf180Sram1KiB)
  macroCell.suggestName("fixed_macro")
  macroCell.io.CLK := owner.pins.CLK.asClock; macroCell.io.CEN := owner.pins.CEN
  macroCell.io.GWEN := owner.pins.GWEN; macroCell.io.WEN := owner.pins.WEN
  macroCell.io.A := owner.pins.A; macroCell.io.D := owner.pins.D; owner.pins.Q := macroCell.io.Q
}

/** Fresh compiler exports; the runner records one receipt for the complete run. */
object MacroByteCohort {
  def repository: Path = {
    var here = Paths.get("").toAbsolutePath.normalize()
    while (!Files.isRegularFile(here.resolve("build.sbt")) && here.getParent != null) here = here.getParent
    require(Files.isRegularFile(here.resolve("build.sbt")), "MACRO_BYTE_REPOSITORY_NOT_FOUND")
    here
  }
  def emit(destination: Path): Path = {
    val target = destination.toAbsolutePath.normalize()
    require(!Files.exists(target), s"MACRO_BYTE_EXPORT_MUST_BE_FRESH:$target")
    Files.createDirectories(target)
    val timing = ByteModelTiming()
    ExportDesign.emit(new FourPhaseMacroByteFixture(timing), target.resolve("bd"), ExportDesign.Debug)
    ExportDesign.emit(new ClickMacroByteFixture(timing), target.resolve("click"), ExportDesign.Debug)
    val jar = Path.of(classOf[chiselasync.primitives.Mutex].getProtectionDomain.getCodeSource.getLocation.toURI)
    require(Files.isRegularFile(jar), "MACRO_BYTE_EXPECTED_LIBRARY_JAR")
    Files.writeString(target.resolve("runtime.json"), ujson.write(ujson.Obj(
      "library_jar" -> jar.toAbsolutePath.toString, "parameters" -> timing.toString))+"\n")
    target
  }
}

/** Standalone Test/runMain emitter; the destination must not already exist. */
object EmitMacroByteFixtures extends App {
  require(args.length == 1, "usage: EmitMacroByteFixtures fresh-output-directory")
  println(MacroByteCohort.emit(Path.of(args(0))))
}
