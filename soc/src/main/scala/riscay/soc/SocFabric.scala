// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._

object MemoryMap {
  val program = 0x10000000L
  val ram = 0x20000000L
  val mmio = 0x30000000L
  // lui x1,0x30000; lw x2,0(x1) (wait for START); jalr x0,x2,0
  val boot = Vector(0x300000b7L, 0x0000a103L, 0x00010067L)
}
object ImageCrc {
  // CRC-32/ISO-HDLC, init ffffffff, reflected 04c11db7, xorout ffffffff.
  def word(previous: UInt, data: UInt): UInt = {
    var result = previous
    for (i <- 0 until 32) {
      result = (result >> 1) ^ Mux(result(0) ^ data(i), "hedb88320".U(32.W), 0.U(32.W))
    }
    result
  }
}

/** Shared port schema only; each variant owns its service implementation. */
abstract class ServiceEndpoint extends Module with InlineInstance {
  val io = IO(new Bundle {
    val request = Flipped(Decoupled(new MemoryRequest))
    val response = Decoupled(new MemoryResponse)
    val scl = Input(Bool()); val sda = Input(Bool()); val sdaLow = Output(Bool())
    val gpioIn = Input(UInt(32.W)); val gpioOut = Output(UInt(32.W)); val gpioOe = Output(UInt(32.W))
    val adcMiso = Input(Bool()); val adcCsN = Output(Bool()); val adcSclk = Output(Bool())
    val watchdogReason = Input(Bool()); val heartbeat = Output(Bool())
    val watchdogAck = Input(Bool())
    val mode = Output(UInt(3.W)); val programmed = Output(Bool()); val locked = Output(Bool())
    val now = Output(UInt(32.W))
    val frontClock = Input(Clock())
    val cpuReset = Input(Bool())
    val cpuResetActive = Input(Bool())
    val crashCount = Input(UInt(32.W))
    val hostSelected = Output(Bool()); val hostRejected = Output(Bool())
    val timeGray = Input(UInt(32.W)); val consumedGray = Output(UInt(32.W))
    val clockRunning = Input(Bool()); val sleepEntries = Input(UInt(32.W))
    val canSleep = Output(Bool()); val activity = Output(Bool())
    val observedGpio = Output(UInt(32.W))
    val commit = Valid(new MemoryRequest)
  })
}
