// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import riscay.soc._

class BdRecoveryOwnershipFixture(p: SocParameters) extends BdPublicationSourceFixture(p) {

  val holdReserve=IO(Input(UInt(2.W)))
  for((bridge,i) <- Seq(telemetryReserve,housekeepingReserve).zipWithIndex) {
    val available=Seq(telemetryReserveAvailable,housekeepingReserveAvailable)(i)
    bridge.in.valid:=sources(i).reserve.valid && available && !holdReserve(i)
    sources(i).reserve.ready:=bridge.in.ready && available && !holdReserve(i)
  }

  val holdFinal=IO(Input(UInt(2.W))); val holdFinalReturn=IO(Input(UInt(2.W)))
  val finalReturns=Seq(telemetryFinalReturn,housekeepingFinalReturn)
  for((receipt,i) <- finalReturns.zipWithIndex) {
    receipt.quiet:=Seq(telemetryReserve,housekeepingReserve)(i).in.ready &&
      Seq(telemetryDecision,housekeepingDecision)(i).in.ready &&
      Seq(telemetryPublication,housekeepingPublication)(i).in.ready &&
      !grants(i).out.valid && !drains(i).out.valid && sources(i).quiet && !holdFinal(i)
    // Test-only hold applied while the actual request is already high. It
    // prolongs the old ACK return without inventing a new receipt transaction.
    receipt.request:=Seq(telemetrySource,housekeepingSource)(i).finalRequest || holdFinalReturn(i)
  }
  val finalRequest=IO(Output(UInt(2.W)))
  finalRequest:=Cat(Seq(housekeepingSource.finalRequest,telemetrySource.finalRequest))
  val finalAcknowledge=IO(Output(UInt(2.W)))
  finalAcknowledge:=Cat(finalReturns.reverse.map(_.acknowledge))
  val finalPending=IO(Output(UInt(2.W))); finalPending:=finalRequest ^ finalAcknowledge

