// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming, ModelTime}
import chiselasync.primitives.EventRegister
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


/** Bounded native nibble feedback; one through eight arithmetic turns per
  * unsigned 32-bit delta. Publication and retained fractions keep the ms ABI.
  * Digital timing is explicit; complete physical closure remains separate.
  */
class FourPhaseElapsed(micros: Seq[Int], domain: ResetDomain,
    ownerTiming: BundledTiming = OwnerTiming.base,
    stepTiming: BundledTiming = OwnerTiming.elapsedStep) extends AsyncModule(domain) {
  OwnerTiming.check(ownerTiming); OwnerTiming.check(stepTiming)
  require(micros.nonEmpty && micros.forall(_ > 0))
  private val lanes = micros.size
  private val modeWidth = 2
  private val idleMode = 0.U(modeWidth.W)
  private val runMode = 1.U(modeWidth.W)
  private val replyMode = 2.U(modeWidth.W)
  private val returnMode = 3.U(modeWidth.W)
  val command = fourPhaseInput("command", UInt(32.W))
  val reply = fourPhaseOutput("reply", new ElapsedResult(lanes))
  private val timing = OwnerTiming.passive(ownerTiming)
  private val cell = ModelTime.ps(1000)
  private val resetRef = contract.endpoint("reset", reset)
  private val owner = asyncChild("owner")(d => new FourPhaseFifo(
    new ElapsedLoopState(lanes, modeWidth), 1, timing,
    Seq(0.U.asTypeOf(new ElapsedLoopState(lanes, modeWidth))), cell, d))
  private val step = asyncChild("step")(d => new FourPhaseStage(
    new ElapsedLoopInput(lanes, modeWidth), new ElapsedLoopState(lanes, modeWidth),
    (x: ElapsedLoopInput) => {
      val r = WireDefault(x.state)
      when(x.state.mode === idleMode || x.state.mode === runMode) {
        val first = x.state.mode === idleMode
        val delta = Mux(first, x.target - x.state.target, x.state.delta)
        val leading = WireDefault(0.U(3.W))
        for(i <- 0 until 8) { when(delta(i*4+3, i*4).orR) { leading := i.U } }
        val index = Mux(first, leading, x.state.index)
        val nibble = Mux1H((0 until 8).map(i => (index === i.U) -> delta(i*4+3, i*4)))
        val last = index === 0.U
        r.delta := delta; r.index := index - 1.U
        when(first) {
          r.target := x.target; r.single := delta === 1.U
          r.commandPhase := x.commandPhase
        }
        for((us, lane) <- micros.zipWithIndex) {
          var q = Mux(first, 0.U(32.W), x.state.quotient(lane))
          var rem = Mux(first, 0.U(10.W), x.state.remainder(lane))
          for(bit <- 3 to 0 by -1) {
            val next = ConstantScaling.step(q, rem, nibble(bit), us, 1000)
            q = next._1; rem = next._2(9,0)
          }
          val sum = rem +& x.state.fraction(lane)
          val carry = sum >= 1000.U
          r.remainder(lane) := rem
          r.quotient(lane) := Mux(last, q + carry, q)
          when(last) { r.fraction(lane) := Mux(carry, sum - 1000.U, sum) }
        }
        r.mode := Mux(last, replyMode, runMode)
        when(last) { r.replyPhase := true.B }
      }.elsewhen(x.state.mode === replyMode) {
        r.mode := returnMode; r.replyPhase := false.B
      }.otherwise {
        r.mode := idleMode; r.commandPhase := false.B
      }
      r
    }, OwnerTiming.passive(stepTiming), d))

  // Four-phase source data is held through complete REQ/ACK return. Qualify it
  // only on admission; feedback turns use the retained target and delta.
  private val admitting = owner.out.bits.mode === idleMode
  step.in.bits.state := owner.out.bits
  step.in.bits.target := Mux(admitting, command.bits, 0.U)
  step.in.bits.commandPhase := admitting && command.req
  private val available = MuxLookup(owner.out.bits.mode, false.B)(Seq(
    idleMode -> command.req,
    runMode -> true.B,
    replyMode -> reply.ack,
    returnMode -> (!command.req && !reply.req && !reply.ack)))
  step.in.req := owner.out.req && available
  owner.out.ack := step.in.ack
  FourPhase.connect(owner.in, step.out)

  // Capture only a published, held owner token. In particular, the BD owner's
  // transparent latch q is not a valid external handshake transition.
  private val history = Module(new EventRegister(2, cell))
  history.reset := reset
  contract.primitive("history", history, Map("WIDTH" -> BigInt(2),
    "DELAY_FS" -> BigInt(cell.fs), "RESET_VALUE" -> BigInt(0)), resetRef,
    "independent external command/reply history captured on native owner publication")
  private val historyData = WireDefault(UInt(2.W), Cat(owner.out.bits.replyPhase, owner.out.bits.commandPhase))
  private val publicationEvent = WireDefault(owner.out.req)
  history.d := historyData; history.trigger := publicationEvent
  command.ack := history.q(0); reply.req := history.q(1)
  reply.bits.state.consumed := owner.out.bits.target
  reply.bits.state.fraction := owner.out.bits.fraction
  reply.bits.single := owner.out.bits.single; reply.bits.elapsed := owner.out.bits.quotient
  private val historyCaptured = WireDefault(UInt(2.W), history.q)
  private val ownerRequest = WireDefault(owner.out.req)
  contract.endpoint("owner_request", ownerRequest)
  contract.endpoint("history_sources", historyData); contract.endpoint("history_data", historyData)
  contract.endpoint("publication_event", publicationEvent); contract.endpoint("history_captured", historyCaptured)
  contract.setupHold("history_aperture", "owner_request", "history_sources", "history_data",
    "publication_event", "history_captured", ModelTime.ps(100), ModelTime.ps(100))
}

