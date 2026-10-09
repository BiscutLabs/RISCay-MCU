// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation, PhaseRegister, XorGate}
import riscay._
import riscay.soc.MemoryMap

/** Native toggle fabric: source/response parity advances for every transaction,
  * endpoint parity advances ONLY for endpoint transactions. No RTZ adapters.
  * Input remains held until the selected reply has been captured. A busy output
  * stalls both local ROM accesses and endpoint dispatch without changing data.
  */
class ClickFabric(config: McuConfiguration, timing: ClickTiming, domain: ResetDomain)
    extends AsyncModule(domain) {
  // This composed controller has a separately checked digital envelope. Do not
  // accept arbitrary stage policies until their cell bounds/pulse distribution
  // can be exported and exercised as a fabric contract in their own right.
  require(timing == ClickTiming.Simulation, "CLICK_FABRIC_REQUIRES_SIMULATION_POLICY")
  val request = twoPhaseInput("request", new MemoryRequest)
  val response = twoPhaseOutput("response", new MemoryResponse)
  val serviceRequest = twoPhaseOutput("service_request", new MemoryRequest)
  val serviceResponse = twoPhaseInput("service_response", new MemoryResponse)
  private val resetRef = contract.endpoint("reset", reset)
  private val cell = timing.controls.fire.model
  // The De Morgan ANDs each have THREE serial cell delays. The standard
  // ClickStage guard covers one atomic AND and cannot qualify this network.
  // Drain accepted phase -> pending XOR -> runnable -> capture
  // before either the source or a fast sink can change the selection/feedback.
  private val drain = timing.controls.inputPhase.max.fs + 7 * timing.controls.fire.max.fs +
    timing.clockSkew.fs + math.max(timing.pulseLow.fs, timing.hold.fs) + 1
  private val acknowledgeGuard = ModelTime(math.max(timing.acknowledgeDelay.fs, drain))
  private val outputGuard = ModelTime(math.max(timing.outputDelay.fs, drain))
  private def gate(id: String, op: GateOperation.Value, a: UInt, b: UInt = 0.U,
      width: Int = 1, delay: chiselasync.metadata.ModelTime = cell, resetValue: Int = 0): UInt = {
    val g = Module(new ControlGate(width, op, delay, resetValue))
    g.reset := reset; g.a := a; g.b := b
    contract.primitive(id, g, Map("WIDTH"->BigInt(width), "OP"->BigInt(op.id),
      "DELAY_FS"->BigInt(delay.fs), "RESET_VALUE"->BigInt(resetValue)), resetRef,
      "native Click fabric control/data; local pulse and complete response mux require separate physical qualification")
    g.q
  }
  private def and(id: String, a: UInt, b: UInt): UInt = {
    val na = gate(id+"_na", GateOperation.Invert, a, resetValue=1)
    val nb = gate(id+"_nb", GateOperation.Invert, b, resetValue=1)
    val either = gate(id+"_or", GateOperation.Or, na, nb, resetValue=1)
    gate(id, GateOperation.Invert, either)
  }
  private def xor(id: String, a: Bool, b: Bool): Bool = {
    val g = Module(new XorGate(cell)); g.reset := reset; g.a := a; g.b := b
    contract.primitive(id, g, Map("DELAY_FS"->BigInt(cell.fs)), resetRef, "native pending-phase comparator")
    g.q
  }
  private def phase(id: String): PhaseRegister = {
    val g = Module(new PhaseRegister(timing.controls.inputPhase.model)); g.reset := reset
    contract.primitive(id, g, Map("DELAY_FS"->BigInt(timing.controls.inputPhase.model.fs),
      "RESET_VALUE"->BigInt(0)), resetRef, "toggle once per selected transaction; reset all connected phases together")
    g
  }
  private val r = request.bits
  private val rom = r.address < (MemoryMap.boot.size * 4).U
  private val program = r.address >= MemoryMap.program.U && r.address < (MemoryMap.program + config.programBytes).U &&
    r.operation =/= Operation.Write.U
  private val ram = r.address >= MemoryMap.ram.U && r.address < (MemoryMap.ram + config.workingRamBytes).U &&
    r.operation =/= Operation.Fetch.U
  private val mmio = r.address >= MemoryMap.mmio.U && r.address < (MemoryMap.mmio + 76).U &&
    r.operation =/= Operation.Fetch.U && r.address(1,0) === 0.U && r.mask === 15.U
  private val local = r.operation =/= Operation.Halt.U && (rom || !(program || ram || mmio))
  private val localReply = Wire(new MemoryResponse)
  localReply.data := Mux(rom && r.operation =/= Operation.Write.U,
    VecInit(MemoryMap.boot.map(_.U(32.W)))(r.address(3,2)), 0.U)
  localReply.error := !rom || r.operation === Operation.Write.U
  private val accepted = phase("accepted_phase")
  private val issuedPhase = phase("service_request_phase")
  // Sample endpoint parity on the SAME event as the payload/source phase.
  // Local replies sample the unchanged endpoint phase; only service replies
  // advance its acknowledgement. A separately gated copy of fire can lose a
  // narrow pulse under independent cell skew, so it must not clock this state.
  private val repliedPhase = Module(new EventRegister(1, timing.controls.inputPhase.model))
  repliedPhase.reset := reset
  contract.primitive("service_response_phase", repliedPhase,
    Map("WIDTH"->BigInt(1), "DELAY_FS"->BigInt(timing.controls.inputPhase.model.fs), "RESET_VALUE"->BigInt(0)),
    resetRef, "sample endpoint parity on common capture pulse; local transactions retain endpoint phase")
  private val delayedRequest = gate("request_guard", GateOperation.Buffer, request.req.asUInt,
    delay=timing.requestDelay).asBool
  private val pending = xor("request_pending", delayedRequest, accepted.q)
  private val occupied = xor("response_occupied", accepted.q, response.ack)
  serviceRequest.bits := r
  serviceRequest.req := gate("output_delay", GateOperation.Buffer, issuedPhase.q.asUInt,
    delay=timing.outputDelay).asBool
  serviceResponse.ack := gate("return_guard", GateOperation.Buffer, repliedPhase.q.asUInt,
    delay=acknowledgeGuard).asBool
  private val endpointIdle = serviceRequest.req === serviceRequest.ack && serviceResponse.req === serviceResponse.ack
  private val issued = Module(new AsymmetricCElement(1, 1, 0, cell))
  issued.reset := reset; issued.common := pending.asUInt
  issued.rising := (!local && !occupied && endpointIdle).asUInt; issued.falling := 0.U
  contract.primitive("dispatch", issued, Map("COMMON"->BigInt(1), "RISING"->BigInt(1),
    "FALLING"->BigInt(0), "DELAY_FS"->BigInt(cell.fs), "RESET_VALUE"->BigInt(0),
    "COMMON_INVERT"->BigInt(0), "RISING_INVERT"->BigInt(0), "FALLING_INVERT"->BigInt(0)),
    resetRef, "hold one endpoint dispatch until the incoming phase is consumed; no retrigger while waiting")
  issuedPhase.trigger := issued.q
  private val endpointReply = issued.q && serviceRequest.req === serviceRequest.ack &&
    serviceResponse.req =/= serviceResponse.ack
  private val ready = gate("request_delay", GateOperation.Buffer, (local || endpointReply).asUInt,
    delay=timing.requestDelay).asBool
  private val runnable = and("runnable", pending.asUInt, (!occupied).asUInt).asBool
  private val fire = and("capture", runnable.asUInt, ready.asUInt).asBool
  // Preserve the local timing observation; a direct primitive-output alias can
  // be renamed away before the strict source-to-probe mapping check.
  private val captureEvent = WireDefault(fire)
  dontTouch(captureEvent)
  private val reply = Mux(local, localReply, serviceResponse.bits)
  private val data = gate("data_delay", GateOperation.Buffer, reply.asUInt,
    width=(new MemoryResponse).getWidth, delay=timing.data.model)
  private val payload = Module(new EventRegister((new MemoryResponse).getWidth, timing.payload.model))
  private val registerData = WireDefault(UInt((new MemoryResponse).getWidth.W), data)
  payload.reset := reset; payload.trigger := captureEvent; payload.d := registerData
  contract.primitive("payload", payload, Map("WIDTH"->BigInt((new MemoryResponse).getWidth),
    "DELAY_FS"->BigInt(timing.payload.model.fs), "RESET_VALUE"->BigInt(0)), resetRef,
    "capture reply before guarded input acknowledge and output offer; endpoint input held until guarded acknowledge")
  accepted.trigger := captureEvent
  repliedPhase.trigger := captureEvent
  repliedPhase.d := serviceResponse.req.asUInt
  request.ack := gate("acknowledge_guard", GateOperation.Buffer, accepted.q.asUInt,
    delay=acknowledgeGuard).asBool
  response.req := gate("output_guard", GateOperation.Buffer, accepted.q.asUInt,
    delay=outputGuard).asBool
  response.bits := payload.q.asTypeOf(new MemoryResponse)
  contract.endpoint("reply_sources", Cat(r.asUInt, serviceResponse.bits.asUInt))
  contract.endpoint("register_data", registerData)
  contract.endpoint("capture_event", captureEvent)
  contract.dataPathTiming("response_mux", "reply_sources", "register_data",
    BundledTiming.simulation(dataMax=timing.data.max).copy(dataDelay=timing.data),
    "complete ROM/static permission decode and service response mux before event register")
  contract.setupHold("capture_aperture", "request_request", "request_data", "register_data",
    "capture_event", "response_data", timing.setup, timing.hold)
  contract.capacity(1)
}
