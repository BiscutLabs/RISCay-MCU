// SPDX-License-Identifier: Apache-2.0
package riscay.clocked

import chisel3.RawModule
import circt.stage.ChiselStage
import java.nio.file.{Files, Path, Paths}

/** Ordinary synchronous RTL export; no async timing contract or primitive models. */
object ClockedExport {
  def emit(gen: => RawModule, directory: Path): Unit = {
    Files.createDirectories(directory)
    ChiselStage.emitSystemVerilogFile(chisel3.layer.elideBlocks(gen),
      args=Array("--target-dir", directory.toAbsolutePath.toString),
      firtoolOpts=Array("--disable-all-randomization", "--strip-fir-debug-info",
        "--lowering-options=disallowPortDeclSharing,disallowLocalVariables"))
  }
}
object EmitClockedCore extends App {
  require(args.length == 1, "Usage: EmitClockedCore output-directory")
  ClockedExport.emit(new ClockedCore, Paths.get(args(0)))
}