/** Exact finite-domain strength reduction. The input is twelve bits; the
  * result keeps the existing floor(raw*n/d), modulo-32-bit ABI.
  */
object ExactSampleRatio {
  case class Coefficient(multiplier: BigInt, shift: Int, resultWidth: Int)
  def apply(numerator: Int, denominator: Int): Coefficient = {
    require(numerator > 0 && denominator > 0)
    val common = BigInt(numerator).gcd(BigInt(denominator))
    val n = BigInt(numerator) / common
    val d = BigInt(denominator) / common
    val maximum = BigInt(4095) * n / d
    val width = maximum.bitLength.max(1).min(32)
    if(maximum == 0) return Coefficient(0,0,width)
    // 2^k > 4095*d makes the upward reciprocal error smaller than 1/d,
    // the distance of any nonintegral exact quotient from its next integer.
    // Search lower shifts too, but accept only exhaustive finite-domain equality.
    val guaranteedShift = (BigInt(4095)*d).bitLength
    val result = (0 to guaranteedShift).iterator.map { k =>
      val m = ((n << k) + d - 1) / d
      Coefficient(m,k,width)
    }.find { c =>
      (0 to 4095).forall(x => ((BigInt(x)*c.multiplier) >> c.shift) == BigInt(x)*n/d)
    }
    require(result.nonEmpty,"EXACT_SAMPLE_RECIPROCAL_NOT_FOUND")
    result.get
  }
}

/** One native arithmetic stage; no periodic clock or coefficient state.
  * Coefficients are elaboration constants, never a profile-specific policy.
  * Keep only the live quotient in protected storage; pad the ABI after capture.
  */
class FourPhaseSample(numerator: Int, denominator: Int, domain: ResetDomain,
    timing: BundledTiming = OwnerTiming.sampleScale) extends AsyncModule(domain) {
  OwnerTiming.check(timing)
  private val coefficient = ExactSampleRatio(numerator,denominator)
  val command = fourPhaseInput("command", UInt(12.W))
  val reply = fourPhaseOutput("reply", UInt(32.W))
  private val scale = asyncChild("scale")(d => new FourPhaseStage(
    UInt(12.W), UInt(coefficient.resultWidth.W), (raw: UInt) => {
      if(coefficient.multiplier == 0) 0.U(coefficient.resultWidth.W)
      else {
        // Never truncate before the shift: generic ratios can exceed 32 bits.
        val product = raw * coefficient.multiplier.U
        val quotient = product >> coefficient.shift
        quotient(coefficient.resultWidth-1,0)
      }
    },OwnerTiming.passive(timing),d))
  FourPhase.connect(scale.in,command)
  reply.bits:=scale.out.bits.pad(32);reply.req:=scale.out.req;scale.out.ack:=reply.ack
  dontTouch(scale.out)
}

/** POR-only clocked capture/publication boundary, not an arithmetic machine.
  * Consumed advances on the same edge as time/age publication. Keep the source
  * running through request and response bridge drainage, even with zero elapsed.
  */
class ElapsedTicks(micros: Seq[Int], domain: ResetDomain,
    ownerTiming: BundledTiming = OwnerTiming.base,
    stepTiming: BundledTiming = OwnerTiming.elapsedStep) extends ClockedBridge(domain, 2) {
  val io = IO(new ElapsedScalingPort(micros.size))
  dontTouch(io) // Profiles may ignore observation flags or duplicate elapsed lanes.
  val native = asyncChild("native")(d => new FourPhaseElapsed(micros, d, ownerTiming, stepTiming))
  private val commandBridge = asyncChild("command_bridge")(d => new DecoupledToFourPhase(UInt(32.W), 2, d))
  private val replyBridge = asyncChild("reply_bridge")(d => new FourPhaseServiceReplyReceipt(new ElapsedResult(micros.size), d))
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
    io.publicationElapsed := replyBridge.out.bits.elapsed
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
  private val replyBridge = asyncChild("reply_bridge")(d => new FourPhaseServiceReplyReceipt(UInt(32.W), d))
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
