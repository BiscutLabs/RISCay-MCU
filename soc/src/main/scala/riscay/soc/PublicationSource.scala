// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._

/** Immutable exclusive identity; the tag remains available for CPU diagnostics. */
class PublicationReservation extends Bundle {
  val recovery=Bool()
  val tag=Bool()
}

/** Receiving-clock client schema. BD owns the slot on that arbitration edge;
  * Click retains its independent native reservation/receipt implementation. */
class PublicationSourceBoundaryPort extends Bundle {
  val reserve=Decoupled(new PublicationReservation)
  val grant=Flipped(Decoupled(new PublicationReservation))
  val decision=Decoupled(Bool())
  val publication=Decoupled(Bool())
  val drain=Flipped(Decoupled(new PublicationReservation))
  val eligible=Input(Bool())
  val ownerRecovery=Input(Bool())
  val recoveryDebt=Input(Bool()) // Sticky reset debt; each implementation owns its reset crossing.
  val occupied=Input(Bool()) // Actual owner/crossings, excluding reset debt.
  val returnFence=Input(Bool()) // Debt/cleanup fence through the actual channel return.
  val draining=Input(Bool())
  val quiet=Output(Bool()) // Old dispatch/command/reply/publication fully drained.
}
