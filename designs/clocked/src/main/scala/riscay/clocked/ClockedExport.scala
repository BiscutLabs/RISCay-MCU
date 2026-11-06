// SPDX-License-Identifier: Apache-2.0
package riscay.clocked

import chisel3._
import chisel3.reflect.DataMirror
import circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}

/** Ordinary synchronous RTL export; no async timing contract or primitive models. */
object ClockedExport {
  def emit(gen: => RawModule, directory: Path): Unit = {
    require(!Files.exists(directory.resolve("filelist.f")),"CLOCKED_EXPORT_ALREADY_EXISTS")
    Files.createDirectories(directory)
    var module: RawModule = null
    ChiselStage.emitSystemVerilogFile(chisel3.layer.elideBlocks { module=gen; module },
      args=Array("--target-dir", directory.toAbsolutePath.toString),
      firtoolOpts=Array("--disable-all-randomization", "--strip-fir-debug-info",
        "--lowering-options=disallowPortDeclSharing,disallowLocalVariables"))
    val ports=scala.collection.mutable.ArrayBuffer.empty[ujson.Value]
    def visit(value: Data): Unit=value match {
      case r: Record => r.elements.values.foreach(visit)
      case v: Vec[_] => v.foreach(visit)
      case _ => ports += ujson.Obj("source" -> value.toTarget.serialize,"width" -> value.getWidth,
        "signed" -> value.isInstanceOf[SInt],"clock" -> value.isInstanceOf[Clock],
        "direction" -> DataMirror.directionOf(value).toString.toLowerCase)
    }
    DataMirror.modulePorts(module).foreach {case(_,data) => visit(data)}
    Files.writeString(directory.resolve("ports.json"),ujson.write(ujson.Obj("nodes" -> ujson.Arr(
      ujson.Obj("rtl_path" -> module.name,"module" -> module.name,"ports" -> ujson.Arr.from(ports)))),indent=2))
    val metadata=ujson.Obj("schema" -> "riscay-clocked-v1","top" -> module.name,
      "timing_qualified" -> false,"clocking" -> "synchronous")
    module match {
      case soc: riscay.soc.SocPorts =>
        metadata("gpio_count")=ujson.Num(soc.p.config.gpioCount)
        metadata("spi_boot")=ujson.Bool(soc.p.spiBoot)
        metadata("rom_bytes")=ujson.Num(soc.p.bootWords.size*4)
        metadata("program_bytes")=ujson.Num(soc.p.config.programBytes)
        metadata("ram_bytes")=ujson.Num(soc.p.config.workingRamBytes)
      case _ =>
    }
    Files.writeString(directory.resolve("clocked.json"),ujson.write(metadata,indent=2))
    val stream=Files.list(directory)
    val files=try {import scala.jdk.CollectionConverters._;stream.iterator.asScala.filter(p =>
      p.toString.endsWith(".sv") || p.toString.endsWith(".v")).map(_.getFileName.toString).toVector.sorted}
      finally stream.close()
    Files.writeString(directory.resolve("filelist.f"),files.mkString("\n")+"\n")
  }
}
object EmitClockedCore extends App {
  require(args.length == 1, "Usage: EmitClockedCore output-directory")
  ClockedExport.emit(new ClockedCore, Paths.get(args(0)))
}
