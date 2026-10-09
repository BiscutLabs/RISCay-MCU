// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._

final case class SocParameters(config: McuConfiguration, serviceHz: Int = 10000000,
    i2cAddress: Int = 0x35, staleMs: Int = 100, watchdogCycles: Int = 32768,
    watchdogHoldCycles: Int = 8, adc: Option[AdcParameters] = None,
    lowPower: Option[LowPowerParameters] = None, i2cIdleCycles: Int = 262144) {
  require(serviceHz >= 1000 && serviceHz % 1000 == 0)
  require(i2cAddress >= 8 && i2cAddress < 120)
  require(i2cIdleCycles >= 256)
  require(staleMs > 0 && watchdogCycles > watchdogHoldCycles + 4 && watchdogHoldCycles >= 2)
  require(adc.isEmpty || config.measurements.nonEmpty)
  lowPower.foreach { _ => adc.foreach { a =>
    require(defaultSampleMs >= minimumSampleMs && defaultSampleMs <= maximumSampleMs,
      "sample period must accommodate conversion and leave freshness margin")
  } }
  def defaultSampleMs: Int = adc.map(a => ((a.intervalCycles.toLong * 1000 + serviceHz - 1) / serviceHz).toInt).getOrElse(0)
  // Digital completion/drainage budget: SPI framing, <=16 frontier edges and
  // <=1 us for the native sample pipeline under the declared simulation bounds.
  // Physical qualification must replace the native allowance with measured bounds.
  def conversionMs: Int = adc.map(a => math.ceil(
    (32L * a.halfPeriodCycles + 16) * 1000.0 / serviceHz + 0.001).toInt).getOrElse(0)
  def minimumSampleMs: Int = conversionMs + 2 * lowPower.map(_.quantumMs).getOrElse(1)
  def maximumSampleMs: Int = lowPower.map { lp =>
    math.floor((staleMs - math.max(0, conversionMs - 1) - 2 * lp.maximumQuantumMs) * lp.slowestHz / lp.referenceHz).toInt
  }.getOrElse(staleMs - 2)
  def freshLimitMs: Int = staleMs - lowPower.map(lp => math.max(0, lp.maximumQuantumMs - 1)).getOrElse(0)
}
/** The nominal time unit is a millisecond, subject to the physical oscillator's
  * characterized error. A finite lease prevents a forgotten WAIT from petting
  * the application watchdog indefinitely.
  */
final case class LowPowerParameters(referenceHz: Double = 4000, maximumSleepMs: Int = 60000,
    minimumHz: Double = 0, maximumHz: Double = 0, stopServiceClock: Boolean = false) {
  require(referenceHz.isFinite && referenceHz >= 1 && referenceHz <= 1000000)
  require(referenceHz < 1000 || referenceHz % 1000 == 0)
  val slowestHz: Double = if(minimumHz == 0) referenceHz else minimumHz
  val fastestHz: Double = if(maximumHz == 0) referenceHz else maximumHz
  require(slowestHz.isFinite && fastestHz.isFinite && slowestHz >= 1 && slowestHz <= referenceHz && fastestHz >= referenceHz)
  val divider: Int = math.max(1, (referenceHz / 1000).toInt)
  val tickMicros: Int = math.round(1000000.0 * divider / referenceHz).toInt
  val minimumTickMicros: Int = math.floor(1000000.0 * divider / fastestHz).toInt
  val maximumTickMicros: Int = math.ceil(1000000.0 * divider / slowestHz).toInt
  require(minimumTickMicros > 0)
  val quantumMs: Int = (tickMicros + 999) / 1000
  val maximumQuantumMs: Int = (maximumTickMicros + 999) / 1000
  require(maximumSleepMs > 0 && maximumSleepMs < 0x40000000)
}
object LowPowerParameters {
  // Guarded engineering envelope around the schematic PVT results, not silicon qualification.
  val gf180Slow = LowPowerParameters(referenceHz=7.7307, minimumHz=5, maximumHz=12, stopServiceClock=true)
  val hostWakeWaitUs = 100
  val hostHoldCycles = 4096
}
final case class AdcParameters(halfPeriodCycles: Int = 5, intervalCycles: Int = 100000,
    numerator: Int = 25300, denominator: Int = 4095, offset: Int = 0,
    calibrated: Boolean = false) {
  require(halfPeriodCycles >= 2 && intervalCycles > 40 * halfPeriodCycles)
  require(numerator > 0 && numerator < 1000000 && denominator > 0)
}

class Sample extends Bundle {
  val value = UInt(32.W)
  val valid = Bool()
  val calibrated = Bool()
  val age = UInt(32.W)
  val sequence = UInt(32.W)
  val never = Bool()
  val fault = Bool()
}
class Acquisition extends Bundle {
  val value = UInt(32.W)
  val valid = Bool()
  val calibrated = Bool()
}
/** Immutable board binding; runtime controllers belong to each native design. */
abstract class BoardProfile(val parameters: SocParameters) {
  def ownedRegisters: Set[Int] = Set.empty
  def mask: BigInt = 0
  def enables: BigInt = 0
}
class GenericBoard(p: SocParameters) extends BoardProfile(p)
