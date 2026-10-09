// SPDX-License-Identifier: Apache-2.0
package riscay.physical

import chiselasync.metadata._
import java.nio.file.{Files, Paths}
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

object EmitPhysical extends App {
  require(args.length == 1, "Usage: EmitPhysical new-output-directory")
  val root = Paths.get(args(0)).toAbsolutePath
  require(!Files.exists(root), "PHYSICAL_EXPORT_ALREADY_EXISTS")
  val p = SocParameters(Groundlark.configuration, staleMs=3000, watchdogCycles=32,
    watchdogHoldCycles=2, adc=Some(AdcParameters(intervalCycles=10000000)),
    lowPower=Some(LowPowerParameters.gf180Slow))
  // Preserve the complete supervisor in implementation experiments. These
  // defaults are deliberately NOT a board-qualified battery/tapeout policy.
  def board(p: SocParameters) = new GroundlarkBoard(p,PowerPolicy(enabled=true))
  Seq("bd", "click").foreach { variant =>
    val out = root.resolve(variant)
    if(variant == "bd") ExportDesign.emit(new FourPhaseSoc(p,board,
      PhysicalTiming.bd(20),PhysicalTiming.bd(180)),out)
    else ExportDesign.emit(new ClickSoc(p,board,PhysicalTiming.click,PhysicalTiming.executeData),out)
    SramInventory.write(out,p.config)
    ChipWrapper.write(out,p.lowPower.get)
    Files.writeString(out.resolve("physical-policy.json"),ujson.write(ujson.Obj(
      "schema" -> "riscay-physical-policy-v1", "variant" -> variant,
      "purpose" -> "enabled evaluation fixture; not qualified for a battery or tapeout",
      "policy_enabled" -> true, "gpio_count" -> p.config.gpioCount,
      "service_max_hz" -> 20000000, "lf_max_hz" -> 12,
      "control_min_ns" -> (if(variant=="click") 1.5 else 1.0), "control_max_ns" -> 10,
      "data_max_ns" -> 20, "execute_data_max_ns" -> 180,
      "register_writeback_guard_ns" -> 31,
      "latch_setup_ns" -> 8, "click_setup_ns" -> 5,
      "click_hold_ns" -> 1, "click_high_ns" -> 1.8,
      "click_low_ns" -> 2, "click_clock_skew_ns" -> 2.5),indent=2)+"\n")
  }
}
