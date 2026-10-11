// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdPublicationSourceFixture(p: SocParameters) extends MemoryResetFixture(p) {
  val visibleMask=IO(Output(UInt(32.W))); visibleMask:=BoringUtils.bore(fabric.wakeMask)
  val holdGrant=IO(Input(UInt(2.W))); val holdDecision=IO(Input(UInt(2.W)))
  val holdPublication=IO(Input(UInt(2.W))); val holdDrain=IO(Input(UInt(2.W)))
  val holdCommand=IO(Input(UInt(2.W))); val holdReply=IO(Input(UInt(2.W)))
  val grantWaiting=IO(Output(UInt(2.W))); val replyWaiting=IO(Output(UInt(2.W)))
  val sourceDebt=IO(Output(UInt(2.W))); val sourceBusy=IO(Output(UInt(2.W)))
  val reserveAccepted=IO(Output(UInt(2.W))); val decisionAccepted=IO(Output(UInt(2.W)))
  val committedDecision=IO(Output(UInt(2.W))); val publicationAccepted=IO(Output(UInt(2.W)))
  val drainAccepted=IO(Output(UInt(2.W))); val commandAccepted=IO(Output(UInt(2.W)))
  val replyAccepted=IO(Output(UInt(2.W)))
  val validatedReply=IO(Output(Bool()))
  validatedReply:=fabric.io.controlReply.valid && fabric.io.controlReply.bits.kind === ControlKind.Mmio.U
  val sources=Seq(fabric.io.telemetrySource,fabric.io.housekeepingSource)
  val grants=Seq(telemetryGrant,housekeepingGrant)
  val decisions=Seq(telemetryDecision,housekeepingDecision)
  val publications=Seq(telemetryPublication,housekeepingPublication)
  val drains=Seq(telemetryDrain,housekeepingDrain)
  for(i <- 0 until 2) {
    sources(i).grant.valid:=grants(i).out.valid && !holdGrant(i)
    grants(i).out.ready:=sources(i).grant.ready && !holdGrant(i)
    decisions(i).in.valid:=sources(i).decision.valid && !holdDecision(i)
    sources(i).decision.ready:=decisions(i).in.ready && !holdDecision(i)
    publications(i).in.valid:=sources(i).publication.valid && !holdPublication(i)
    sources(i).publication.ready:=publications(i).in.ready && !holdPublication(i)
    sources(i).drain.valid:=drains(i).out.valid && !holdDrain(i)
    drains(i).out.ready:=sources(i).drain.ready && !holdDrain(i)
  }
  telemetryCommandBridge.in.valid:=fabric.telemetryCommand.valid && !holdCommand(0)
  fabric.telemetryCommand.ready:=telemetryCommandBridge.in.ready && !holdCommand(0)
  housekeepingCommandBridge.in.valid:=fabric.housekeepingCommand.valid && !holdCommand(1)
  fabric.housekeepingCommand.ready:=housekeepingCommandBridge.in.ready && !holdCommand(1)
  fabric.telemetryReply.valid:=telemetryReplyBridge.out.valid && !holdReply(0)
  telemetryReplyBridge.out.ready:=fabric.telemetryReply.ready && !holdReply(0)
  fabric.housekeepingReply.valid:=housekeepingReplyBridge.out.valid && !holdReply(1)
  housekeepingReplyBridge.out.ready:=fabric.housekeepingReply.ready && !holdReply(1)
  grantWaiting:=Cat(grants.reverse.map(_.out.valid))
  replyWaiting:=Cat(housekeepingReplyBridge.out.valid && housekeepingReplyBridge.out.bits.cpuCompletion,
    telemetryReplyBridge.out.valid && telemetryReplyBridge.out.bits.kind === TelemetryKind.Commit.U)
  sourceDebt:=Cat(sources.reverse.map(_.resetDebt)); sourceBusy:=Cat(sources.reverse.map(_.occupied))
  reserveAccepted:=Cat(sources.reverse.map(_.reserve.fire))
  decisionAccepted:=Cat(sources.reverse.map(_.decision.fire))
  committedDecision:=Cat(sources.reverse.map(s => s.decision.fire && s.decision.bits))
  publicationAccepted:=Cat(publications.reverse.map(_.in.fire))
  drainAccepted:=Cat(drains.reverse.map(_.out.fire))
  commandAccepted:=Cat(fabric.housekeepingCommand.fire && fabric.housekeepingCommand.bits.cpuCompletion,
    fabric.telemetryCommand.fire && fabric.telemetryCommand.bits.kind === TelemetryKind.Commit.U)
  replyAccepted:=Cat(fabric.housekeepingReply.fire && fabric.housekeepingReply.bits.cpuCompletion,
    fabric.telemetryReply.fire && fabric.telemetryReply.bits.kind === TelemetryKind.Commit.U)
}

