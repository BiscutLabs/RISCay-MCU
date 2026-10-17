// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chiselasync.metadata.{ClickTiming, DelayBounds, ModelTime}
import riscay.soc.ApplicationResetContract

/** Native Click policy; no four-phase conversion or periodic staging. */
object OwnerTiming {
  val elapsedStep: ClickTiming = ClickTiming.Simulation.copy(requestDelay=ModelTime.ps(100000))
  def execute(base: ClickTiming, data: ModelTime): ClickTiming = base.copy(
    data=DelayBounds.fixed(data),
    requestDelay=ModelTime((data.fs + base.requestDelay.fs - base.data.max.fs).max(80000000L)))
  def check(t: ClickTiming): Unit = require(
    (Seq(t.requestDelay.fs,t.acknowledgeDelay.fs,t.outputDelay.fs,t.data.max.fs,t.payload.max.fs) ++
      t.cells.values.map(_.max.fs)).forall(_ <= ApplicationResetContract.digitalDelayLimitFs),
    "owner timing exceeds supported digital timing-policy limit")
}

case class OwnerTiming(
    controlOwner: ClickTiming = ClickTiming.Simulation,
    controlUpdate: ClickTiming = ClickTiming.Simulation,
    elapsedOwner: ClickTiming = ClickTiming.Simulation,
    elapsedStep: ClickTiming = OwnerTiming.elapsedStep) {
  Seq(controlOwner,controlUpdate,elapsedOwner,elapsedStep).foreach(OwnerTiming.check)
}
