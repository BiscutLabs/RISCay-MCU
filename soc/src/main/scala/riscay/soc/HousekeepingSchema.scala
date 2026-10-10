// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.experimental.BundleLiterals._

/** Wire formats and reset literals only; each design owns its transitions. */
class HousekeepingState extends Bundle {
  val now = UInt(32.W); val boardNow = UInt(32.W); val consumed = UInt(32.W)
  val deadline = UInt(32.W); val armed = Bool(); val lease = UInt(32.W); val wakeMask = UInt(32.W)
  val period = UInt(32.W); val nextPeriod = UInt(32.W); val periodPending = Bool()
  val countdown = UInt(32.W); val requested = Bool()
}
object HousekeepingState {
  def initial(p: SocParameters): HousekeepingState = (new HousekeepingState).Lit(
    _.now -> 0.U, _.boardNow -> 0.U, _.consumed -> 0.U,
    _.deadline -> 0.U, _.armed -> false.B, _.lease -> 0.U, _.wakeMask -> 15.U,
    _.period -> p.defaultSampleMs.U, _.nextPeriod -> p.defaultSampleMs.U, _.periodPending -> false.B,
    _.countdown -> (p.defaultSampleMs - 1).max(0).U,
    _.requested -> (p.lowPower.nonEmpty && p.adc.nonEmpty).B)
}
class HousekeepingCommand extends Bundle {
  val timeValid = Bool(); val target = UInt(32.W); val single = Bool()
  val elapsed = Vec(3, UInt(32.W)); val elapsedOverflow = Bool()
  val resetApplication = Bool(); val started = Bool(); val parked = Bool()
  val adcBusy = Bool(); val discard = Bool()
  val write = Bool(); val offset = UInt(7.W); val data = UInt(32.W); val waitAccepted = Bool()
  val periodUpdate = Bool(); val period = UInt(32.W); val cpuCompletion = Bool()
}
class HousekeepingReply extends Bundle {
  val state = new HousekeepingState
  val timeValid = Bool(); val tick = Bool(); val single = Bool(); val elapsed = Vec(3, UInt(32.W))
  val due = Bool(); val leaseExpired = Bool(); val startAdc = Bool(); val kick = Bool()
  val resetApplication = Bool(); val cpuCompletion = Bool()
}
