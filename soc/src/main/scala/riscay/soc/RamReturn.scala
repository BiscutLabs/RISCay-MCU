// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import riscay.MemoryResponse

/** Native response across explicitly different POR/application lifetimes.
  * This is deliberately not a library Channel: that schema binds every port
  * to its parent's single reset domain. The MCU export contract must validate
  * the physical resets, state ownership and cancellation at this boundary.
  */
class RamReturnResponse extends Bundle {
  val req = Output(Bool())
  val ack = Input(Bool())
  val bits = Output(new MemoryResponse)
}

/** Program and working RAM share only this reset-boundary port schema. */
class ProgramReturnResponse extends RamReturnResponse
