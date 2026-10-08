// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives.{AsymmetricCElement, EventRegister}

/** Digital bounds, not characterized GF180 cells. The request barrier covers
  * arrival detection + bank selection + register Q propagation, with margin.
  * Both protocols delay the native request (including both Click polarities).
  */
object RegisterTiming {
  val minimum = ModelTime.ps(1000)
  val maximum = ModelTime.ps(10000)
  val forward = ModelTime(3 * maximum.fs + minimum.fs)
  val executeData = ModelTime.ps(20000) // complete read mux + decode/ALU path
  def check(model: ModelTime): Unit = require(model.fs >= minimum.fs && model.fs <= maximum.fs,
    "REGISTER_CELL_OUTSIDE_WRITEBACK_GUARD")
}

/** One copy of x1..x15. The core holds the token until the writeback guard
  * expires. Read muxes live inside the execute stage's whole-path budget.
  * Only the selected bank receives a write pulse; x0 has no storage.
  */
class ArchitecturalRegisters(domain: ResetDomain, cell: ModelTime = RegisterTiming.minimum) extends AsyncModule(domain) {
  RegisterTiming.check(cell)
  val arrival = IO(Input(Bool()))
  val write = IO(Input(new RegisterWrite))
  val values = IO(Output(Vec(15, UInt(32.W))))
  private val resetRef = contract.endpoint("reset",reset)
  for(index <- 1 to 15) {
    // Public API: rise on arrival AND decode, hold until arrival falls.
    // Selection remains stable for the complete pulse through acknowledgement.
    val gate = Module(new AsymmetricCElement(1,1,0,cell))
    gate.reset := reset; gate.common := arrival.asUInt
    gate.rising := (write.enable && write.rd === index.U).asUInt; gate.falling := 0.U
    contract.primitive(s"select$index",gate,Map("COMMON"->BigInt(1),"RISING"->BigInt(1),
      "FALLING"->BigInt(0),"DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),
      "COMMON_INVERT"->BigInt(0),"RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,
      "public asymmetric C-element; decode/data stable before arrival through token acknowledgement; max 10 ns")
    val bank = Module(new EventRegister(32,cell))
    bank.reset := reset; bank.trigger := gate.q; bank.d := write.data
    contract.primitive(s"x$index",bank,Map("WIDTH"->BigInt(32),"DELAY_FS"->BigInt(cell.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,
      "one selected architectural register per retirement; max trigger-to-Q 10 ns; core writeback guard covers completion")
    values(index-1) := bank.q
  }
  contract.endpoint("arrival",arrival)
  contract.endpoint("write_enable",write.enable)
  contract.endpoint("write_index",write.rd); contract.endpoint("write_data",write.data)
}
