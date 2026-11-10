// SPDX-License-Identifier: Apache-2.0
package riscay.desync

import chisel3._
import chisel3.util._
import riscay._
import riscay.soc._

/** Mode-0, 16-clock receive-only ADC (ADC121S021 framing). The first conversion
  * is discarded. All-zero and all-one samples are possible real voltages; SPI
  * has no CRC/ready signal and cannot itself detect a disconnected ADC.
  */
class ClockedSpiAdc(p: AdcParameters, autonomous: Boolean = true) extends Module {
  val io = IO(new Bundle {
    val miso = Input(Bool())
    val csN = Output(Bool())
    val sclk = Output(Bool())
    val result = Valid(new Acquisition)
    val allow = Input(Bool());val launched=Output(Bool())
    val start = Input(Bool()); val busy = Output(Bool()); val done = Output(Bool())
  })
  val active = RegInit(false.B)
  val sclk = RegInit(false.B)
  val divider = RegInit(0.U(log2Ceil(p.halfPeriodCycles).max(1).W))
  val interval = RegInit(0.U(log2Ceil(p.intervalCycles).W))
  val bit = RegInit(0.U(5.W))
  val shift = RegInit(0.U(16.W))
  val primed = RegInit(false.B)
  val scaler = Module(new ClockedSampleScaler(p.numerator, p.denominator))
  scaler.io.start := false.B; scaler.io.raw := shift(11,0)
  io.launched:=false.B
  io.csN := !active; io.sclk := sclk
  io.busy := active || scaler.io.busy; io.done := scaler.io.done
  io.result.valid := scaler.io.done && primed
  io.result.bits.value := (scaler.io.value + p.offset.S(32.W).asUInt)(31, 0)
  io.result.bits.valid := true.B
  io.result.bits.calibrated := p.calibrated.B
  when(scaler.io.done) { primed := true.B }
  when(!active && !scaler.io.busy) {
    when(io.allow && (if(autonomous) interval === 0.U else io.start)) {
      io.launched:=true.B;active := true.B; sclk := false.B; divider := 0.U; bit := 0.U
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
