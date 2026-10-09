// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.experimental.BundleLiterals._
import riscay._

/** Wire schemas only. Each design owns its native transition/serialization logic. */
class HostFrame extends Bundle {
  val length = UInt(6.W)
  val overflow = Bool()
  val bytes = Vec(33, UInt(8.W))
}

class ControlState extends Bundle {
  val mode = UInt(3.W)
  val programmed = Bool(); val locked = Bool(); val started = Bool()
  val lastError = UInt(8.W)
  val imageLength = UInt(32.W); val entry = UInt(32.W); val received = UInt(32.W)
  val imageId = UInt(32.W); val expectedCrc = UInt(32.W); val crc = UInt(32.W)
  val loaderPending = Bool(); val loaderWord = UInt(32.W)
  val selector = UInt(24.W)
  val sampleIndex = UInt(4.W); val sampleValue = UInt(32.W); val appIndex = UInt(6.W)
}
object ControlState {
  def initial: ControlState = (new ControlState).Lit(
    _.mode -> 0.U, _.programmed -> false.B, _.locked -> false.B, _.started -> false.B,
    _.lastError -> 0.U, _.imageLength -> 0.U, _.entry -> 0.U, _.received -> 0.U,
    _.imageId -> 0.U, _.expectedCrc -> 0.U, _.crc -> "hffffffff".U,
    _.loaderPending -> false.B, _.loaderWord -> 0.U, _.selector -> 0.U,
    _.sampleIndex -> 0.U, _.sampleValue -> 0.U, _.appIndex -> 0.U)
}
object ControlKind {
  val Host = 0; val Stored = 1; val ResetApplication = 2; val Halt = 3; val Mmio = 4; val MmioCommit = 5
}
class ControlIngress extends Bundle {
  val frame = new HostFrame
  val resetActive = Bool(); val programBusy = Bool()
}
class ControlCommand extends Bundle {
  val kind = UInt(3.W)
  val frame = new HostFrame
  val cpuResetActive = Bool(); val programBusy = Bool()
  val memory = new MemoryRequest
  // Snapshot assembled at the clocked peripheral boundary. Loader-owned reads
  // use native state instead. Accepted effects route either to native Telemetry
  // commits or to the remaining clocked timer/peripheral owners.
  val peripheralData = UInt(32.W)
  val applicationWritable = Bool()
}
class ControlReply extends Bundle {
  val kind = UInt(3.W)
  val state = new ControlState
  val programWrite = Bool()
  // Raw candidate; it has no peripheral effect unless periodUpdate is asserted.
  val periodUpdate = Bool(); val period = UInt(32.W); val hostWake = Bool()
  val memory = new MemoryResponse
}
