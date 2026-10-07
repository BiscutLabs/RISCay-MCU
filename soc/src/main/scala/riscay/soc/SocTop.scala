// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._
import chiselasync.core.AsyncModule
import riscay._

/** Async contract root with a shared generated reset for all transaction state.
  * Only the watchdog lives in the outer, POR-only domain. Synchronous release
  * into the service clock also delays Click startup; async assertion is immediate.
  */
abstract class SocTop(val p: SocParameters, board: SocParameters => BoardController) extends AsyncModule {
  val serviceClock = IO(Input(Clock())); val watchdogClock = IO(Input(Clock()))
  val scl = IO(Input(Bool())); val sda = IO(Input(Bool())); val sdaLow = IO(Output(Bool()))
  val gpioIn = IO(Input(UInt(32.W))); val gpioOut = IO(Output(UInt(32.W))); val gpioOe = IO(Output(UInt(32.W)))
  val adcMiso = IO(Input(Bool())); val adcCsN = IO(Output(Bool())); val adcSclk = IO(Output(Bool()))
  val mode = IO(Output(UInt(3.W))); val programmed = IO(Output(Bool())); val locked = IO(Output(Bool()))
  val systemReset = IO(Output(Bool())); val resetReason = IO(Output(Bool()))
  val trace = IO(Output(new Retirement)); val traceEvent = IO(Output(Bool()))
  val commit = IO(Output(Valid(new MemoryRequest)))
  val watchdog = withClockAndReset(watchdogClock, reset) { Module(new Watchdog(p.watchdogCycles, p.watchdogHoldCycles)) }
  val assertion = reset.asBool || watchdog.io.expired
  val release = withClockAndReset(serviceClock, assertion.asAsyncReset) {
    val stages = RegInit(3.U(2.W)); stages := Cat(stages(0), false.B); stages
  }
  systemReset := assertion || release.orR
  resetReason := watchdog.io.reason
  protected val fabric = withClockAndReset(serviceClock, systemReset.asAsyncReset) { Module(new SocFabric(p, board)) }
  fabric.io.scl := scl; fabric.io.sda := sda; sdaLow := fabric.io.sdaLow
  fabric.io.gpioIn := gpioIn; gpioOut := fabric.io.gpioOut; gpioOe := fabric.io.gpioOe
  fabric.io.adcMiso := adcMiso; adcCsN := fabric.io.adcCsN; adcSclk := fabric.io.adcSclk
  fabric.io.watchdogReason := watchdog.io.reason; watchdog.io.heartbeat := fabric.io.heartbeat
  fabric.io.watchdogAck := watchdog.io.acknowledge
  mode := fabric.io.mode; programmed := fabric.io.programmed; locked := fabric.io.locked
  commit := fabric.io.commit
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
