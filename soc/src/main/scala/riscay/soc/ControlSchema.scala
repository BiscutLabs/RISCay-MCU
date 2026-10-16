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

/** Internal loader storage only. Host fields are checked at their full
  * 32-bit width before assignment. Inclusive counts must represent capacity
  * itself, including a completed power-of-two-sized image.
  */
class ControlState(programBytes: Int) extends Bundle {
  require(programBytes > 0 && programBytes % 4 == 0)
  private val countWidth = BigInt(programBytes).bitLength
  private val entryWidth = (BigInt(programBytes) - 1).bitLength.max(1)
  val mode = UInt(3.W)
  val programmed = Bool(); val locked = Bool(); val started = Bool()
  val lastError = UInt(8.W)
  val imageLength = UInt(countWidth.W); val entry = UInt(entryWidth.W); val received = UInt(countWidth.W)
  val imageId = UInt(32.W); val expectedCrc = UInt(32.W); val crc = UInt(32.W)
  val loaderPending = Bool(); val loaderWord = UInt(32.W)
  val selector = UInt(24.W)
  val sampleIndex = UInt(4.W); val sampleValue = UInt(32.W); val appIndex = UInt(6.W)
}
object ControlState {
  def initial(programBytes: Int): ControlState = (new ControlState(programBytes)).Lit(
    _.mode -> 0.U, _.programmed -> false.B, _.locked -> false.B, _.started -> false.B,
    _.lastError -> 0.U, _.imageLength -> 0.U, _.entry -> 0.U, _.received -> 0.U,
    _.imageId -> 0.U, _.expectedCrc -> 0.U, _.crc -> "hffffffff".U,
    _.loaderPending -> false.B, _.loaderWord -> 0.U, _.selector -> 0.U,
    _.sampleIndex -> 0.U, _.sampleValue -> 0.U, _.appIndex -> 0.U)
}
/** Internal feedback token. The speculative CRC never appears in the public
  * loader state until an accepted Stored command commits it. */
class ControlToken(programBytes: Int) extends Bundle {
  val state = new ControlState(programBytes)
  val pendingCrc = UInt(32.W)
}
object ControlToken {
  def initial(programBytes: Int): ControlToken = (new ControlToken(programBytes)).Lit(
    _.state -> ControlState.initial(programBytes), _.pendingCrc -> "hffffffff".U)
}
/** Internal arithmetic input only; the state owner retains the loader context. */
class Crc32Command extends Bundle {
  val crc = UInt(32.W)
  val word = UInt(32.W)
  val pending = Bool()
}
object ControlKind {
  val Host = 0; val Stored = 1; val ResetApplication = 2; val Halt = 3; val Mmio = 4; val MmioCommit = 5
}
class ControlDescriptor extends Bundle {
  val bank = UInt(2.W)
  val resetActive = Bool()
  val programBusy = Bool()
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
class ControlReply(programBytes: Int) extends Bundle {
  val kind = UInt(3.W)
  val state = new ControlState(programBytes)
  val programWrite = Bool()
  // Raw candidate; it has no peripheral effect unless periodUpdate is asserted.
  val periodUpdate = Bool(); val period = UInt(32.W); val hostWake = Bool()
  val memory = new MemoryResponse
}
