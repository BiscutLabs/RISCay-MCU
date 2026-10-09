// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._

/** Wire formats only. Native state transitions belong to each design. */
class TelemetryState(channels: Int, words: Int) extends Bundle {
  val output = UInt(32.W); val enable = UInt(32.W); val pending = UInt(6.W)
  val application = if(words > 0) Some(Vec(words, UInt(32.W))) else None
  val samples = if(channels > 0) Some(Vec(channels, new Sample)) else None
}
object TelemetryState {
  def initial(p: SocParameters, words: Int): TelemetryState = {
    val sample = (new Sample).Lit(_.value -> 0.U, _.valid -> false.B, _.calibrated -> false.B,
      _.age -> 0.U, _.sequence -> 0.U, _.never -> true.B, _.fault -> false.B)
    val fields: Seq[TelemetryState => (Data, Data)] = Seq(
      _.output -> p.config.application.pins.filter(_.resetHigh).map(x => BigInt(1) << x.index).sum.U(32.W),
      _.enable -> p.config.application.pins.filter(_.output).map(x => BigInt(1) << x.index).sum.U(32.W),
      _.pending -> 0.U)
    val application: Seq[TelemetryState => (Data, Data)] = if(words == 0) Seq.empty else
      Seq(_.application.get -> Vec.Lit((0 until words).map(_ => 0.U(32.W)): _*))
    val samples: Seq[TelemetryState => (Data, Data)] = if(p.config.measurements.isEmpty) Seq.empty else
      Seq(_.samples.get -> Vec.Lit(p.config.measurements.indices.map(_ => sample): _*))
    (new TelemetryState(p.config.measurements.size, words)).Lit((fields ++ application ++ samples): _*)
  }
}
/** Lossless compaction of publications while a native command is backpressured.
  * Count wraps exactly like the ABI sequence. Last successful value and its age
  * are independent of the latest attempt's status.
  */
class TelemetryCapture extends Bundle {
  val seen = Bool(); val count = UInt(32.W); val hadValid = Bool()
  val valid = Bool(); val calibrated = Bool(); val value = UInt(32.W); val tailAge = UInt(32.W)
}
object TelemetryKind { val Observe = 0; val Commit = 1; val ResetApplication = 2 }
class TelemetryCommand(channels: Int) extends Bundle {
  val kind = UInt(2.W); val events = UInt(6.W); val clear = UInt(6.W)
  val elapsedUpper = UInt(32.W)
  val offset = UInt(7.W); val data = UInt(32.W); val appIndex = UInt(6.W)
  val captures = if(channels > 0) Some(Vec(channels, new TelemetryCapture)) else None
}
class TelemetryReply(channels: Int, words: Int) extends Bundle {
  val kind = UInt(2.W); val state = new TelemetryState(channels, words)
}
