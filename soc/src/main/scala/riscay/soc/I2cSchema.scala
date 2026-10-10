// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._

/** Captured wire observations, not protocol state. Slots remain immutable until
  * the published native head returns through the service synchronizers.
  */
class I2cEdge extends Bundle {
  val rise = Bool(); val fall = Bool(); val start = Bool(); val stop = Bool()
  val timeout = Bool(); val sda = Bool()
  val readWord = UInt(32.W)
  val resetActive = Bool(); val programBusy = Bool(); val resetEpoch = UInt(64.W)
}
class I2cState extends Bundle {
  val head = UInt(4.W); val headGray = UInt(4.W)
  val mode = UInt(4.W); val active = Bool(); val rejected = Bool()
  val addressByte = Bool(); val selectedWrite = Bool()
  val receive = UInt(8.W); val bit = UInt(3.W)
  val drive = Bool(); val ack = Bool(); val reading = Bool(); val masterAck = Bool()
  val length = UInt(6.W); val overflow = Bool(); val bytes = Vec(33, UInt(8.W))
  val send = UInt(32.W); val sent = UInt(6.W)
}
object I2cState {
  def initial: I2cState = (new I2cState).Lit(
    _.head -> 0.U, _.headGray -> 0.U, _.mode -> 0.U, _.active -> false.B, _.rejected -> false.B,
    _.addressByte -> false.B, _.selectedWrite -> false.B, _.receive -> 0.U, _.bit -> 0.U,
    _.drive -> false.B, _.ack -> false.B, _.reading -> false.B, _.masterAck -> false.B,
    _.length -> 0.U, _.overflow -> false.B, _.bytes -> Vec.Lit(Seq.fill(33)(0.U(8.W)): _*),
    _.send -> 0.U, _.sent -> 0.U)
}
class I2cWork extends Bundle { val state = new I2cState; val edge = new I2cEdge }
class I2cFrame extends Bundle { val ingress = new ControlIngress; val resetEpoch = UInt(64.W) }
class I2cResult extends Bundle {
  val state = new I2cState
  val frameValid = Bool(); val frame = new I2cFrame
  val snapshotValid = Bool(); val snapshotTag = UInt(8.W)
}
/** Target-facing service boundary. The front clock owns publication only. */
class I2cHostPort extends Bundle {
  val frame = Valid(new ControlIngress)
  val readStart = Output(Bool()); val wordIndex = Output(UInt(4.W))
  val readWord = Input(UInt(32.W))
  val resetActive = Input(Bool()); val programBusy = Input(Bool())
  val busy = Output(Bool()); val selected = Output(Bool()); val rejected = Output(Bool())
}
