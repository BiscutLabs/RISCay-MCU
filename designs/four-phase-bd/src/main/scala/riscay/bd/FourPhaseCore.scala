// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{BundledTiming, ExportDesign, ModelTime}
import chiselasync.protocol.FourPhase
import java.nio.file.Paths
import riscay._

/** Sequential RV32E core. No periodic clock; memory owns each request's latency.
  * The state branch waits for the matching response before executing a microstep.
  */
class FourPhaseCore extends AsyncModule {
  val request = fourPhaseOutput("request", new MemoryRequest)
  val response = fourPhaseInput("response", new MemoryResponse)
  val trace = IO(Output(new Retirement))
  val traceEvent = IO(Output(Bool()))
  private val timing = BundledTiming.Simulation
  private val cell = ModelTime.ps(1000)
  private val state = asyncChild("state")(d => new FourPhaseFifo(new CoreState, 1,
    timing, Seq(CoreState.initial), cell, d))
  private val fork = asyncChild("fork")(d => new FourPhaseFork(new CoreState, 2, cell, d))
  private val address = asyncChild("address")(d => new FourPhaseStage(new CoreState,
    new MemoryRequest, Execute.request, timing, d))
  private val join = asyncChild("join")(d => new FourPhaseJoin(new CoreState, new MemoryResponse, timing, cell, d))
  private val execute = asyncChild("execute")(d => new FourPhaseStage(
    new Joined(new CoreState, new MemoryResponse), new CoreState,
    (p: Joined[CoreState, MemoryResponse]) => Execute.step(p.left, p.right), timing, d))
  FourPhase.connect(fork.in, state.out)
  FourPhase.connect(address.in, fork.out(0))
  FourPhase.connect(join.left, fork.out(1))
  FourPhase.connect(request, address.out)
  FourPhase.connect(join.right, response)
  FourPhase.connect(execute.in, join.out)
  FourPhase.connect(state.in, execute.out)
  trace := execute.out.bits.trace
  traceEvent := execute.out.req
  contract.endpoint("trace_event", traceEvent)
  trace.elements.foreach { case (name, field) => contract.endpoint(s"trace_$name", field) }
}

object EmitFourPhase extends App {
  require(args.length == 1, "Usage: EmitFourPhase output-directory")
  ExportDesign.emit(new FourPhaseCore, Paths.get(args(0)))
}
