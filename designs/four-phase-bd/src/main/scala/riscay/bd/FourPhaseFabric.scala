// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled.FourPhaseStage
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ControlGate, GateOperation}
import chiselasync.protocol.FourPhase
import riscay._
import riscay.soc.MemoryMap

/** Native return-to-zero transaction fabric. Constant ROM and static access
  * faults complete without a service clock. Stateful endpoints own dynamic
  * protection, WAIT, loader arbitration, and accepted SRAM side effects.
  * The source holds its request through acknowledgement return. A service
  * transaction cannot release that return until BOTH endpoint handshakes drain.
  */
class FourPhaseFabric(config: McuConfiguration, timing: BundledTiming,
    domain: ResetDomain) extends AsyncModule(domain) {
  val request = fourPhaseInput("request", new MemoryRequest)
  val response = fourPhaseOutput("response", new MemoryResponse)
  val serviceRequest = fourPhaseOutput("service_request", new MemoryRequest)
  val serviceResponse = fourPhaseInput("service_response", new MemoryResponse)
  private val resetRef = contract.endpoint("reset", reset)
  private val cell = ModelTime.ps(1000)
  private def gate(id: String, op: GateOperation.Value, a: Bool, b: Bool = false.B,
      delay: ModelTime = cell, resetValue: Int = 0): Bool = {
    val g = Module(new ControlGate(1, op, delay, resetValue))
    g.reset := reset; g.a := a.asUInt; g.b := b.asUInt
    contract.primitive(id, g, Map("WIDTH"->BigInt(1), "OP"->BigInt(op.id),
      "DELAY_FS"->BigInt(delay.fs), "RESET_VALUE"->BigInt(resetValue)), resetRef,
      "BD fabric control; preserve gates and qualify decode, response mux and return-path timing")
    g.q.asBool
  }
  // Use public primitives only. Reset values keep the De Morgan network low
  // throughout reset release; no private library AND module/resource binding.
  private def and(id: String, a: Bool, b: Bool): Bool = {
    val na = gate(id+"_na", GateOperation.Invert, a, resetValue=1)
    val nb = gate(id+"_nb", GateOperation.Invert, b, resetValue=1)
    val either = gate(id+"_or", GateOperation.Or, na, nb, resetValue=1)
    gate(id, GateOperation.Invert, either)
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
  private val guarded = gate("request_guard", GateOperation.Buffer, request.req, delay=timing.matchedDelay)
  serviceRequest.bits := r
  serviceRequest.req := and("service_select", guarded, !local)
  private val returned = and("service_returned", serviceRequest.ack, serviceResponse.req)
  private val available = gate("response_available", GateOperation.Or, local, returned)
  private val reply = asyncChild("reply")(d => new FourPhaseStage(new MemoryResponse, new MemoryResponse,
    (x: MemoryResponse) => x, timing, d))
  reply.in.req := and("reply_offer", guarded, available)
  private val muxResult = WireDefault(Mux(local, localReply, serviceResponse.bits))
  reply.in.bits := muxResult
  // Capture is a separate handshake from the upstream request return. Retain
  // the endpoint acknowledgement until that endpoint withdraws its request.
  private val serviceAck = Module(new AsymmetricCElement(1, 1, 0, cell))
  serviceAck.reset := reset; serviceAck.common := serviceResponse.req.asUInt
  serviceAck.rising := (reply.in.ack && !local).asUInt; serviceAck.falling := 0.U
  serviceResponse.ack := serviceAck.q
  contract.primitive("service_response_ack", serviceAck, Map("COMMON"->BigInt(1), "RISING"->BigInt(1),
    "FALLING"->BigInt(0), "DELAY_FS"->BigInt(cell.fs), "RESET_VALUE"->BigInt(0),
    "COMMON_INVERT"->BigInt(0), "RISING_INVERT"->BigInt(0), "FALLING_INVERT"->BigInt(0)),
    resetRef, "retain endpoint acknowledge until endpoint request returns low")
  FourPhase.connect(response, reply.out)
  // Rising acknowledge commits the held request; return waits for both service
  // channels. Otherwise a stale high response could satisfy the next request.
  private val completed = Module(new AsymmetricCElement(1, 0, 3, cell))
  completed.reset := reset; completed.common := reply.in.ack.asUInt
  completed.rising := 1.U; completed.falling := Cat(serviceRequest.ack, serviceResponse.req, serviceResponse.ack)
  request.ack := completed.q
  contract.primitive("completion", completed, Map("COMMON"->BigInt(1), "RISING"->BigInt(0),
    "FALLING"->BigInt(3), "DELAY_FS"->BigInt(cell.fs), "RESET_VALUE"->BigInt(0),
    "COMMON_INVERT"->BigInt(0), "RISING_INVERT"->BigInt(0), "FALLING_INVERT"->BigInt(0)),
    resetRef, "ack return waits for reply capture and both endpoint handshakes; coordinated application reset")
  contract.endpoint("mux_sources", Cat(r.asUInt, serviceResponse.bits.asUInt))
  contract.endpoint("mux_result", muxResult)
  contract.dataPathTiming("response_mux", "mux_sources", "mux_result", timing,
    "ROM/static permission decode and service response mux", Seq("reply"))
  contract.capacity(1)
}
