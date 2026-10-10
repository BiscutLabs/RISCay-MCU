// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chiselasync.bundled.{ClickBuffer,PhaseDecoupledClickBuffer}
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.ClickTiming
import chiselasync.protocol.TwoPhase

/** One seeded native credit; input and output parities are independent.
  * All state belongs to the CPU lifetime. No return-to-zero conversion is used.
  */
class ClickAdmission(domain: ResetDomain) extends AsyncModule(domain) {
  val returned=twoPhaseInput("returned",Bool())
  val grant=twoPhaseOutput("grant",Bool())
  val start=IO(Input(Bool()))
  private val timing=ClickTiming.Simulation
  private val pending=asyncChild("pending")(d => new ClickBuffer(Bool(),timing,d))
  private val credit=asyncChild("credit")(d => new PhaseDecoupledClickBuffer(Bool(),timing,Some(false.B),d))
  credit.start.get:=start
  TwoPhase.connect(pending.in,returned); TwoPhase.connect(credit.in,pending.out)
  TwoPhase.connect(grant,credit.out)
  contract.endpoint("reset",reset); contract.endpoint("start",start)
  contract.capacity(2)
}
