// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chiselasync.metadata.{DataAllowance, ClickTiming, DelayBounds, ModelTime}
import riscay.soc.ApplicationResetContract

/** Native Click policy; no four-phase conversion or periodic staging. */
object OwnerTiming {
  // Unmasked whole-transform annotation; capture storage owns reset.
  val base: ClickTiming = ClickTiming.Simulation.copy(dataAllowance=DataAllowance.Passive)
  def passive(t: ClickTiming): ClickTiming = t.copy(dataAllowance=DataAllowance.Passive)
  val elapsedStep: ClickTiming = OwnerTiming.base.copy(requestDelay=ModelTime.ps(100000))
  def execute(base: ClickTiming, data: ModelTime): ClickTiming = base.copy(
    data=DelayBounds.fixed(data),dataAllowance=DataAllowance.Passive,
    requestDelay=ModelTime((data.fs + base.requestDelay.fs - base.data.max.fs).max(80000000L)))
  def check(t: ClickTiming): Unit = require(
    (Seq(t.requestDelay.fs,t.acknowledgeDelay.fs,t.outputDelay.fs,t.data.max.fs,t.payload.max.fs) ++
      t.cells.values.map(_.max.fs)).forall(_ <= ApplicationResetContract.digitalDelayLimitFs),
    "owner timing exceeds supported digital timing-policy limit")
}

case class OwnerTiming(
    controlOwner: ClickTiming = OwnerTiming.base,
    controlUpdate: ClickTiming = OwnerTiming.base,
    elapsedOwner: ClickTiming = OwnerTiming.base,
    elapsedStep: ClickTiming = OwnerTiming.elapsedStep) {
  Seq(controlOwner,controlUpdate,elapsedOwner,elapsedStep).foreach(OwnerTiming.check)
}
