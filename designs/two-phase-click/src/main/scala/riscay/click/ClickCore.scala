// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{ClickTiming, ExportDesign}
import chiselasync.protocol.TwoPhase
import java.nio.file.Paths
import riscay._

/** Sequential RV32E core with native Click storage and phase routing throughout.
  * start rises once after coordinated reset settles, and stays high until reset.
  */
class ClickCore extends AsyncModule {
  val start = IO(Input(Bool()))
  val request = twoPhaseOutput("request", new MemoryRequest)
  val response = twoPhaseInput("response", new MemoryResponse)
  val trace = IO(Output(new Retirement))
  val traceEvent = IO(Output(Bool()))
  private val timing = ClickTiming.Simulation
  private val state = asyncChild("state")(d => new PhaseDecoupledClickBuffer(
    new CoreState, timing, Some(CoreState.initial), d))
  private val fork = asyncChild("fork")(d => new ClickFork(new CoreState, d))
  private val address = asyncChild("address")(d => new ClickStage(new CoreState,
    new MemoryRequest, Execute.request, timing, d))
  private val join = asyncChild("join")(d => new ClickJoin(new CoreState, new MemoryResponse, timing, d))
  private val execute = asyncChild("execute")(d => new ClickStage(
    new Joined(new CoreState, new MemoryResponse), new CoreState,
    (p: Joined[CoreState, MemoryResponse]) => Execute.step(p.left, p.right), timing, d))
  state.start.get := start
  TwoPhase.connect(fork.in, state.out)
  TwoPhase.connect(address.in, fork.left)
  TwoPhase.connect(join.left, fork.right)
  TwoPhase.connect(request, address.out)
  TwoPhase.connect(join.right, response)
  TwoPhase.connect(execute.in, join.out)
  TwoPhase.connect(state.in, execute.out)
  trace := execute.out.bits.trace
  traceEvent := execute.out.req
  contract.endpoint("start", start)
  contract.endpoint("trace_event", traceEvent)
  trace.elements.foreach { case (name, field) => contract.endpoint(s"trace_$name", field) }
}

object EmitClick extends App {
  require(args.length == 1, "Usage: EmitClick output-directory")
  ExportDesign.emit(new ClickCore, Paths.get(args(0)))
}