  val nativeDebt=IO(Output(UInt(2.W))); nativeDebt:=Cat(housekeepingSource.recoveryDebt,telemetrySource.recoveryDebt)
  val returnFence=IO(Output(UInt(2.W))); returnFence:=Cat(housekeepingReturnFence,telemetryReturnFence)
  val eligible=IO(Output(UInt(2.W))); eligible:=Cat(housekeepingSource.eligible,telemetrySource.eligible)
  val serviceEligible=IO(Output(UInt(2.W))); serviceEligible:=Cat(sources.reverse.map(_.eligible))
  val nativeRecoveryRole=IO(Output(UInt(2.W))); nativeRecoveryRole:=Cat(housekeepingSource.ownerRecovery,telemetrySource.ownerRecovery)
  val qualifiedReset=IO(Output(Bool())); qualifiedReset:=fabric.io.cpuReset
  val recoveryGrantWaiting=IO(Output(UInt(2.W)))
  recoveryGrantWaiting:=Cat(grants.reverse.map(g => g.out.valid && g.out.bits.recovery))
  val recoveryReplyWaiting=IO(Output(UInt(2.W)))
  recoveryReplyWaiting:=Cat(housekeepingReplyBridge.out.valid && housekeepingReplyBridge.out.bits.recovery,
    telemetryReplyBridge.out.valid && telemetryReplyBridge.out.bits.recovery)
  val recoveryReserve=IO(Output(UInt(2.W)))
  recoveryReserve:=Cat(sources.reverse.map(s => s.reserve.fire && s.reserve.bits.recovery))
  val recoveryDecision=IO(Output(UInt(2.W)))
  recoveryDecision:=Cat(sources.reverse.map(s => s.decision.fire && s.ownerRecovery))
  val recoveryCommit=IO(Output(UInt(2.W)))
  recoveryCommit:=Cat(sources.reverse.map(s => s.decision.fire && s.decision.bits && s.ownerRecovery))
  val recoveryPublication=IO(Output(UInt(2.W)))
  recoveryPublication:=Cat(sources.reverse.map(s => s.publication.fire && s.ownerRecovery))
  val recoveryDrain=IO(Output(UInt(2.W)))
  recoveryDrain:=Cat(drains.reverse.map(d => d.out.fire && d.out.bits.recovery))
  val recoveryCommand=IO(Output(UInt(2.W)))
  recoveryCommand:=Cat(fabric.housekeepingCommand.fire && fabric.housekeepingCommand.bits.recovery,
    fabric.telemetryCommand.fire && fabric.telemetryCommand.bits.recovery)
  val recoveryReply=IO(Output(UInt(2.W)))
  recoveryReply:=Cat(fabric.housekeepingReply.fire && fabric.housekeepingReply.bits.recovery,
    fabric.telemetryReply.fire && fabric.telemetryReply.bits.recovery)
  val freshRecoveryReply=IO(Output(UInt(2.W)))
  freshRecoveryReply:=recoveryReply & eligible & Fill(2,!fabric.io.cpuResetActive)
  val projectedEvents=IO(Output(UInt(6.W))); projectedEvents:=BoringUtils.bore(fabric.eventPending)
  val visibleEvents=IO(Output(UInt(6.W))); visibleEvents:=BoringUtils.bore(fabric.pending)
  val visibleDeadline=IO(Output(UInt(32.W))); visibleDeadline:=BoringUtils.bore(fabric.deadline)
  val projectedTime=IO(Output(UInt(32.W))); projectedTime:=(BoringUtils.bore(fabric.housekeepingState).now + BoringUtils.bore(fabric.housekeepingQueued).elapsed(0) +
    Mux(BoringUtils.bore(fabric.housekeepingOrderedPending),BoringUtils.bore(fabric.housekeepingOrdered).elapsed(0),0.U) +
    BoringUtils.bore(fabric.housekeepingInFlight).elapsed(0))
  val maintenanceReply=IO(Output(Bool()))
  maintenanceReply:=fabric.housekeepingReply.fire && !fabric.housekeepingReply.bits.recovery &&
    !fabric.housekeepingReply.bits.cpuCompletion && fabric.housekeepingReply.bits.resetApplication
  val maintenanceKick=IO(Output(Bool())); maintenanceKick:=BoringUtils.bore(fabric.kick)
}

class ClickRecoveryOwnershipFixture(p: SocParameters) extends ClickPublicationSourceFixture(p) {

  val holdReserve=IO(Input(UInt(2.W)))
  for((bridge,i) <- Seq(telemetryReserve,housekeepingReserve).zipWithIndex) {
    val available=Seq(telemetryReserveAvailable,housekeepingReserveAvailable)(i)
    bridge.in.valid:=sources(i).reserve.valid && available && !holdReserve(i)
    sources(i).reserve.ready:=bridge.in.ready && available && !holdReserve(i)
  }

  val holdFinal=IO(Input(UInt(2.W))); val holdFinalReturn=IO(Input(UInt(2.W)))
  val finalReturns=Seq(telemetryFinalReturn,housekeepingFinalReturn)
  for((receipt,i) <- finalReturns.zipWithIndex) {
    receipt.quiet:=Seq(telemetryReserve,housekeepingReserve)(i).in.ready &&
      Seq(telemetryDecision,housekeepingDecision)(i).in.ready &&
      Seq(telemetryPublication,housekeepingPublication)(i).in.ready &&
      !grants(i).out.valid && !drains(i).out.valid && sources(i).quiet && !holdFinal(i)
  }
  val finalRequest=IO(Output(UInt(2.W)))
  finalRequest:=Cat(Seq(housekeepingSource.finalRequest,telemetrySource.finalRequest))
  val finalAcknowledge=IO(Output(UInt(2.W)))
  finalAcknowledge:=Cat(finalReturns.reverse.map(_.acknowledge))
  val finalPending=IO(Output(UInt(2.W))); finalPending:=finalRequest ^ finalAcknowledge

