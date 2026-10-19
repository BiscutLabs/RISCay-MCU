// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._

/** Conservative upper milliseconds: at least 116 wall years at the supported
  * 2.4x fastest/slowest LF ratio. Saturation makes every sample stale until POR.
  * Nominal MMIO time and deadlines retain their independent 32-bit ABI.
  */
object SampleTime {
  val Width=43
  val Maximum=(BigInt(1)<<Width)-1
}

/** POR-owned last-good sample. Time is conservative upper milliseconds, not
  * nominal MMIO time. Read conversion saturates; failed attempts retain stamp.
  */
class SampleRecord extends Bundle {
  val value=UInt(32.W); val timestamp=UInt(SampleTime.Width.W); val sequence=UInt(32.W)
  val valid=Bool(); val calibrated=Bool(); val seen=Bool(); val fault=Bool()
}
object SampleRecord {
  def initial: SampleRecord = (new SampleRecord).Lit(_.value -> 0.U, _.timestamp -> 0.U,
    _.sequence -> 0.U, _.valid -> false.B, _.calibrated -> false.B, _.seen -> false.B, _.fault -> false.B)
}
class SoftwareSampleCommit extends Bundle {
  val index=UInt(4.W); val value=UInt(32.W); val timestamp=UInt(SampleTime.Width.W)
}

/** Wire formats only. Native state transitions belong to each design. */
class TelemetryState(channels: Int, words: Int) extends Bundle {
  val output = UInt(32.W); val enable = UInt(32.W)
  val application = if(words > 0) Some(Vec(words, UInt(32.W))) else None
  val samples = if(channels > 0) Some(Vec(channels, new SampleRecord)) else None
}
object TelemetryState {
  def initial(p: SocParameters, words: Int): TelemetryState = {
    val sample = SampleRecord.initial
    val fields: Seq[TelemetryState => (Data, Data)] = Seq(
      _.output -> 0.U(32.W),
      _.enable -> 0.U(32.W))
    val application: Seq[TelemetryState => (Data, Data)] = if(words == 0) Seq.empty else
      Seq(_.application.get -> Vec.Lit((0 until words).map(_ => 0.U(32.W)): _*))
    val samples: Seq[TelemetryState => (Data, Data)] = if(p.softwareSampleChannels.isEmpty) Seq.empty else
      Seq(_.samples.get -> Vec.Lit(p.softwareSampleChannels.map(_ => sample): _*))
    (new TelemetryState(p.softwareSampleChannels.size, words)).Lit((fields ++ application ++ samples): _*)
  }
}
object TelemetryKind { val Commit = 1; val ResetApplication = 2 }
class TelemetryCommand(channels: Int) extends Bundle {
  val recovery = Bool()
  val kind = UInt(2.W)
  val offset = UInt(7.W); val data = UInt(32.W); val appIndex = UInt(6.W)
  val sample = if(channels > 0) Some(new SoftwareSampleCommit) else None
}
/** Periodic sender fields; immutable commit operands remain in Services until return. */
class TelemetryCommandHeader(channels: Int) extends Bundle {
  val recovery = Bool(); val kind = UInt(2.W)
}
class TelemetryCommitFields extends Bundle {
  val offset = UInt(7.W); val data = UInt(32.W); val appIndex = UInt(6.W)
}
class TelemetryReply(channels: Int, words: Int) extends Bundle {
  val recovery = Bool()
  val kind = UInt(2.W); val state = new TelemetryState(channels, words)
}
