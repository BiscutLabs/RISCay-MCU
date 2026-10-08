// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ClickTiming, ExportDesign, ModelTime}
import chiselasync.protocol.TwoPhase
import chiselasync.primitives.XorGate
import java.nio.file.Paths
import riscay._

/** Sequential RV32E core with native Click storage and phase routing throughout.
  * start rises once after coordinated reset settles, and stays high until reset.
  */
class ClickCore(domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
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
    new ExecutionInput, new ExecutionResult,
    (p: ExecutionInput) => Execute.step(p.state, p.response, p.a, p.b), timing, d))
  private val registers = asyncChild("register_file")(d => new ArchitecturalRegisters(d))
  private val arrival = Module(new XorGate(ModelTime.ps(1000)))
  arrival.reset := reset; arrival.a := state.out.req; arrival.b := state.out.ack
  contract.primitive("register_arrival",arrival,Map("DELAY_FS"->BigInt(1000000)),
    contract.endpoint("register_reset",reset),
    "native Click pending phase captures one writeback; payload held through acknowledge")
  registers.arrival := arrival.q
  registers.write := state.out.bits.writeback
  registers.rs1 := join.out.bits.right.data(19,15); registers.rs2 := join.out.bits.right.data(24,20)
  state.start.get := start
  TwoPhase.connect(fork.in, state.out)
  TwoPhase.connect(address.in, fork.left)
  TwoPhase.connect(join.left, fork.right)
  TwoPhase.connect(request, address.out)
  TwoPhase.connect(join.right, response)
  execute.in.req := join.out.req; join.out.ack := execute.in.ack
  execute.in.bits.state := join.out.bits.left; execute.in.bits.response := join.out.bits.right
  execute.in.bits.a := registers.a; execute.in.bits.b := registers.b
  state.in.req := execute.out.req; execute.out.ack := state.in.ack
  state.in.bits := execute.out.bits.state
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