class ClickPublicationSourceFixture(p: SocParameters) extends ClickMemoryResetFixture(p) {
  val visibleMask=IO(Output(UInt(32.W))); visibleMask:=BoringUtils.bore(fabric.wakeMask)
  val holdGrant=IO(Input(UInt(2.W))); val holdDecision=IO(Input(UInt(2.W)))
  val holdPublication=IO(Input(UInt(2.W))); val holdDrain=IO(Input(UInt(2.W)))
  val holdCommand=IO(Input(UInt(2.W))); val holdReply=IO(Input(UInt(2.W)))
  val grantWaiting=IO(Output(UInt(2.W))); val replyWaiting=IO(Output(UInt(2.W)))
  val sourceDebt=IO(Output(UInt(2.W))); val sourceBusy=IO(Output(UInt(2.W)))
  val reserveAccepted=IO(Output(UInt(2.W))); val decisionAccepted=IO(Output(UInt(2.W)))
  val committedDecision=IO(Output(UInt(2.W))); val publicationAccepted=IO(Output(UInt(2.W)))
  val drainAccepted=IO(Output(UInt(2.W))); val commandAccepted=IO(Output(UInt(2.W)))
  val replyAccepted=IO(Output(UInt(2.W)))
  val validatedReply=IO(Output(Bool()))
  validatedReply:=fabric.io.controlReply.valid && fabric.io.controlReply.bits.kind === ControlKind.Mmio.U
  val sources=Seq(fabric.io.telemetrySource,fabric.io.housekeepingSource)
  val grants=Seq(telemetryGrant,housekeepingGrant)
  val decisions=Seq(telemetryDecision,housekeepingDecision)
  val publications=Seq(telemetryPublication,housekeepingPublication)
  val drains=Seq(telemetryDrain,housekeepingDrain)
  for(i <- 0 until 2) {
    sources(i).grant.valid:=grants(i).out.valid && !holdGrant(i)
    grants(i).out.ready:=sources(i).grant.ready && !holdGrant(i)
    decisions(i).in.valid:=sources(i).decision.valid && !holdDecision(i)
    sources(i).decision.ready:=decisions(i).in.ready && !holdDecision(i)
    publications(i).in.valid:=sources(i).publication.valid && !holdPublication(i)
    sources(i).publication.ready:=publications(i).in.ready && !holdPublication(i)
    sources(i).drain.valid:=drains(i).out.valid && !holdDrain(i)
    drains(i).out.ready:=sources(i).drain.ready && !holdDrain(i)
  }
  telemetryCommandBridge.in.valid:=fabric.telemetryCommand.valid && !holdCommand(0)
  fabric.telemetryCommand.ready:=telemetryCommandBridge.in.ready && !holdCommand(0)
  housekeepingCommandBridge.in.valid:=fabric.housekeepingCommand.valid && !holdCommand(1)
  fabric.housekeepingCommand.ready:=housekeepingCommandBridge.in.ready && !holdCommand(1)
  fabric.telemetryReply.valid:=telemetryReplyBridge.out.valid && !holdReply(0)
  telemetryReplyBridge.out.ready:=fabric.telemetryReply.ready && !holdReply(0)
  fabric.housekeepingReply.valid:=housekeepingReplyBridge.out.valid && !holdReply(1)
  housekeepingReplyBridge.out.ready:=fabric.housekeepingReply.ready && !holdReply(1)
  grantWaiting:=Cat(grants.reverse.map(_.out.valid))
  replyWaiting:=Cat(housekeepingReplyBridge.out.valid && housekeepingReplyBridge.out.bits.cpuCompletion,
    telemetryReplyBridge.out.valid && telemetryReplyBridge.out.bits.kind === TelemetryKind.Commit.U)
  sourceDebt:=Cat(sources.reverse.map(_.resetDebt)); sourceBusy:=Cat(sources.reverse.map(_.occupied))
  reserveAccepted:=Cat(sources.reverse.map(_.reserve.fire))
  decisionAccepted:=Cat(sources.reverse.map(_.decision.fire))
  committedDecision:=Cat(sources.reverse.map(s => s.decision.fire && s.decision.bits))
  publicationAccepted:=Cat(publications.reverse.map(_.in.fire))
  drainAccepted:=Cat(drains.reverse.map(_.out.fire))
  commandAccepted:=Cat(fabric.housekeepingCommand.fire && fabric.housekeepingCommand.bits.cpuCompletion,
    fabric.telemetryCommand.fire && fabric.telemetryCommand.bits.kind === TelemetryKind.Commit.U)
  replyAccepted:=Cat(fabric.housekeepingReply.fire && fabric.housekeepingReply.bits.cpuCompletion,
    fabric.telemetryReply.fire && fabric.telemetryReply.bits.kind === TelemetryKind.Commit.U)
}
