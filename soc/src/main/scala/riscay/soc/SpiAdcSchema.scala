// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._

/** Static native-owned pin recipe, replayed LSB first at the wire boundary.
  * Each occupied slot has a CS/SCLK level and one retained MISO observation.
  */
class SpiWaveform extends Bundle {
  val initialCsN = Bool(); val initialSclk = Bool()
  val occupied = UInt(32.W); val csN = UInt(32.W); val sclk = UInt(32.W)
}
class SpiCapture extends Bundle { val samples = UInt(32.W); val complete = Bool() }
class SpiRaw extends Bundle { val primed = Bool(); val complete = Bool(); val raw = UInt(12.W) }
class SpiResult extends Bundle {
  val nextPrimed = Bool(); val publish = Bool()
  val sample = new SampleRecord
}
class SpiFinishWork extends Bundle {
  val raw=new SpiRaw; val scaled=UInt(32.W)
  val sample=new SampleRecord; val timestamp=UInt(SampleTime.Width.W)
}
/** ADC-facing service boundary. Cadence and elapsed-time provenance are external. */
class SpiAdcPort extends Bundle {
  val start = Input(Bool()); val upperTime = Input(UInt(SampleTime.Width.W))
  val busy = Output(Bool()); val done = Output(Bool())
  val result = Valid(new Acquisition)
  val sample = Output(new SampleRecord); val sampleReady = Output(Bool())
}
