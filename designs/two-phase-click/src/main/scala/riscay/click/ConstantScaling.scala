// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming, ModelTime}
import chiselasync.primitives.{EventRegister, XorGate}
import chiselasync.protocol.TwoPhase
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
class ClickElapsed(micros: Seq[Int], domain: ResetDomain,
    ownerTiming: ClickTiming = ClickTiming.Simulation,
    stepTiming: ClickTiming = OwnerTiming.elapsedStep) extends AsyncModule(domain) {
  OwnerTiming.check(ownerTiming); OwnerTiming.check(stepTiming)
  require(micros.nonEmpty && micros.forall(_ > 0))
  private val lanes = micros.size
  private val modeWidth = 1
  private val idleMode = 0.U(modeWidth.W)
  private val runMode = 1.U(modeWidth.W)
  val command = twoPhaseInput("command", UInt(32.W))
  val reply = twoPhaseOutput("reply", new ElapsedResult(lanes))
  private val timing = ownerTiming
  private val cell = ModelTime.ps(1000)
  private val resetRef = contract.endpoint("reset", reset)
  val start = IO(Input(Bool()))
  private val owner = asyncChild("owner")(d => new PhaseDecoupledClickBuffer(
    new ElapsedLoopState(lanes, modeWidth), timing,
    Some(0.U.asTypeOf(new ElapsedLoopState(lanes, modeWidth))), d))
  owner.start.get := start; contract.endpoint("start", start)
  private val step = asyncChild("step")(d => new ClickStage(
    new ElapsedLoopInput(lanes, modeWidth), new ElapsedLoopState(lanes, modeWidth),
    (x: ElapsedLoopInput) => {
      val r = WireDefault(x.state)
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
      r.mode := Mux(last, idleMode, runMode)
      when(last) { r.replyPhase := !x.state.replyPhase }
      r
    }, stepTiming, d))

  // Source reuse is allowed after command ACK; unused live source fields must
  // not enter a pending arithmetic token during later feedback turns.
  private val admitting = owner.out.bits.mode === idleMode
  step.in.bits.state := owner.out.bits
  step.in.bits.target := Mux(admitting, command.bits, 0.U)
  step.in.bits.commandPhase := admitting && command.req
  private val available = !admitting ||
    (reply.ack === owner.out.bits.replyPhase && command.req =/= owner.out.bits.commandPhase)
  step.in.req := Mux(available, owner.out.req, step.in.ack)
  owner.out.ack := step.in.ack
  TwoPhase.connect(owner.in, step.out)

  // Capture only a published, held owner token. In particular, the BD owner's
  // transparent latch q is not a valid external handshake transition.
  private val history = Module(new EventRegister(2, cell))
  history.reset := reset
  contract.primitive("history", history, Map("WIDTH" -> BigInt(2),
    "DELAY_FS" -> BigInt(cell.fs), "RESET_VALUE" -> BigInt(0)), resetRef,
    "independent external command/reply history captured on native owner publication")
  private val historyData = WireDefault(UInt(2.W), Cat(owner.out.bits.replyPhase, owner.out.bits.commandPhase))
  private val publication = Module(new XorGate(cell))
  publication.reset := reset; publication.a := owner.out.req; publication.b := owner.out.ack
  contract.primitive("publication_compare", publication, Map("DELAY_FS" -> BigInt(cell.fs)), resetRef,
    "one retained publication pulse per native owner token, independent of phase polarity")
  private val publicationEvent = WireDefault(publication.q)
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

/** Three clockless four-bit rational transforms; no multiplier or divider. */
class ClickSample(numerator: Int, denominator: Int, domain: ResetDomain) extends AsyncModule(domain) {
  require(numerator > 0 && denominator > 0)
  private val width = log2Ceil(denominator).max(1)
  private val timing = ClickTiming.Simulation
  private val cell = ModelTime.ps(1000)
  val command = twoPhaseInput("command", UInt(12.W))
  val reply = twoPhaseOutput("reply", UInt(32.W))
  private val prepare = asyncChild("prepare")(d => new ClickStage(UInt(12.W), new SampleWork(width),
    (raw: UInt) => { val w = WireDefault(0.U.asTypeOf(new SampleWork(width))); w.raw := raw; w }, timing, d))
  private val steps = (0 until 3).map { group =>
    asyncChild(s"radix_$group")(d => new ClickStage(new SampleWork(width), new SampleWork(width), (x: SampleWork) => {
      val w = WireDefault(x); var q = x.quotient; var r = x.remainder
      for(bit <- (11 - group * 4) to (8 - group * 4) by -1) {
        val next = ConstantScaling.step(q, r, x.raw(bit), numerator, denominator)
        q = next._1; r = next._2(width-1,0)
      }
      w.quotient := q; w.remainder := r; w
    }, timing, d))
  }
  TwoPhase.connect(prepare.in, command); TwoPhase.connect(steps.head.in, prepare.out)
  steps.sliding(2).foreach { pair => TwoPhase.connect(pair(1).in, pair(0).out) }
  dontTouch(steps.last.out) // Preserve the complete registered native boundary.
  reply.bits := steps.last.out.bits.quotient; reply.req := steps.last.out.req; steps.last.out.ack := reply.ack
}

/** POR-only clocked capture/publication boundary, not an arithmetic machine.
  * Consumed advances on the same edge as time/age publication. Keep the source
  * running through request and response bridge drainage, even with zero elapsed.
  */
class ElapsedTicks(micros: Seq[Int], domain: ResetDomain,
    ownerTiming: ClickTiming = ClickTiming.Simulation,
    stepTiming: ClickTiming = OwnerTiming.elapsedStep) extends ClockedBridge(domain, 2) {
  val io = IO(new ElapsedScalingPort(micros.size))
  dontTouch(io) // Profiles may ignore observation flags or duplicate elapsed lanes.
  val native = asyncChild("native")(d => new ClickElapsed(micros, d, ownerTiming, stepTiming))
  private val commandBridge = asyncChild("command_bridge")(d => new DecoupledToClick(UInt(32.W), d))
  private val replyBridge = asyncChild("reply_bridge")(d => new ClickServiceReplyReceipt(new ElapsedResult(micros.size), d))
  commandBridge.clock := clock; replyBridge.clock := clock
  TwoPhase.connect(native.command, commandBridge.out); TwoPhase.connect(replyBridge.in, native.reply)
  native.start := !localReset.asBool
  private val returned = synchronizedControl(replyBridge.in.req === replyBridge.in.ack)
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
  val native = asyncChild("native")(d => new ClickSample(numerator, denominator, d))
  private val commandBridge = asyncChild("command_bridge")(d => new DecoupledToClick(UInt(12.W), d))
  private val replyBridge = asyncChild("reply_bridge")(d => new ClickServiceReplyReceipt(UInt(32.W), d))
  commandBridge.clock := clock; replyBridge.clock := clock
  TwoPhase.connect(native.command, commandBridge.out); TwoPhase.connect(replyBridge.in, native.reply)
  private val returned = synchronizedControl(replyBridge.in.req === replyBridge.in.ack)
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
