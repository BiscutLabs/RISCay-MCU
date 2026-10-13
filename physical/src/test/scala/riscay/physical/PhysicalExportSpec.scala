// SPDX-License-Identifier: Apache-2.0
package riscay.physical

import chiselasync.metadata.ExportDesign
import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import org.scalatest.funsuite.AnyFunSuite
import riscay.click.ClickSoc
import scala.jdk.CollectionConverters._

class PhysicalExportSpec extends AnyFunSuite {
  private def sha(bytes: Array[Byte]) = MessageDigest.getInstance("SHA-256").digest(bytes)
    .map(b => f"${b & 0xff}%02x").mkString

  test("current physical exports retain supported contracts and inline assertions for both variants") {
    val parent=Paths.get("build/physical-export-tests").toAbsolutePath; Files.createDirectories(parent)
    val root=Files.createTempDirectory(parent,"current-").resolve("exports")
    PhysicalSocExport.emit(root)
    for((variant,top) <- Seq("bd" -> "FourPhaseSoc", "click" -> "ClickSoc")) {
      val out=root.resolve(variant)
      val policy=ujson.read(Files.readString(out.resolve("physical-policy.json")))
      assert(policy("schema").str == "riscay-physical-policy-v3")
      assert(policy("variant").str == variant && policy("policy_enabled").bool)
      assert(policy("timing_policy").str == "current-supported-digital")
      assert(policy("qualification").str == "unqualified")
      val resetPolicy=policy("application_reset")
      assert(policy("service_max_hz").num == 20000000)
      assert(resetPolicy("qualifier_edges").num == 8)
      assert(resetPolicy("native_hold_edges").num == 64 && resetPolicy("native_release_edges").num == 64)
      assert(resetPolicy("minimum_native_hold_fs").str == "3150000000")
      assert(resetPolicy("minimum_native_release_fs").str == "3150000000")
      assert(resetPolicy("digital_delay_limit_fs").str == "250000000")
      assert(resetPolicy("measured_local_guard_reset_max_fs").str == "1550000000")
      assert(resetPolicy("qualification").str == "unqualified" && resetPolicy("scope").str == "local-guard-margin-only")
      assert(!policy.obj.contains("native_reset_settlement_fs"))
      assert(policy("contract_sha256").str == sha(Files.readAllBytes(out.resolve("contract.json"))))
      assert(policy("ports_sha256").str == sha(Files.readAllBytes(out.resolve("ports.json"))))
      val manifest=ujson.read(Files.readString(out.resolve("contract.json")))("manifest")
      assert(manifest("top").str == top)
      val files=Files.readAllLines(out.resolve("filelist.f")).asScala.filter(_.trim.nonEmpty)
      assert(files.forall(name => out.resolve(name).normalize.getParent == out.normalize),
        "every registered source must resolve directly inside the export directory")
      val rtl=files.map(name => Files.readString(out.resolve(name))).mkString("\n")
      assert(rtl.contains("CONTROL_HOST_MAILBOX_OVERFLOW"), "original frame-admission assertion must remain inline")
      assert(rtl.contains("`ifndef SYNTHESIS"), "verification must remain excluded from synthesis")
      def nodes(n: ujson.Value): Seq[ujson.Value] = Seq(n) ++ n("children").arr.flatMap(c => nodes(c("contract")))
      val tree=nodes(manifest("design"))
      val fabric=tree.find(n => n("module").str == (if(variant=="bd") "FourPhaseFabric" else "ClickFabric")).get
      val guard=fabric("primitives").arr.find(_("id").str == "request_guard").get
      assert(guard("parameters")("DELAY_FS").str == "11000000")
      if(variant=="click") assert(!tree.exists(_("module").str.startsWith("FourPhase")), "Click must stay native")
    }
    val before=sha(Files.readAllBytes(root.resolve("bd/contract.json")))
    assert(intercept[IllegalArgumentException](PhysicalSocExport.emit(root)).getMessage.contains("PHYSICAL_EXPORT_ALREADY_EXISTS"))
    assert(sha(Files.readAllBytes(root.resolve("bd/contract.json"))) == before)
  }

  test("unsupported composed Click policy still rejects the old physical-core experiment") {
    val parent=Paths.get("build/physical-export-tests").toAbsolutePath; Files.createDirectories(parent)
    val root=Files.createTempDirectory(parent,"unsupported-click-")
    val error=intercept[IllegalArgumentException] {
      ExportDesign.emit(new ClickSoc(PhysicalSocExport.parameters, timing=PhysicalTiming.click,
        executeData=PhysicalTiming.executeData),root)
    }
    assert(error.getMessage.contains("CLICK_FABRIC_REQUIRES_SIMULATION_POLICY"),error.getMessage)
  }
}
