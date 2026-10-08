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
  def conversionMs: Int = adc.map(a => (((32L * a.halfPeriodCycles + 12) * 1000 + serviceHz - 1) / serviceHz).toInt).getOrElse(0)
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
class BoardIO(p: SocParameters) extends Bundle {
  val tick = Input(Bool())
  val now = Input(UInt(32.W))
  val observationMs = Input(UInt(32.W))
  val gpio = Input(UInt(32.W))
  val samples = Input(Vec(p.config.measurements.size, new Sample))
  val mask = Output(UInt(32.W))
  val outputs = Output(UInt(32.W))
  val enables = Output(UInt(32.W))
  val registers = Output(Vec(64, UInt(32.W)))
}
abstract class BoardController(p: SocParameters) extends Module with InlineInstance {
  /** Static ownership permits removing software storage for hardware telemetry. */
  def ownedRegisters: Set[Int] = Set.empty
  val io = IO(new BoardIO(p))
}
class GenericBoard(p: SocParameters) extends BoardController(p) {
  io.mask := 0.U; io.outputs := 0.U; io.enables := 0.U
  io.registers := VecInit(Seq.fill(64)(0.U(32.W)))
}

/** Independent reference clock. A timeout asserts application reset for a
  * bounded interval, including the CPU and its bus endpoints, not power policy.
  * Reason is retained in this POR-only domain until external reset.
  */
class Watchdog(limit: Int, holdCycles: Int) extends Module with InlineInstance {
  val io = IO(new Bundle {
    val heartbeat = Input(Bool())
    val expired = Output(Bool())
    val reason = Output(Bool())
    val acknowledge = Output(Bool())
  })
  val sync = RegInit(0.U(2.W)); sync := Cat(sync(0), io.heartbeat)
  val seen = RegInit(false.B)
  val count = RegInit(0.U(log2Ceil(limit + 1).W))
  val hold = RegInit(0.U(log2Ceil(holdCycles + 1).W))
  val reason = RegInit(false.B)
  when(hold =/= 0.U) { hold := hold - 1.U; count := 0.U; seen := sync(1) }
    .elsewhen(sync(1) =/= seen) { seen := sync(1); count := 0.U }
    .elsewhen(count === (limit - 1).U) { hold := holdCycles.U; reason := true.B; count := 0.U }
    .otherwise { count := count + 1.U }
  io.expired := hold =/= 0.U
  io.reason := reason
  io.acknowledge := seen
}

/** Mode-0, 16-clock receive-only ADC (ADC121S021 framing). The first conversion
  * is discarded. All-zero and all-one samples are possible real voltages; SPI
  * has no CRC/ready signal and cannot itself detect a disconnected ADC.
  */
class SpiAdc(p: AdcParameters, autonomous: Boolean = true) extends Module with InlineInstance {
  val io = IO(new Bundle {
    val miso = Input(Bool())
    val csN = Output(Bool())
    val sclk = Output(Bool())
    val result = Valid(new Acquisition)
    val start = Input(Bool()); val busy = Output(Bool()); val done = Output(Bool())
  })
  val active = RegInit(false.B)
  val sclk = RegInit(false.B)
  val divider = RegInit(0.U(log2Ceil(p.halfPeriodCycles).max(1).W))
  val interval = RegInit(0.U(log2Ceil(p.intervalCycles).W))
  val bit = RegInit(0.U(5.W))
  val shift = RegInit(0.U(16.W))
  val primed = RegInit(false.B)
  val scaler = Module(new SampleScaler(p.numerator, p.denominator))
  scaler.io.start := false.B; scaler.io.raw := shift(11,0)
  io.csN := !active; io.sclk := sclk
  io.busy := active || scaler.io.busy; io.done := scaler.io.done
  io.result.valid := scaler.io.done && primed
  io.result.bits.value := (scaler.io.value + p.offset.S(32.W).asUInt)(31, 0)
  io.result.bits.valid := true.B
  io.result.bits.calibrated := p.calibrated.B
  when(scaler.io.done) { primed := true.B }
  when(!active && !scaler.io.busy) {
    when(if(autonomous) interval === 0.U else io.start) {
      active := true.B; sclk := false.B; divider := 0.U; bit := 0.U
      interval := (p.intervalCycles - 1).U
    }.otherwise { interval := interval - 1.U }
  }.elsewhen(active) {
    when(divider === (p.halfPeriodCycles - 1).U) {
      divider := 0.U; sclk := !sclk
      when(!sclk) { shift := Cat(shift(14, 0), io.miso) }
        .otherwise {
          when(bit === 15.U) {
            active := false.B; sclk := false.B; scaler.io.start := true.B
          }.otherwise { bit := bit + 1.U }
        }
    }.otherwise { divider := divider + 1.U }
  }
}
