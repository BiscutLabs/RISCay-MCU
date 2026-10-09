// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._
import riscay.soc._

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
