// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming, ModelTime}
import chiselasync.protocol.FourPhase
import riscay.soc._

object ConstantScaling {
  // One radix-2 step in mixed quotient/remainder form. Bounds permit at most
  // two subtractions. All divisions here are Scala elaboration-time constants.
  def step(q: UInt, r: UInt, bit: Bool, numerator: Int, denominator: Int): (UInt, UInt) = {
    val total = (r << 1) +& Mux(bit, (numerator % denominator).U, 0.U)
    val carry = Mux(total >= (2L * denominator).U, 2.U, Mux(total >= denominator.U, 1.U, 0.U))
    val remainder = Mux(carry === 2.U, total - (2L * denominator).U,
      Mux(carry === 1.U, total - denominator.U, total))
    (((q << 1) + Mux(bit, (numerator / denominator).U, 0.U) + carry)(31,0), remainder)
  }
}


/** Clockless fractional time. Four native stages each consume eight radix-2
  * bits. The retained state token serializes targets, including count wrap.
  * Simulation data budgets cover complete transforms; physical closure is separate.
  */
class FourPhaseElapsed(micros: Seq[Int], domain: ResetDomain) extends AsyncModule(domain) {
  require(micros.nonEmpty && micros.forall(_ > 0))
  private val lanes = micros.size
  val command = fourPhaseInput("command", UInt(32.W))
  val reply = fourPhaseOutput("reply", new ElapsedResult(lanes))

  private val timing = BundledTiming.Simulation
  private val cell = ModelTime.ps(1000)
  private val state = asyncChild("state")(d => new FourPhaseFifo(new ElapsedState(lanes), 1, timing, Seq(0.U.asTypeOf(new ElapsedState(lanes))), cell, d))
  private val join = asyncChild("join")(d => new FourPhaseJoin(new ElapsedState(lanes), UInt(32.W), timing, cell, d))
  private val prepare = asyncChild("prepare")(d => new FourPhaseStage(new Joined(new ElapsedState(lanes), UInt(32.W)),
    new ElapsedWork(lanes), (x: Joined[ElapsedState, UInt]) => {
      val w = WireDefault(0.U.asTypeOf(new ElapsedWork(lanes)))
      val delta = x.right - x.left.consumed
      w.state := x.left; w.target := x.right; w.delta := delta
      for((us,lane) <- micros.zipWithIndex) {
        var q = 0.U(32.W); var r = 0.U(10.W)
        for(bit <- 31 to 24 by -1) {
          val next = ConstantScaling.step(q, r, delta(bit), us, 1000)
          q = next._1; r = next._2(9,0)
        }
        w.quotient(lane) := q; w.remainder(lane) := r
      }
      w
    }, timing, d))
  private val steps = (1 until 3).map { group =>
    asyncChild(s"radix_$group")(d => new FourPhaseStage(new ElapsedWork(lanes), new ElapsedWork(lanes),
      (x: ElapsedWork) => {
        val w = WireDefault(x)
        for((us, lane) <- micros.zipWithIndex) {
          var q = x.quotient(lane); var r = x.remainder(lane)
          for(bit <- (31 - group * 8) to (24 - group * 8) by -1) {
            val next = ConstantScaling.step(q, r, x.delta(bit), us, 1000)
            q = next._1; r = next._2(9,0)
          }
          w.quotient(lane) := q; w.remainder(lane) := r
        }
        w
      }, timing, d))
  }
  private val finish = asyncChild("finish")(d => new FourPhaseStage(new ElapsedWork(lanes), new ElapsedResult(lanes),
    (x: ElapsedWork) => {
      val r = Wire(new ElapsedResult(lanes)); r.state := x.state
      r.state.consumed := x.target; r.single := x.delta === 1.U
      for((us,lane) <- micros.zipWithIndex) {
        var q = x.quotient(lane); var rem = x.remainder(lane)
        for(bit <- 7 to 0 by -1) {
          val next = ConstantScaling.step(q, rem, x.delta(bit), us, 1000)
          q = next._1; rem = next._2(9,0)
        }
        val sum = rem +& x.state.fraction(lane); val carry = sum >= 1000.U
        r.state.fraction(lane) := Mux(carry, sum - 1000.U, sum)
        r.elapsed(lane) := q + carry
      }
      r
    }, timing, d))
  private val fork = asyncChild("fork")(d => new FourPhaseFork(new ElapsedResult(lanes), 2, cell, d))
  dontTouch(fork.out(0))

  FourPhase.connect(join.left, state.out); FourPhase.connect(join.right, command)
  FourPhase.connect(prepare.in, join.out)
  FourPhase.connect(steps.head.in, prepare.out)
  steps.sliding(2).foreach { pair => FourPhase.connect(pair(1).in, pair(0).out) }
  FourPhase.connect(finish.in, steps.last.out); FourPhase.connect(fork.in, finish.out)
  state.in.bits := fork.out(0).bits.state; state.in.req := fork.out(0).req; fork.out(0).ack := state.in.ack
  FourPhase.connect(reply, fork.out(1))
}

