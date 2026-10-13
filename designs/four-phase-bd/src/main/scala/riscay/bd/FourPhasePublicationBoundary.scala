// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util.experimental.InlineInstance

/** Temporary POR work-domain ownership of the clocked client's generation.
  * Native debt/return proof remains authoritative. A single held clean fact
  * crosses two flops; cached clean cannot retire an uncommitted new recovery.
  * No native eligibility or role level controls a clocked decision.
  */
class FourPhasePublicationBoundary extends Module with InlineInstance {
  val io=IO(new Bundle {
    val cancel=Input(Bool()); val nativeClean=Input(Bool())
    val empty=Input(Bool()); val quiet=Input(Bool())
    val reserved=Input(Bool()); val reservationRecovery=Input(Bool())
    val decided=Input(Bool()); val committed=Input(Bool())
    val available=Output(Bool()); val debt=Output(Bool())
    val eligible=Output(Bool()); val recovery=Output(Bool()); val occupied=Output(Bool())
  })
  val cleanFirst=RegNext(io.nativeClean,false.B)
  val clean=RegNext(cleanFirst,false.B)
  Seq(cleanFirst,clean).foreach(dontTouch(_))
  val pending=RegInit(true.B)
  val issued=RegInit(false.B); val recoveryCommitted=RegInit(false.B)
  val sawDirty=RegInit(false.B)
  val active=RegInit(false.B); val sawBusy=RegInit(false.B)
  val revoked=RegInit(true.B); val role=RegInit(false.B)
  io.available:= !io.cancel && !active && io.empty && (!pending || !issued)
  io.debt:=pending || io.cancel
  io.eligible:=active && !revoked && !io.cancel
  io.recovery:=role
  io.occupied:=active || !io.empty
  when(!clean) { sawDirty:=true.B }
  when(active && !io.empty) { sawBusy:=true.B }
  when(active && sawBusy && io.empty && io.quiet) { active:=false.B; sawBusy:=false.B }
  when(io.reserved) {
    assert(io.available,"PUBLICATION_BOUNDARY_DOUBLE_RESERVATION")
    active:=true.B; sawBusy:=false.B; revoked:=false.B; role:=io.reservationRecovery
    when(io.reservationRecovery) {
      assert(pending && !issued,"PUBLICATION_BOUNDARY_DUPLICATE_RECOVERY")
      issued:=true.B
    }
  }
  when(io.decided && io.committed && role) {
    assert(active && issued && !revoked && !io.cancel,"PUBLICATION_BOUNDARY_STALE_RECOVERY_COMMIT")
    recoveryCommitted:=true.B
  }
  when(pending && recoveryCommitted && sawDirty && clean && !active && io.empty && io.quiet) {
    pending:=false.B; issued:=false.B; recoveryCommitted:=false.B
  }
  // Revocation is sticky for this reservation, including grants/replies that
  // have not reached the clocked client yet. Persistent effects still drain.
  when(io.cancel) {
    pending:=true.B; issued:=false.B; recoveryCommitted:=false.B
    sawDirty:=false.B; revoked:=true.B
  }
}
