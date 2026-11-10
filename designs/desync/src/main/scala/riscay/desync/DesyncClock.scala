// SPDX-License-Identifier: Apache-2.0
package riscay.desync

import chisel3._

/** One pausible fast region. Physical definitions come only from the registered
  * controller, measured mixed-cell delay, and qualified mutex recipes.
  * There is deliberately no synthesizable behavioral oscillator substitute.
  */
class DesyncClock extends RawModule {
  val reset = IO(Input(Bool()))
  val run = IO(Input(Bool()))
  val clockOut = IO(Output(Clock()))
  val controller = Module(new DesyncController)
  val delay = Module(new DesyncDelay)
  val mutex = Module(new DesyncMutex)
  controller.reset := reset
  controller.run := run
  controller.delayed := delay.out
  controller.cycleGrant := mutex.grant1
  controller.pauseGrant := mutex.grant0
  mutex.reset := reset
  mutex.request0 := controller.pauseRequest
  mutex.request1 := controller.cycleRequest
  delay.reset := reset
  delay.in := controller.clockOut
  clockOut := controller.clockOut.asClock
}

/** Controller contract: clock is the C-element of cycleGrant and !delayed;
  * cycleRequest is !reset && !clock. POR holds clock, pause state and BOTH
  * mutex requests low. Only after reset release may cycleRequest assert;
  * delayed clock feedback must settle before the first capture transition.
  * Pause requests persist until granted, even if run
  * changes while arbitration is unresolved. A wake releases the granted pause.
  * The existing wake frontier holds run through subsequent generated edges,
  * so the pause grant is low before another pause request is issued.
  * Only POR may abort a pulse; operational stopping completes the active pulse.
  * This interface is not a physical implementation or a timing qualification.
  */
class DesyncController extends ExtModule {
  override def desiredName = "RiscayDesyncController"
  val reset = IO(Input(Bool())); val run = IO(Input(Bool()))
  val delayed = IO(Input(Bool()))
  val cycleGrant = IO(Input(Bool())); val pauseGrant = IO(Input(Bool()))
  val clockOut = IO(Output(Bool()))
  val cycleRequest = IO(Output(Bool())); val pauseRequest = IO(Output(Bool()))
}

/** RELATIVE: one non-inverting matched delay in the oscillator feedback loop.
  * No RTL delay/count parameter. The mapper must read current STA evidence.
  * SRAM/POR/controller ABSOLUTE pulse obligations also constrain its final size.
  */
class DesyncDelay extends ExtModule {
  override def desiredName = "RiscayDesyncDelay"
  val reset = IO(Input(Bool()))
  val in = IO(Input(Bool())); val out = IO(Output(Bool()))
}

/** Analog arbitration with filtered grants. Never replace with priority logic.
  * The absent GF180 layout/LEF/Liberty remains a physical mapping error.
  */
class DesyncMutex extends ExtModule {
  override def desiredName = "RiscayDesyncMutex"
  val reset = IO(Input(Bool()))
  val request0 = IO(Input(Bool())); val request1 = IO(Input(Bool()))
  val grant0 = IO(Output(Bool())); val grant1 = IO(Output(Bool()))
}
