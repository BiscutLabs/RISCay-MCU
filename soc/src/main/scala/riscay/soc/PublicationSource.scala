// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._

/** Immutable exclusive identity; the tag remains available for CPU diagnostics. */
class PublicationReservation extends Bundle {
  val recovery=Bool()
  val tag=Bool()
}

/** Clocked-client schema only; each design owns native reservation and receipts. */
class PublicationSourceBoundaryPort extends Bundle {
  val reserve=Decoupled(new PublicationReservation)
  val grant=Flipped(Decoupled(new PublicationReservation))
  val decision=Decoupled(Bool())
  val publication=Decoupled(Bool())
  val drain=Flipped(Decoupled(new PublicationReservation))
  val eligible=Input(Bool())
  val ownerRecovery=Input(Bool())
  val recoveryDebt=Input(Bool()) // Native sticky debt, asserted by every application reset.
  val occupied=Input(Bool()) // Actual owner/crossings, excluding reset debt.
  val returnFence=Input(Bool()) // Explicit clocked full-return fence, pending item 10b2c2b.
  val draining=Input(Bool())
  val quiet=Output(Bool()) // Old dispatch/command/reply/publication fully drained.
}
