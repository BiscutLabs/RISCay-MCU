// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import riscay.soc._

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance

/** Always-on reference domain. Registered Gray output changes one bit per tick.
  * Reset release is synchronized here; assertion is asynchronous at the parent.
  */
class SleepTimebase(p: LowPowerParameters) extends Module with InlineInstance {
  val io = IO(new Bundle { val gray = Output(UInt(32.W)) })
  val release = RegInit(3.U(2.W)); release := Cat(release(0), false.B)
  val divider = RegInit(0.U(log2Ceil(p.divider).max(1).W))
  val count = RegInit(0.U(32.W)); val gray = RegInit(0.U(32.W))
  when(!release.orR) {
    when(divider === (p.divider - 1).U) {
      divider := 0.U
      val next = count + 1.U
      count := next; gray := next ^ (next >> 1)
    }.otherwise { divider := divider + 1.U }
  }
  io.gray := gray
}

/** Event-set wake storage works with the service oscillator stopped. Async
  * assertion captures a wake; release affects counters only on service edges.
  * These flops need recovery/removal/placement checks in the physical flow.
  * A host wake probe buys a bounded retry window without another package pin.
  */
class ServiceClockWake extends Module with InlineInstance {
  val io = IO(new Bundle {
    val event = Input(Bool()); val scl = Input(Bool()); val sda = Input(Bool())
    val selected = Input(Bool()); val rejected = Input(Bool())
    val running = Input(Bool()); val enable = Output(Bool())
  })
  def hold(event: Bool, cycles: Int): Bool = withReset((reset.asBool || event).asAsyncReset) {
    val sync = RegInit(3.U(2.W)); sync := Cat(sync(0), false.B)
    val remaining = RegInit((cycles - 1).U(log2Ceil(cycles).W))
    when(!sync.orR && remaining =/= 0.U) { remaining := remaining - 1.U }
    sync.orR || remaining =/= 0.U
  }
  val eventHold = hold(io.event, 16)
  // SDA falling while SCL is high is a START, not a static bus-low level.
  // This small event-clocked frontier stays powered with the oscillator off.
  // Physical integration must constrain SCL setup/hold at the SDA event flop.
  val hostPhase = withClock((!io.sda).asClock) {
    val phase = RegInit(false.B)
    when(io.scl) { phase := !phase }
    phase
  }
  val host0 = RegNext(hostPhase, false.B); val host1 = RegNext(host0, false.B)
  val seen = RegInit(false.B)
  val remaining = RegInit(0.U(log2Ceil(LowPowerParameters.hostHoldCycles + 1).W))
  when(host1 =/= seen || io.selected) { remaining := LowPowerParameters.hostHoldCycles.U }
    .elsewhen(remaining =/= 0.U) { remaining := remaining - 1.U }
  seen := host1
  // An address for another target must not extend our retry window.
  when(io.rejected) { remaining := 0.U }
  io.enable := reset.asBool || io.event || eventHold || hostPhase =/= seen ||
    remaining =/= 0.U || io.running
}

/** Small ungated service-clock frontier. The Gray bus needs a physical skew
  * constraint (< one reference tick), in addition to synchronizer placement.
  * A falling-edge enable FF implements a complete-cycle clock gate in portable
  * RTL. ASIC integration must map/check this against the chosen gate cell.
  */
class RetainedClock extends Module with InlineInstance {
  val io = IO(new Bundle {
    val gray = Input(UInt(32.W)); val consumedGray = Input(UInt(32.W))
    val canSleep = Input(Bool()); val activity = Input(Bool()); val forceRun = Input(Bool())
    val synchronizedGray = Output(UInt(32.W))
    val running = Output(Bool()); val clockOut = Output(Clock())
    val entries = Output(UInt(32.W))
  })
  val first = RegNext(io.gray, 0.U); val second = RegNext(first, 0.U)
  io.synchronizedGray := second
  // Application reset can also change canSleep/activity through resettable
  // registers. Synchronize the complete demand before the falling-edge gate
  // FF; its input then has a normal half-cycle timing path.
  val demand = io.forceRun || !io.canSleep || io.activity || second =/= io.consumedGray
  val demandFirst = RegNext(demand, true.B)
  val needClock = RegNext(demandFirst, true.B)
  // Drain bridge/reset and host STOP pipelines before closing the clock gate.
  val grace = RegInit(7.U(3.W))
  when(needClock) { grace := 7.U }.elsewhen(grace =/= 0.U) { grace := grace - 1.U }
  val run = needClock || grace =/= 0.U || reset.asBool
  val enabled = withClock((!clock.asBool).asClock) { RegNext(run, true.B) }
  io.running := enabled
  io.clockOut := (clock.asBool && enabled).asClock
  val previous = RegNext(enabled, true.B)
  val entries = RegInit(0.U(32.W))
  when(previous && !enabled) { entries := entries + 1.U }
  io.entries := entries
}
