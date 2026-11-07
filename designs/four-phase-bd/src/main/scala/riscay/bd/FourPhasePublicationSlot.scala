// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay.soc._

/** A single slot at the existing command/recovery receiving-clock arbiter.
  * It owns no payload. Actual command and reply bridges remain native crossings.
  * Accepted effects drain even when cancellation revokes their application view.
  */
class FourPhasePublicationSlot extends Module with InlineInstance {
  val io=IO(new Bundle {
    val client=Flipped(new PublicationSourceBoundaryPort)
    val cancel=Input(Bool())
    val commandAccepted=Input(Bool())
    val channelsReturned=Input(Bool())
  })
  private val idle :: grant :: waitingIssue :: issued :: published :: cancelled :: Nil = Enum(6)
  private val phase=RegInit(idle)
  private val debt=RegInit(true.B)
  private val revoked=RegInit(true.B)
  private val role=RegInit(false.B)
  private val tag=RegInit(false.B)
  private val p=io.client
  p.reserve.ready:=phase===idle && !io.cancel && p.quiet && io.channelsReturned
  p.grant.valid:=phase===grant
  p.grant.bits.recovery:=role; p.grant.bits.tag:=tag
  p.decision.ready:=phase===grant
  // A publication is accepted at the same edge as the actual reply receipt.
  p.publication.ready:=true.B
  // Drain receipts identify accepted effects only. A rejected reservation has
  // no command/reply to acknowledge and cannot be blocked by its drain sink.
  p.drain.valid:=phase===published && io.channelsReturned
  p.drain.bits.recovery:=role; p.drain.bits.tag:=tag
  p.eligible:=phase=/=idle && !revoked && !io.cancel
  p.ownerRecovery:=role
  p.recoveryDebt:=debt || io.cancel
  p.occupied:=phase=/=idle
  p.returnFence:=debt || io.cancel
  p.draining:=phase=/=idle || debt || io.cancel
  when(p.reserve.fire) {
    phase:=grant; role:=p.reserve.bits.recovery; tag:=p.reserve.bits.tag; revoked:=false.B
  }
  when(p.decision.fire) {
    assert(p.grant.fire,"PUBLICATION_SLOT_DECISION_WITHOUT_GRANT")
    when(p.decision.bits) {
      assert(!revoked && !io.cancel,"PUBLICATION_SLOT_REVOKED_ACCEPT")
      when(role) { assert(io.commandAccepted,"PUBLICATION_SLOT_RECOVERY_NOT_ATOMIC") }
      phase:=Mux(io.commandAccepted,issued,waitingIssue)
    }.otherwise { phase:=cancelled; revoked:=true.B }
  }
  when(io.commandAccepted) {
    assert(phase===idle || phase===waitingIssue ||
      (phase===grant && p.decision.fire && p.decision.bits),
      "PUBLICATION_SLOT_UNEXPECTED_COMMAND")
  }
  when(io.commandAccepted && phase===waitingIssue) { phase:=issued }
  when(p.publication.fire) {
    assert(phase===issued,"PUBLICATION_SLOT_REPLY_WITHOUT_COMMAND")
    phase:=published
  }
  when(p.drain.fire) {
    when(phase===published && role && !revoked && !io.cancel) { debt:=false.B }
    phase:=idle
  }
  when(phase===cancelled && io.channelsReturned && p.quiet) { phase:=idle }
  // A later cancellation revokes a recovery as well. Never erase its accepted
  // command, and never let its eventual reply clear the new recovery debt.
  when(io.cancel) { debt:=true.B; revoked:=true.B }
}
