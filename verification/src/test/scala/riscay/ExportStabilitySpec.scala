// SPDX-License-Identifier: Apache-2.0
package riscay

import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc.SocParameters

class ExportStabilitySpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(32,32,7,Vector.empty,
    ApplicationProfile(1,1,"export-stability",
      Vector(0,2,7,11,31,63).map(i => HostRegister(i,s"WORD_$i")),Vector.empty)))

  private def contents(directory: Path, metadata: String): Map[String,String] = {
    val files=Files.readString(directory.resolve("filelist.f")).linesIterator.filter(_.nonEmpty).toVector
    assert(files.nonEmpty,"EMPTY_EXPORT")
    (files ++ Vector("filelist.f","ports.json",metadata)).map { name =>
      name -> Files.readString(directory.resolve(name))
    }.toMap
  }

  test("clocked repeated elaboration preserves every exported RTL and interface file") {
    val root=Paths.get("build/export-stability");Files.createDirectories(root)
    val exports=(0 until 3).map { _ =>
      val directory=Files.createTempDirectory(root,"clocked")
      riscay.clocked.ClockedExport.emit(new riscay.clocked.ClockedFabric(p),directory)
      contents(directory,"clocked.json")
    }
    for(candidate <- exports.tail) {
      val changed=(exports.head.keySet ++ candidate.keySet).filter(k => exports.head.get(k)!=candidate.get(k))
      assert(changed.isEmpty,s"NONDETERMINISTIC_EXPORT: ${changed.toVector.sorted.mkString(",")}")
    }
  }
}
