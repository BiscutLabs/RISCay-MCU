// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import riscay.MemoryResponse

/** One admitted CPU operation. Completion inputs are selected by this immutable
  * plan, never arbitrated from live requests. Effects remain with their owners.
  */
class CompletionPlan extends Bundle {
  val response = new MemoryResponse
  // Program and working-RAM responses have independent native histories. An
  // admitted plan selects at most one memory owner; effects may join either.
  val memory = Bool()
  val ram = Bool()
  val telemetry = Bool()
  val housekeeping = Bool()
}
