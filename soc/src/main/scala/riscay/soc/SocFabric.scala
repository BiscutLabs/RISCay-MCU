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
/** Shared port schema only; each variant owns its service implementation. */
abstract class ServiceEndpoint extends Module with InlineInstance {
  val io = IO(new Bundle {
    val program = new SramAccessPort
    val ram = new SramAccessPort
    val ramSource = new RamSourceBoundaryPort
    val programSource = new ProgramSourceBoundaryPort
    val elapsedScaling = Flipped(new ElapsedScalingPort(3))
    val adc = Flipped(new SpiAdcPort)
    val controlCommand = Decoupled(new ControlCommand)
    val controlReply = Flipped(Decoupled(new ControlReply))
    val request = Flipped(Decoupled(new MemoryRequest))
    val response = Decoupled(new MemoryResponse)
    val completionPlan = Decoupled(new CompletionPlan)
    val completionMemory = Decoupled(new MemoryResponse)
    val completionTelemetry = Decoupled(Bool())
    val completionHousekeeping = Decoupled(Bool())
    val completionResponse = Flipped(Decoupled(new MemoryResponse))
    val admissionGrant = Flipped(Decoupled(Bool()))
    val completionIdle = Input(Bool())
    val i2c = Flipped(new I2cHostPort)
    val gpioIn = Input(UInt(32.W)); val gpioOut = Output(UInt(32.W)); val gpioOe = Output(UInt(32.W))
    val watchdogReason = Input(Bool()); val heartbeat = Output(Bool())
    val watchdogAck = Input(Bool())
    val mode = Output(UInt(3.W)); val programmed = Output(Bool()); val locked = Output(Bool())
    val now = Output(UInt(32.W))
    val frontClock = Input(Clock())
    val cpuReset = Input(Bool())
    val cpuResetActive = Input(Bool())
    val crashCount = Input(UInt(32.W))
    val hostSelected = Output(Bool()); val hostRejected = Output(Bool())
    val hostFrameAccepted = Output(Bool())
    val timeGray = Input(UInt(32.W)); val consumedGray = Output(UInt(32.W))
    val clockRunning = Input(Bool()); val sleepEntries = Input(UInt(32.W))
    val canSleep = Output(Bool()); val activity = Output(Bool())
    val drainDemand = Output(Bool()); val telemetryDraining = Input(Bool())
    val boardDraining = Input(Bool()); val housekeepingDraining = Input(Bool())
    val observedGpio = Output(UInt(32.W))
    val commit = Valid(new MemoryRequest)
  })
}
