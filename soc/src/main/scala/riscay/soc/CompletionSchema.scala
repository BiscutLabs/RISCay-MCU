// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import riscay.MemoryResponse

/** One admitted CPU operation. Completion inputs are selected by this immutable
  * plan, never arbitrated from live requests. Effects remain with their owners.
  */
class CompletionPlan extends Bundle {
  val response = new MemoryResponse
  val memory = Bool()
  val telemetry = Bool()
  val housekeeping = Bool()
}
