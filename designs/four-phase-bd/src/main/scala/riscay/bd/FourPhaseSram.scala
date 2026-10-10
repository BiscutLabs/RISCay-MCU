// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.protocol.FourPhase
import riscay.soc._

/** Native word ownership and four ordered byte rendezvous. Consumer acceptance
  * returns the sole execution credit; the next word cannot touch a macro before
  * that event. The synchronous macro boundary supplies one completion per byte,
  * including disabled lanes. POR aborts tokens; application reset is absent.
  * Complete transforms use simulation budgets, not physical qualification.
  */
class FourPhaseSram(domain: ResetDomain) extends AsyncModule(domain) {
  val request = fourPhaseInput("request", new SramWordRequest)
  val response = fourPhaseOutput("response", UInt(32.W))
  val byteRequest = (0 until 4).map(i => fourPhaseOutput(s"byte_request_$i", new SramByteRequest))
  val byteResponse = (0 until 4).map(i => fourPhaseInput(s"byte_response_$i", UInt(8.W)))
  private val timing = BundledTiming.Simulation
  private val cell = ModelTime.ps(1000)
  private val credit = asyncChild("credit")(d => new FourPhaseFifo(Bool(), 1, timing, Seq(false.B), cell, d))

  private val owner = asyncChild("owner")(d => new FourPhaseJoin(Bool(), new SramWordRequest, timing, cell, d))
  FourPhase.connect(owner.left, credit.out); FourPhase.connect(owner.right, request)
  private val prepare = asyncChild("prepare")(d => new FourPhaseStage(new Joined(Bool(), new SramWordRequest), new SramWork,
    (x: Joined[Bool, SramWordRequest]) => {
      val w = Wire(new SramWork); w.request := x.right; w.result := 0.U; w
    }, timing, d))
  FourPhase.connect(prepare.in, owner.out)
  private var previous = prepare.out
  for(lane <- 0 until 4) {
    val fork = asyncChild(s"lane_${lane}_fork")(d => new FourPhaseFork(new SramWork, 2, cell, d))
    val issue = asyncChild(s"lane_${lane}_issue")(d => new FourPhaseStage(new SramWork, new SramByteRequest,
      (w: SramWork) => {
        val b = Wire(new SramByteRequest)
        b.address := Cat(w.request.address(31,2), lane.U(2.W))
        b.write := w.request.write; b.data := w.request.data(8*lane+7,8*lane)
        b.enable := !w.request.write || w.request.mask(lane); b
      }, timing, d))
    val join = asyncChild(s"lane_${lane}_join")(d => new FourPhaseJoin(new SramWork, UInt(8.W), timing, cell, d))
    val capture = asyncChild(s"lane_${lane}_capture")(d => new FourPhaseStage(new Joined(new SramWork, UInt(8.W)), new SramWork,
      (x: Joined[SramWork, UInt]) => {
        val w = WireDefault(x.left)
        when(!x.left.request.write) {
          val bytes = Wire(Vec(4, UInt(8.W))); bytes := x.left.result.asTypeOf(bytes)
          bytes(lane) := x.right; w.result := bytes.asUInt
        }
        w
      }, timing, d))
    FourPhase.connect(fork.in, previous)
    FourPhase.connect(issue.in, fork.out(0)); FourPhase.connect(join.left, fork.out(1))
    FourPhase.connect(byteRequest(lane), issue.out); FourPhase.connect(join.right, byteResponse(lane))
    FourPhase.connect(capture.in, join.out)
    previous = capture.out
  }
  // Consumer acknowledgement returns execution credit. Carry the retired
  // operation bit, stable before response.req and held until credit capture
  // acknowledges the final result. Credit availability alone gates execution;
  // its payload is ignored by prepare and remains observable in the contract.
  credit.in.bits := previous.bits.request.write; credit.in.req := response.ack
  dontTouch(credit.in)
  previous.ack := credit.in.ack
  response.req := previous.req; response.bits := previous.bits.result
  dontTouch(previous)
  contract.endpoint("reset", reset)
}

/** Explicit word admission/publication and per-byte macro crossings. The
  * service clock tracks admission and drainage; lane sequencing and read
  * assembly live in the native child.
  */
class SramAccess(domain: ResetDomain) extends ClockedBridge(domain, 2) {
  val io = IO(Flipped(new SramAccessPort))
  // Services uses busy for admission and always accepts the final reply. Keep
  // the complete registered crossing ABI even when those ports are constant.
  dontTouch(io)
  val native = asyncChild("native")(d => new FourPhaseSram(d))

  val command = asyncChild("command_bridge")(d => new DecoupledToFourPhase(new SramWordRequest, 2, d))
  val reply = asyncChild("reply_bridge")(d => new FourPhaseToDecoupled(UInt(32.W), 2, d))
  command.clock := clock; reply.clock := clock
  FourPhase.connect(native.request, command.out); FourPhase.connect(reply.in, native.response)
  val requests = (0 until 4).map(i => asyncChild(s"byte_request_$i")(d => new FourPhaseToDecoupled(new SramByteRequest, 2, d)))
  val replies = (0 until 4).map(i => asyncChild(s"byte_reply_$i")(d => new DecoupledToFourPhase(UInt(8.W), 2, d)))
  for(i <- 0 until 4) {
    requests(i).clock := clock; replies(i).clock := clock
    FourPhase.connect(requests(i).in, native.byteRequest(i)); FourPhase.connect(native.byteResponse(i), replies(i).out)
    io.bytes(i) <> requests(i).out; replies(i).in <> io.completions(i)
  }
  private val returned = synchronizedControl(!reply.in.req) && !reply.in.ack
  private val bytesReturned = requests.map(b => synchronizedControl(!b.in.req) && !b.in.ack).reduce(_ && _)
  withClockAndReset(clock, localReset) {
    val active = RegInit(false.B)
    val drained = returned && bytesReturned && command.in.ready && replies.map(_.in.ready).reduce(_ && _)
    command.in.valid := io.request.valid && !active && drained
    command.in.bits := io.request.bits; io.request.ready := !active && drained
    when(command.in.fire) { active := true.B }
    io.response.valid := reply.out.valid && active; io.response.bits := reply.out.bits
    reply.out.ready := io.response.ready && active
    when(io.response.fire) { active := false.B }
    io.busy := active || !drained || localReset.asBool
  }
  contract.endpoint("reset", reset)
}
