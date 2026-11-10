// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3.RawModule
import riscay.clocked.ClockedExport
import java.nio.file.{Files, Path, Paths}
import java.util.concurrent.TimeUnit
import scala.jdk.CollectionConverters._

/** Ordinary clocked RTL, using the same Icarus backend as the SoC regressions. */
object SynchronousSimulation {
  def run(gen: => RawModule, name: String, testbench: String,
      timeoutSeconds: Int = 90): Path = {
    val root=Paths.get("build/clocked-tests").toAbsolutePath
    Files.createDirectories(root)
    val base=Files.createTempDirectory(root,name)
    ClockedExport.emit(gen,base)
    Files.writeString(base.resolve("testbench.sv"),testbench)
    val files=Files.list(base)
    val sources=try files.iterator.asScala.filter(p =>
      (p.toString.endsWith(".sv") || p.toString.endsWith(".v")) &&
        p.getFileName.toString != "testbench.sv").map(_.toString).toVector finally files.close()
    def command(args: Seq[String], log: String): Unit = {
      val path=base.resolve(log)
      val process=new ProcessBuilder(args:_*).directory(base.toFile)
        .redirectErrorStream(true).redirectOutput(path.toFile).start()
      if(!process.waitFor(timeoutSeconds,TimeUnit.SECONDS)) {
        process.destroyForcibly(); sys.error(s"Timeout: $path")
      }
      require(process.exitValue()==0,s"Simulation failure: $path\n${Files.readString(path).takeRight(5000)}")
    }
    command(Seq(sys.env.getOrElse("CA_IVERILOG","iverilog"),"-g2012","-s","Testbench","-o","sim.vvp") ++ sources ++ Seq("testbench.sv"),"compile.log")
    command(Seq(sys.env.getOrElse("CA_VVP","vvp"),"sim.vvp"),"simulation.log")
    require(Files.readString(base.resolve("simulation.log")).linesIterator.count(_ == "RISCAY_CLOCKED_PASS")==1,
      "MISSING_CLOCKED_COMPLETION")
    base
  }
}
