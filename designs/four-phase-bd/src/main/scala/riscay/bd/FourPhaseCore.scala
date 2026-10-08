// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ExportDesign, ModelTime}
import chiselasync.protocol.FourPhase
import chiselasync.primitives.{ControlGate, GateOperation}
import java.nio.file.Paths
import riscay._

/** Sequential RV32E core. No periodic clock; memory owns each request's latency.
  * The state branch waits for the matching response before executing a microstep.
  */
class FourPhaseCore(domain: ResetDomain = new ResetDomain("root"),
    registerCell: ModelTime = RegisterTiming.minimum,
    timing: BundledTiming = BundledTiming.Simulation,
    executeTiming: BundledTiming = BundledTiming.simulation(dataMax=RegisterTiming.executeData)) extends AsyncModule(domain) {
  RegisterTiming.check(registerCell)
  val request = fourPhaseOutput("request", new MemoryRequest)
  val response = fourPhaseInput("response", new MemoryResponse)
  val trace = IO(Output(new Retirement))
  val traceEvent = IO(Output(Bool()))
  private val cell = ModelTime.ps(1000)
  private val state = asyncChild("state")(d => new FourPhaseFifo(new CoreState, 1,
    timing, Seq(CoreState.initial), cell, d))
  private val fork = asyncChild("fork")(d => new FourPhaseFork(new CoreState, 2, cell, d))
  private val address = asyncChild("address")(d => new FourPhaseStage(new CoreState,
    new MemoryRequest, Execute.request, timing, d))
  private val join = asyncChild("join")(d => new FourPhaseJoin(new CoreState, new MemoryResponse, timing, cell, d))
  private val execute = asyncChild("execute")(d => new FourPhaseStage(
    new ExecutionInput, new ExecutionResult,
    (p: ExecutionInput) => Execute.step(p.state, p.response, p.a, p.b),
    executeTiming, d))
  private val registers = asyncChild("register_file")(d => new ArchitecturalRegisters(d,registerCell))
  private val arrival = Module(new ControlGate(1,GateOperation.Buffer,registerCell))
  arrival.reset := reset; arrival.a := state.out.req.asUInt; arrival.b := 0.U
  contract.primitive("register_arrival",arrival,Map("WIDTH"->BigInt(1),"OP"->BigInt(0),
    "DELAY_FS"->BigInt(registerCell.fs),"RESET_VALUE"->BigInt(0)),contract.endpoint("register_reset",reset),
    "four-phase state request captures one writeback before following operand evaluation")
  registers.arrival := arrival.q.asBool
  registers.write := state.out.bits.writeback
  private val writeback = Module(new ControlGate(1,GateOperation.Buffer,RegisterTiming.forward))
  writeback.reset := reset; writeback.a := state.out.req.asUInt; writeback.b := 0.U
  contract.primitive("request_guard",writeback,Map("WIDTH"->BigInt(1),"OP"->BigInt(0),
    "DELAY_FS"->BigInt(RegisterTiming.forward.fs),"RESET_VALUE"->BigInt(0)),"register_reset",
    "min 31 ns > arrival max 10 ns + selection max 10 ns + register Q max 10 ns; hold token until acknowledge")
  fork.in.req := writeback.q.asBool; fork.in.bits := state.out.bits; state.out.ack := fork.in.ack
  FourPhase.connect(address.in, fork.out(0))
  FourPhase.connect(join.left, fork.out(1))
  FourPhase.connect(request, address.out)
  FourPhase.connect(join.right, response)
  execute.in.req := join.out.req; join.out.ack := execute.in.ack
  execute.in.bits.state := join.out.bits.left; execute.in.bits.response := join.out.bits.right
  execute.in.bits.registers := registers.values
  state.in.req := execute.out.req; execute.out.ack := state.in.ack
  state.in.bits := execute.out.bits.state
  trace := execute.out.bits.trace
  traceEvent := execute.out.req
  contract.endpoint("trace_event", traceEvent)
  trace.elements.foreach { case (name, field) => contract.endpoint(s"trace_$name", field) }
}

object EmitFourPhase extends App {
  require(args.length == 1, "Usage: EmitFourPhase output-directory")
  ExportDesign.emit(new FourPhaseCore, Paths.get(args(0)))
}