/** Three clockless four-bit rational transforms; no multiplier or divider. */
class FourPhaseSample(numerator: Int, denominator: Int, domain: ResetDomain) extends AsyncModule(domain) {
  require(numerator > 0 && denominator > 0)
  private val width = log2Ceil(denominator).max(1)
  private val timing = BundledTiming.Simulation
  private val cell = ModelTime.ps(1000)
  val command = fourPhaseInput("command", UInt(12.W))
  val reply = fourPhaseOutput("reply", UInt(32.W))
  private val prepare = asyncChild("prepare")(d => new FourPhaseStage(UInt(12.W), new SampleWork(width),
    (raw: UInt) => { val w = WireDefault(0.U.asTypeOf(new SampleWork(width))); w.raw := raw; w }, timing, d))
  private val steps = (0 until 3).map { group =>
    asyncChild(s"radix_$group")(d => new FourPhaseStage(new SampleWork(width), new SampleWork(width), (x: SampleWork) => {
      val w = WireDefault(x); var q = x.quotient; var r = x.remainder
      for(bit <- (11 - group * 4) to (8 - group * 4) by -1) {
        val next = ConstantScaling.step(q, r, x.raw(bit), numerator, denominator)
        q = next._1; r = next._2(width-1,0)
      }
      w.quotient := q; w.remainder := r; w
    }, timing, d))
  }
  FourPhase.connect(prepare.in, command); FourPhase.connect(steps.head.in, prepare.out)
  steps.sliding(2).foreach { pair => FourPhase.connect(pair(1).in, pair(0).out) }
  dontTouch(steps.last.out) // Preserve the complete registered native boundary.
  reply.bits := steps.last.out.bits.quotient; reply.req := steps.last.out.req; steps.last.out.ack := reply.ack
}

/** POR-only clocked capture/publication boundary, not an arithmetic machine.
  * Consumed advances on the same edge as time/age publication. Keep the source
  * running through request and response bridge drainage, even with zero elapsed.
  */
class ElapsedTicks(micros: Seq[Int], domain: ResetDomain) extends ClockedBridge(domain, 2) {
  val io = IO(new ElapsedScalingPort(micros.size))
  dontTouch(io) // Profiles may ignore observation flags or duplicate elapsed lanes.
  val native = asyncChild("native")(d => new FourPhaseElapsed(micros, d))
  private val commandBridge = asyncChild("command_bridge")(d => new DecoupledToFourPhase(UInt(32.W), 2, d))
  private val replyBridge = asyncChild("reply_bridge")(d => new FourPhaseToDecoupled(new ElapsedResult(micros.size), 2, d))
  commandBridge.clock := clock; replyBridge.clock := clock
  FourPhase.connect(native.command, commandBridge.out); FourPhase.connect(replyBridge.in, native.reply)

  private val returned = synchronizedControl(!replyBridge.in.req && !replyBridge.in.ack)
  withClockAndReset(clock, localReset) {
    val active = RegInit(false.B); val consumed = RegInit(0.U(32.W))
    commandBridge.in.bits := io.target
    commandBridge.in.valid := !active && returned && io.target =/= consumed
    when(commandBridge.in.fire) { active := true.B }
    replyBridge.out.ready := active
    when(replyBridge.out.fire) { active := false.B; consumed := replyBridge.out.bits.state.consumed }
    io.consumed := consumed; io.publicationTarget := replyBridge.out.bits.state.consumed; io.valid := replyBridge.out.fire
    // Observation credit requires the live target to still match this reply.
    // Arithmetic for a once-single tick is retained even if newer ticks queued.
    io.single := io.valid && replyBridge.out.bits.single && replyBridge.out.bits.state.consumed === io.target
    io.elapsed := Mux(io.valid, replyBridge.out.bits.elapsed, 0.U.asTypeOf(io.elapsed))
    io.busy := active || !returned || !commandBridge.in.ready || io.target =/= consumed
  }
  dontTouch(replyBridge.out)
  contract.endpoint("reset", reset)
}

/** Capture each SPI result once; retain busy through native publication/drainage. */
class SampleScaler(numerator: Int, denominator: Int, domain: ResetDomain) extends ClockedBridge(domain, 2) {
  val io = IO(new SampleScalingPort)
  val native = asyncChild("native")(d => new FourPhaseSample(numerator, denominator, d))
  private val commandBridge = asyncChild("command_bridge")(d => new DecoupledToFourPhase(UInt(12.W), 2, d))
  private val replyBridge = asyncChild("reply_bridge")(d => new FourPhaseToDecoupled(UInt(32.W), 2, d))
  commandBridge.clock := clock; replyBridge.clock := clock
  FourPhase.connect(native.command, commandBridge.out); FourPhase.connect(replyBridge.in, native.reply)
  private val returned = synchronizedControl(!replyBridge.in.req && !replyBridge.in.ack)
  withClockAndReset(clock, localReset) {
    val active = RegInit(false.B); val pending = RegInit(false.B); val raw = RegInit(0.U(12.W))
    when(io.start && !active) { active := true.B; pending := true.B; raw := io.raw }
    commandBridge.in.valid := pending; commandBridge.in.bits := raw
    when(commandBridge.in.fire) { pending := false.B }
    replyBridge.out.ready := active
    when(replyBridge.out.fire) { active := false.B }
    io.done := replyBridge.out.fire; io.value := replyBridge.out.bits
    io.busy := active || !returned || !commandBridge.in.ready
  }
  contract.endpoint("reset", reset)
}
