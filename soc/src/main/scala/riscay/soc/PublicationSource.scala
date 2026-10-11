// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._

/** Clocked-client schema only; each design owns native reservation and receipts. */
class PublicationSourceBoundaryPort extends Bundle {
  val reserve=Decoupled(Bool())
  val grant=Flipped(Decoupled(Bool()))
  val decision=Decoupled(Bool())
  val publication=Decoupled(Bool())
  val drain=Flipped(Decoupled(Bool()))
  val eligible=Input(Bool())
  val occupied=Input(Bool()) // Actual owner/crossings, excluding reset debt.
  val resetDebt=Input(Bool())
  val draining=Input(Bool())
  val quiet=Output(Bool()) // Old dispatch/command/reply/publication fully drained.
}