  val nativeDebt=IO(Output(UInt(2.W))); nativeDebt:=Cat(housekeepingSource.recoveryDebt,telemetrySource.recoveryDebt)
  val returnFence=IO(Output(UInt(2.W))); returnFence:=Cat(housekeepingReturnFence,telemetryReturnFence)
  val eligible=IO(Output(UInt(2.W))); eligible:=Cat(housekeepingSource.eligible,telemetrySource.eligible)
  val serviceEligible=IO(Output(UInt(2.W))); serviceEligible:=Cat(sources.reverse.map(_.eligible))
  val nativeRecoveryRole=IO(Output(UInt(2.W))); nativeRecoveryRole:=Cat(housekeepingSource.ownerRecovery,telemetrySource.ownerRecovery)
  val qualifiedReset=IO(Output(Bool())); qualifiedReset:=fabric.io.cpuReset
  val recoveryGrantWaiting=IO(Output(UInt(2.W)))
  recoveryGrantWaiting:=Cat(grants.reverse.map(g => g.out.valid && g.out.bits.recovery))
  val recoveryReplyWaiting=IO(Output(UInt(2.W)))
  recoveryReplyWaiting:=Cat(housekeepingReplyBridge.out.valid && housekeepingReplyBridge.out.bits.recovery,
    telemetryReplyBridge.out.valid && telemetryReplyBridge.out.bits.recovery)
  val recoveryReserve=IO(Output(UInt(2.W)))
  recoveryReserve:=Cat(sources.reverse.map(s => s.reserve.fire && s.reserve.bits.recovery))
  val recoveryDecision=IO(Output(UInt(2.W)))
  recoveryDecision:=Cat(sources.reverse.map(s => s.decision.fire && s.ownerRecovery))
  val recoveryCommit=IO(Output(UInt(2.W)))
  recoveryCommit:=Cat(sources.reverse.map(s => s.decision.fire && s.decision.bits && s.ownerRecovery))
  val recoveryPublication=IO(Output(UInt(2.W)))
  recoveryPublication:=Cat(sources.reverse.map(s => s.publication.fire && s.ownerRecovery))
  val recoveryDrain=IO(Output(UInt(2.W)))
  recoveryDrain:=Cat(drains.reverse.map(d => d.out.fire && d.out.bits.recovery))
  val recoveryCommand=IO(Output(UInt(2.W)))
  recoveryCommand:=Cat(fabric.housekeepingCommand.fire && fabric.housekeepingCommand.bits.recovery,
    fabric.telemetryCommand.fire && fabric.telemetryCommand.bits.recovery)
  val recoveryReply=IO(Output(UInt(2.W)))
  recoveryReply:=Cat(fabric.housekeepingReply.fire && fabric.housekeepingReply.bits.recovery,
    fabric.telemetryReply.fire && fabric.telemetryReply.bits.recovery)
  val freshRecoveryReply=IO(Output(UInt(2.W)))
  freshRecoveryReply:=recoveryReply & eligible & Fill(2,!fabric.io.cpuResetActive)
  val projectedEvents=IO(Output(UInt(6.W))); projectedEvents:=BoringUtils.bore(fabric.eventPending)
  val visibleEvents=IO(Output(UInt(6.W))); visibleEvents:=BoringUtils.bore(fabric.pending)
  val visibleDeadline=IO(Output(UInt(32.W))); visibleDeadline:=BoringUtils.bore(fabric.deadline)
  val projectedTime=IO(Output(UInt(32.W))); projectedTime:=(BoringUtils.bore(fabric.housekeepingState).now + BoringUtils.bore(fabric.housekeepingQueued).elapsed(0) +
    Mux(BoringUtils.bore(fabric.housekeepingOrderedPending),BoringUtils.bore(fabric.housekeepingOrdered).elapsed(0),0.U) +
    BoringUtils.bore(fabric.housekeepingInFlight).elapsed(0))
  val maintenanceReply=IO(Output(Bool()))
  maintenanceReply:=fabric.housekeepingReply.fire && !fabric.housekeepingReply.bits.recovery &&
    !fabric.housekeepingReply.bits.cpuCompletion && fabric.housekeepingReply.bits.resetApplication
  val maintenanceKick=IO(Output(Bool())); maintenanceKick:=BoringUtils.bore(fabric.kick)
}
