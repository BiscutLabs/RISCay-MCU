// SPDX-License-Identifier: Apache-2.0
// One exact fixed macro per isolated native owner; no production wiring.
package riscay

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ExportDesign
import riscay.soc.{Gf180Sram1KiB, SramByteRequest}
import java.nio.file.{Files, Path, Paths}
import java.nio.charset.StandardCharsets.UTF_8
import java.security.MessageDigest
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

/** Fresh generation and resolved runtime class-file identity; not loaded-bytecode attestation. */
object MacroByteCohort {
  val sourceFiles = Vector(
    "build.sbt",
    "designs/four-phase-bd/src/main/scala/riscay/bd/experimental/FourPhaseMacroByteOwner.scala",
    "designs/two-phase-click/src/main/scala/riscay/click/experimental/ClickMacroByteOwner.scala",
    "soc/src/main/scala/riscay/soc/experimental/MacroByteSchema.scala",
    "soc/src/main/scala/riscay/soc/Sram.scala",
    "soc/sram-lock.json",
    "soc/src/main/resources/riscay/sram/gf180mcu_ocd_ip_sram__sram1024x8m8wm1.v",
    "soc/src/main/resources/riscay/sram/gf180mcu_ocd_ip_sram__sram1024x8m8wm1.blackbox.v",
    "verification/src/test/scala/riscay/MacroByteFixtures.scala",
    "verification/src/test/scala/riscay/AsyncMacroByteOwnerSpec.scala",
    "verification/src/test/resources/riscay/macro-byte/ByteOwnerBench.sv.in",
    "verification/src/test/resources/riscay/macro-byte/PinAperture.sv",
    "tools/check_macro_byte_owner.py",
    "tools/macro_byte_source_binding.py")
  private val classSources = Vector(
    "riscay.bd.experimental.FourPhaseMacroByteOwner" -> sourceFiles(1),
    "riscay.click.experimental.ClickMacroByteOwner" -> sourceFiles(2),
    "riscay.soc.experimental.MacroBytePins" -> sourceFiles(3),
    "riscay.soc.experimental.MacroByteObservations" -> sourceFiles(3),
    "riscay.soc.experimental.ByteModelTiming" -> sourceFiles(3),
    "riscay.soc.Gf180Sram1KiB" -> sourceFiles(4),
    "riscay.soc.Gf180Sram1KiB$$anon$1" -> sourceFiles(4),
    "riscay.soc.SramByteRequest" -> sourceFiles(4),
    "riscay.soc.SramInventory" -> sourceFiles(4),
    "riscay.soc.SramInventory$" -> sourceFiles(4),
    "riscay.FourPhaseMacroByteFixture" -> sourceFiles(8),
    "riscay.ClickMacroByteFixture" -> sourceFiles(8),
    "riscay.MacroByteCohort$" -> sourceFiles(8),
    "riscay.EmitMacroByteFixtures$" -> sourceFiles(8),
    "riscay.AsyncMacroByteOwnerSpec" -> sourceFiles(9))
  def repository: Path = {
    var here = Paths.get("").toAbsolutePath.normalize()
    while (!Files.isRegularFile(here.resolve("build.sbt")) && here.getParent != null) here = here.getParent
    require(Files.isRegularFile(here.resolve("build.sbt")), "MACRO_BYTE_REPOSITORY_NOT_FOUND")
    here
  }
  private def hash(path: Path): String = MessageDigest.getInstance("SHA-256")
    .digest(Files.readAllBytes(path)).map(b => f"${b & 0xff}%02x").mkString
  private def jsonMillis(value: Long): ujson.Num = {
    require(value >= 0L && value <= 9007199254740991L, "MACRO_BYTE_TIMESTAMP_NOT_EXACT_JSON_NUMBER")
    ujson.Num(value.toDouble)
  }
  private def sources(root: Path): ujson.Obj = ujson.Obj.from(sourceFiles.map { relative =>
    val path = root.resolve(relative)
    require(Files.isRegularFile(path), s"MACRO_BYTE_MISSING_SOURCE:$relative")
    relative -> ujson.Obj("sha256" -> hash(path), "modified_ms" -> jsonMillis(Files.getLastModifiedTime(path).toMillis))
  })
  private def runtimeClasses(root: Path): ujson.Arr = {
    val rows = classSources.flatMap { case(name, source) =>
      val names = if(name.endsWith("$") || classSources.exists(_._1 == name+"$")) Vector(name) else Vector(name, name+"$")
      names.zipWithIndex.flatMap { case(className, index) =>
        val resource = Option(getClass.getResource("/"+className.replace('.', '/')+".class"))
        require(index != 0 || resource.nonEmpty, s"MACRO_BYTE_MISSING_RUNTIME_CLASS:$className")
        resource.map { url =>
          require(url.getProtocol == "file", s"MACRO_BYTE_PROJECT_CLASS_NOT_FILE:$className")
          val path = Path.of(url.toURI).toAbsolutePath.normalize()
          require(path.startsWith(root), s"MACRO_BYTE_CLASS_OUTSIDE_REPOSITORY:$className")
          require(Files.getLastModifiedTime(path).toMillis >= Files.getLastModifiedTime(root.resolve(source)).toMillis,
            s"MACRO_BYTE_SOURCE_NEWER_THAN_COMPILED_CLASS:$className")
          ujson.Obj("name" -> className, "source" -> source, "path" -> path.toString,
            "sha256" -> hash(path), "modified_ms" -> jsonMillis(Files.getLastModifiedTime(path).toMillis))
        }
      }
    }
    // Explicit used SRAM families, including anonymous/companion class files.
    // A new family member requires review and a classSources entry.
    Vector("Gf180Sram1KiB", "SramByteRequest", "SramInventory").foreach { family =>
      val primary = rows.find(_("name").str == "riscay.soc."+family).get
      val folder = Path.of(primary("path").str).getParent
      val stream = Files.list(folder)
      val actual = try {
        import scala.jdk.CollectionConverters._
        stream.iterator().asScala.map(_.getFileName.toString).filter { name =>
          name == family+".class" || (name.startsWith(family+"$") && name.endsWith(".class"))
        }.map(_.stripSuffix(".class")).toSet
      } finally stream.close()
      val recorded = rows.map(_("name").str).filter { name =>
        name == "riscay.soc."+family || name.startsWith("riscay.soc."+family+"$")
      }.map(_.stripPrefix("riscay.soc.")).toSet
      require(rows.filter(row => recorded.contains(row("name").str.stripPrefix("riscay.soc.")))
        .forall(row => Path.of(row("path").str).getParent == folder),
        s"MACRO_BYTE_SRAM_CLASS_FAMILY_LOCATION:$family")
      require(actual == recorded, s"MACRO_BYTE_SRAM_CLASS_FAMILY_INVENTORY:$family")
    }
    ujson.Arr.from(rows)
  }
  def emit(destination: Path): Path = {
    val root = repository; val target = destination.toAbsolutePath.normalize()
    require(!Files.exists(target), s"MACRO_BYTE_EXPORT_MUST_BE_FRESH:$target")
    Files.createDirectories(target)
    val started = System.currentTimeMillis()
    val before = sources(root); val classes = runtimeClasses(root)
    require(before.value.values.forall(_("modified_ms").num <= started), "MACRO_BYTE_SOURCE_AFTER_GENERATION_START")
    val jar = Path.of(classOf[chiselasync.primitives.Mutex].getProtectionDomain.getCodeSource.getLocation.toURI)
    require(Files.isRegularFile(jar) && jar.toString.endsWith(".jar"), "MACRO_BYTE_EXPECTED_PINNED_LIBRARY_JAR")
    val jarHash = hash(jar)
    val record = ujson.Obj("schema" -> "riscay-experimental-macro-byte-cohort-v1", "status" -> "CAPTURED",
      "started_ms" -> jsonMillis(started), "sources" -> before, "runtime_classes" -> classes,
      "library_jar" -> ujson.Obj("path" -> jar.toAbsolutePath.toString, "sha256" -> jarHash))
    Files.writeString(target.resolve("source-manifest.json"), ujson.write(record, indent=2)+"\n", UTF_8)
    val timing = ByteModelTiming()
    ExportDesign.emit(new FourPhaseMacroByteFixture(timing), target.resolve("bd"), ExportDesign.Debug)
    ExportDesign.emit(new ClickMacroByteFixture(timing), target.resolve("click"), ExportDesign.Debug)
    require(before == sources(root), "MACRO_BYTE_SOURCES_CHANGED_DURING_EMISSION")
    require(classes == runtimeClasses(root) && jarHash == hash(jar), "MACRO_BYTE_RUNTIME_CHANGED_DURING_EMISSION")
    record("exports") = ujson.Obj.from(Vector("bd", "click").map { variant =>
      variant -> ujson.read(Files.readString(target.resolve(s"$variant/contract.json")))("semantic_sha256")
    })
    record("parameters") = timing.toString
    record("finished_ms") = jsonMillis(System.currentTimeMillis())
    record("status") = "COMPLETE"
    Files.writeString(target.resolve("source-manifest.json"), ujson.write(record, indent=2)+"\n", UTF_8)
    target
  }
}

/** Standalone Test/runMain emitter; the destination must not already exist. */
object EmitMacroByteFixtures extends App {
  require(args.length == 1, "usage: EmitMacroByteFixtures fresh-output-directory")
  println(MacroByteCohort.emit(Path.of(args(0))))
}
