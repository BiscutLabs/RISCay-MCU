// SPDX-License-Identifier: Apache-2.0
package riscay.physical

import chiselasync.metadata._
import java.nio.file.{Files, Path, Paths}
import java.security.MessageDigest
import riscay.bd.FourPhaseSoc
import riscay.click.ClickSoc
import riscay.profiles._
import riscay.soc._

/** Implementation targets, not measured delay claims. Physical checks must
  * establish these envelopes; ordinary simulation emitters keep their policy.
  */
object PhysicalTiming {
  private def ns(n: Int) = ModelTime.ps(n * 1000L)
  val control = DelayBounds(ns(1), ns(10), ns(1))
  val storage = DelayBounds(ModelTime.ps(100), ns(10), ns(1))
  val executeData = ns(180)
  def bd(data: Int): BundledTiming = BundledTiming.Digital(ns(data+9),
    DelayBounds.fixed(ns(data)), ControlDelays.uniform(control), storage, ns(31))
  val clickControl = DelayBounds(ModelTime.ps(1500), ns(10), ModelTime.ps(1500))
  val click = ClickTiming(ClickControlDelays(clickControl,clickControl,clickControl,clickControl,clickControl),
    storage, DelayBounds.fixed(ns(20)), ns(26), ns(36), ns(36),
    ns(5), ns(1), ModelTime.ps(1800), ns(2), ModelTime.ps(2500))
}

/** Export the controllers whose digital contracts are actually supported.
  * PhysicalTiming above remains a standalone core experiment; applying it to
  * the composed Click fabric is deliberately rejected by that fabric.
  * This export is physical-flow input, never a characterized timing policy.
  */
object PhysicalSocExport {
  val parameters = SocParameters(Groundlark.configuration, staleMs=3000, watchdogCycles=32,
    watchdogHoldCycles=2, adc=Some(AdcParameters(intervalCycles=10000000)),
    lowPower=Some(LowPowerParameters.gf180Slow))
  // Preserve the complete supervisor in implementation experiments. These
  // defaults are deliberately NOT a board-qualified battery/tapeout policy.
  private def board(p: SocParameters) = new GroundlarkBoard(p,PowerPolicy(enabled=true))
  private def sha(path: Path): String = MessageDigest.getInstance("SHA-256")
    .digest(Files.readAllBytes(path)).map(b => f"${b & 0xff}%02x").mkString

  def emit(root: Path): Unit = {
    require(!Files.exists(root), "PHYSICAL_EXPORT_ALREADY_EXISTS")
    val p = parameters
    Seq("bd", "click").foreach { variant =>
      val out = root.resolve(variant)
      // Keep verification bodies in their owning module. The mapper still
      // rejects arbitrary/extracted sources; SYNTHESIS removes assertions.
      ExportDesign.emit(chisel3.layer.elideBlocks {
        if(variant == "bd") new FourPhaseSoc(p,board)
        else new ClickSoc(p,board)
      },out)
      SramInventory.write(out,p.config)
      ChipWrapper.write(out,p.lowPower.get)
      Files.writeString(out.resolve("physical-policy.json"),ujson.write(ujson.Obj(
        "schema" -> "riscay-physical-policy-v3", "variant" -> variant,
        "purpose" -> "enabled evaluation fixture; not qualified for a battery or tapeout",
        "policy_enabled" -> true, "gpio_count" -> p.config.gpioCount,
        "service_max_hz" -> ApplicationResetContract.maximumServiceHz, "lf_max_hz" -> 12,
        "timing_policy" -> "current-supported-digital", "qualification" -> "unqualified",
        "timing_intent" -> "contract.json", "contract_sha256" -> sha(out.resolve("contract.json")),
        "ports_sha256" -> sha(out.resolve("ports.json")), "verification_layers" -> "inline",
        "application_reset" -> ujson.Obj(
          "qualifier_edges" -> ApplicationResetContract.qualifierEdges,
          "native_hold_edges" -> ApplicationResetContract.nativeHoldEdges,
          "native_release_edges" -> ApplicationResetContract.nativeReleaseEdges,
          "digital_delay_limit_fs" -> ApplicationResetContract.digitalDelayLimitFs.toString,
          "measured_local_guard_reset_max_fs" -> ApplicationResetContract.measuredLocalGuardResetMaxFs.toString,
          "minimum_native_hold_fs" -> ApplicationResetContract.minimumNativeHoldFs.toString,
          "minimum_native_release_fs" -> ApplicationResetContract.minimumNativeReleaseFs.toString,
          "qualification" -> "unqualified", "scope" -> "local-guard-margin-only")),indent=2)+"\n")
    }
  }
}

object EmitPhysical extends App {
  require(args.length == 1, "Usage: EmitPhysical new-output-directory")
  PhysicalSocExport.emit(Paths.get(args(0)).toAbsolutePath)
}
