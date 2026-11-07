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

/** RF consumes writeback before the fork; execute never reads that old effect.
  * Keep the continuation by named field, with a live schema check below.
  */
private[bd] class CoreContinuation extends Bundle {
  val pc = UInt(32.W)
  val operation = UInt(2.W)
  val instruction = UInt(32.W)
  val address = UInt(32.W)
  val storeData = UInt(32.W)
  val mask = UInt(4.W)
}
private[bd] object CoreContinuation {
  def project(s: CoreState): CoreContinuation = {
    val c = Wire(new CoreContinuation)
    require(c.elements.keySet == s.elements.keySet - "writeback", "CORE_CONTINUATION_FIELDS")
    c.elements.foreach { case (name, field) =>
      require(field.getWidth == s.elements(name).getWidth, s"CORE_CONTINUATION_WIDTH:$name")
      field := s.elements(name)
    }
    c
  }
  def restore(c: CoreContinuation): CoreState = {
    val s = WireDefault(0.U.asTypeOf(new CoreState))
    c.elements.foreach { case (name, field) => s.elements(name) := field }
    s
  }
}
private[bd] class ContinuationInput extends Bundle {
  val state = new CoreContinuation
  val response = new MemoryResponse
  val registers = Vec(15, UInt(32.W))
  def restore: ExecutionInput = {
    val x = Wire(new ExecutionInput)
    x.state := CoreContinuation.restore(state)
    x.response := response; x.registers := registers
    x
  }
}
private[bd] class StoredExecutionResult(retainTrace: Boolean) extends Bundle {
  val state = new CoreState
  val trace = if(retainTrace) Some(new Retirement) else None
}

/** Sequential RV32E core. No periodic clock; memory owns each request's latency.
  * The state branch waits for the matching response before executing a microstep.
  */
class FourPhaseCore(domain: ResetDomain = new ResetDomain("root"),
    registerCell: ModelTime = RegisterTiming.minimum,
    timing: BundledTiming = OwnerTiming.base,
    executeTiming: BundledTiming = OwnerTiming.execute,
    retainTrace: Boolean = true) extends AsyncModule(domain) {
  private val nativeTiming = OwnerTiming.passive(timing)
  RegisterTiming.check(registerCell)
  val request = fourPhaseOutput("request", new MemoryRequest)
  val response = fourPhaseInput("response", new MemoryResponse)
  val trace = IO(Output(new Retirement))
  val traceEvent = IO(Output(Bool()))
  private val cell = ModelTime.ps(1000)
  private val state = asyncChild("state")(d => new FourPhaseFifo(new CoreState, 1,
    nativeTiming, Seq(CoreState.initial), cell, d))
  private val fork = asyncChild("fork")(d => new FourPhaseFork(new CoreState, 2, cell, d))
  private val address = asyncChild("address")(d => new FourPhaseStage(new CoreState,
    new MemoryRequest, Execute.request, nativeTiming, d))
  private val join = asyncChild("join")(d => new FourPhaseJoin(new CoreContinuation, new MemoryResponse, nativeTiming, cell, d))
  private val execute = asyncChild("execute")(d => new FourPhaseStage(
    new ContinuationInput, new StoredExecutionResult(retainTrace),
    (continuation: ContinuationInput) => {
      val p = continuation.restore
      val result = Execute.step(p.state, p.response, p.a, p.b)
      val stored = Wire(new StoredExecutionResult(retainTrace))
      stored.state := result.state
      stored.trace.foreach(_ := result.trace)
      stored
    },
    OwnerTiming.passive(executeTiming), d))
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
  join.left.req := fork.out(1).req; fork.out(1).ack := join.left.ack
  join.left.bits := CoreContinuation.project(fork.out(1).bits)
  FourPhase.connect(request, address.out)
  FourPhase.connect(join.right, response)
  execute.in.req := join.out.req; join.out.ack := execute.in.ack
  execute.in.bits.state := join.out.bits.left; execute.in.bits.response := join.out.bits.right
  execute.in.bits.registers := registers.values
  state.in.req := execute.out.req; execute.out.ack := state.in.ack
  state.in.bits := execute.out.bits.state
  // The pad-level build has no trace consumer. Project before protected storage;
  // default verification/debug exports retain the complete retirement interface.
  trace := execute.out.bits.trace.getOrElse(0.U.asTypeOf(new Retirement))
  traceEvent := (if(retainTrace) execute.out.req else false.B)
  if(retainTrace) {
    contract.endpoint("trace_event", traceEvent)
    trace.elements.foreach { case (name, field) => contract.endpoint(s"trace_$name", field) }
  }
}

object EmitFourPhase extends App {
  require(args.length == 1, "Usage: EmitFourPhase output-directory")
  ExportDesign.emit(new FourPhaseCore, Paths.get(args(0)))
}
