// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3.RawModule
import java.nio.file.Path

/** The exact same wire-level programs and assertions run on all chips. */
trait SocImplementationSuite {
  protected def synchronous: Boolean = false
  protected def generated: Boolean = false
  protected def variants: Seq[Boolean] = if(synchronous) Seq(false) else Seq(false,true)
  protected def run(gen: => chisel3.RawModule, name: String, body: String, extra: String = "",
      referenceHalfPeriodNs: Int = 163, onChipOscillator: Boolean = false,
      chipParameters: riscay.soc.LowPowerParameters = riscay.soc.LowPowerParameters(),
      serviceStartupNs: Int = 500, deadlineNs: Long = 100000000L,
      serviceModelHz: Double = 10000000, processTimeoutSeconds: Int = 90,
      serviceHalfPeriodNs: Double = 50, maximumDelaySubtree: Option[String] = None,
      primitiveDelayOverrides: Map[(String,String),Long] = Map.empty,
      powerOnResetNs: Long = 2000): Path = {
    ClockedSimulation.run(gen,name,body,extra,referenceHalfPeriodNs,onChipOscillator,chipParameters,serviceStartupNs,deadlineNs,serviceModelHz,processTimeoutSeconds,serviceHalfPeriodNs,maximumDelaySubtree,primitiveDelayOverrides,powerOnResetNs,synchronous,generated)
  }
}
