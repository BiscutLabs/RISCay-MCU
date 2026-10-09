// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._
import chiselasync.core.AsyncModule
import riscay._

/** Watchdog recovery resets the application CPU and its transaction frontier.
  * Permanent power supervision, sensing and loader protection are POR-only. Release
  * into the service clock also delays Click startup; async assertion is immediate.
  */
abstract class SocTop(val p: SocParameters) extends AsyncModule {
  val serviceClock = IO(Input(Clock())); val watchdogClock = IO(Input(Clock()))
  val scl = IO(Input(Bool())); val sda = IO(Input(Bool())); val sdaLow = IO(Output(Bool()))
  val gpioIn = IO(Input(UInt(32.W))); val gpioOut = IO(Output(UInt(32.W))); val gpioOe = IO(Output(UInt(32.W)))
  val adcMiso = IO(Input(Bool())); val adcCsN = IO(Output(Bool())); val adcSclk = IO(Output(Bool()))
  val mode = IO(Output(UInt(3.W))); val programmed = IO(Output(Bool())); val locked = IO(Output(Bool()))
  val systemReset = IO(Output(Bool())); val resetReason = IO(Output(Bool()))
  val sleeping = IO(Output(Bool())); val sleepEntries = IO(Output(UInt(32.W)))
  val serviceClockEnable = IO(Output(Bool()))
  val trace = IO(Output(new Retirement)); val traceEvent = IO(Output(Bool()))
  val commit = IO(Output(Valid(new MemoryRequest)))
  contract.endpoint("system_reset", systemReset)
  contract.endpoint("reset_reason", resetReason)
  contract.endpoint("scl", scl); contract.endpoint("sda", sda); contract.endpoint("sda_low", sdaLow)
  // GPIO output/enable vectors can be constant or contain unused constant bits.
  // Their public ABI is in ports.json; they are not async timing endpoints.
  contract.endpoint("gpio_in", gpioIn)
  contract.endpoint("adc_miso", adcMiso); contract.endpoint("adc_csn", adcCsN); contract.endpoint("adc_sclk", adcSclk)
  contract.endpoint("mode", mode); contract.endpoint("programmed", programmed); contract.endpoint("locked", locked)
  contract.endpoint("trace_event", traceEvent)
  trace.elements.foreach { case (name, field) => contract.endpoint(s"trace_$name", field) }
  contract.endpoint("commit_valid", commit.valid)
  commit.bits.elements.foreach { case (name, field) => contract.endpoint(s"commit_$name", field) }
}
