// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chiselasync.metadata.{BundledTiming, ModelTime}
import riscay.RegisterTiming
import riscay.soc.ApplicationResetContract

/** Per-owner implementation targets, not characterized physical guarantees.
  * Only request/ACK guards grow; arithmetic and storage models stay unchanged.
  */
object OwnerTiming {
  val execute: BundledTiming = BundledTiming.simulation(dataMax=RegisterTiming.executeData)
    .copy(matchedDelay=ModelTime.ps(80000))
  val elapsedStep: BundledTiming = BundledTiming.Simulation.copy(matchedDelay=ModelTime.ps(100000))
  val controlAck: ModelTime = ModelTime.ps(32000)
  def check(t: BundledTiming): Unit = require(
    (Seq(t.matchedDelay.fs,t.outputDelay.fs,t.dataDelay.max.fs,t.latchDelay.max.fs) ++
      t.controls.values.map(_.max.fs)).forall(_ <= ApplicationResetContract.digitalDelayLimitFs),
    "owner timing exceeds supported digital timing-policy limit")
}

case class OwnerTiming(
    controlOwner: BundledTiming = BundledTiming.Simulation,
    controlUpdate: BundledTiming = BundledTiming.Simulation,
    elapsedOwner: BundledTiming = BundledTiming.Simulation,
    elapsedStep: BundledTiming = OwnerTiming.elapsedStep,
    controlAck: ModelTime = OwnerTiming.controlAck) {
  Seq(controlOwner,controlUpdate,elapsedOwner,elapsedStep).foreach(OwnerTiming.check)
  require(controlAck.fs > 0 && controlAck.fs <= ApplicationResetContract.digitalDelayLimitFs,
    "control ACK guard exceeds supported digital timing-policy limit")
}
