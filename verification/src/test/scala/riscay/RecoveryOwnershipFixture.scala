// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import riscay.soc._

class BdRecoveryOwnershipFixture(p: SocParameters) extends BdPublicationSourceFixture(p) {

  val holdReserve=IO(Input(UInt(2.W)))
  for((bridge,i) <- Seq(telemetryReserve,housekeepingReserve).zipWithIndex) {
    bridge.in.valid:=sources(i).reserve.valid && !holdReserve(i)
    sources(i).reserve.ready:=bridge.in.ready && !holdReserve(i)
  }

  val nativeDebt=IO(Output(UInt(2.W))); nativeDebt:=Cat(sources.reverse.map(_.recoveryDebt))
  val returnFence=IO(Output(UInt(2.W))); returnFence:=Cat(sources.reverse.map(_.returnFence))
  val eligible=IO(Output(UInt(2.W))); eligible:=Cat(sources.reverse.map(_.eligible))
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
  val projectedEvents=IO(Output(UInt(6.W))); projectedEvents:=BoringUtils.bore(fabric.pendingState)
  val visibleEvents=IO(Output(UInt(6.W))); visibleEvents:=BoringUtils.bore(fabric.pending)
  val visibleDeadline=IO(Output(UInt(32.W))); visibleDeadline:=BoringUtils.bore(fabric.deadline)
  val boardTime=IO(Output(UInt(32.W))); boardTime:=BoringUtils.bore(fabric.boardNow)
  val maintenanceReply=IO(Output(Bool()))
  maintenanceReply:=fabric.housekeepingReply.fire && !fabric.housekeepingReply.bits.recovery &&
    !fabric.housekeepingReply.bits.cpuCompletion && fabric.housekeepingReply.bits.resetApplication
  val maintenanceKick=IO(Output(Bool())); maintenanceKick:=BoringUtils.bore(fabric.kick)
}

class ClickRecoveryOwnershipFixture(p: SocParameters) extends ClickPublicationSourceFixture(p) {

  val holdReserve=IO(Input(UInt(2.W)))
  for((bridge,i) <- Seq(telemetryReserve,housekeepingReserve).zipWithIndex) {
    bridge.in.valid:=sources(i).reserve.valid && !holdReserve(i)
    sources(i).reserve.ready:=bridge.in.ready && !holdReserve(i)
  }

  val nativeDebt=IO(Output(UInt(2.W))); nativeDebt:=Cat(sources.reverse.map(_.recoveryDebt))
  val returnFence=IO(Output(UInt(2.W))); returnFence:=Cat(sources.reverse.map(_.returnFence))
  val eligible=IO(Output(UInt(2.W))); eligible:=Cat(sources.reverse.map(_.eligible))
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
  val projectedEvents=IO(Output(UInt(6.W))); projectedEvents:=BoringUtils.bore(fabric.pendingState)
  val visibleEvents=IO(Output(UInt(6.W))); visibleEvents:=BoringUtils.bore(fabric.pending)
  val visibleDeadline=IO(Output(UInt(32.W))); visibleDeadline:=BoringUtils.bore(fabric.deadline)
  val boardTime=IO(Output(UInt(32.W))); boardTime:=BoringUtils.bore(fabric.boardNow)
  val maintenanceReply=IO(Output(Bool()))
  maintenanceReply:=fabric.housekeepingReply.fire && !fabric.housekeepingReply.bits.recovery &&
    !fabric.housekeepingReply.bits.cpuCompletion && fabric.housekeepingReply.bits.resetApplication
  val maintenanceKick=IO(Output(Bool())); maintenanceKick:=BoringUtils.bore(fabric.kick)
}
