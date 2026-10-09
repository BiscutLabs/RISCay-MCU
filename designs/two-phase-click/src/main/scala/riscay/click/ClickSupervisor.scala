// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ClickTiming, ModelTime}
import chiselasync.protocol.TwoPhase
import riscay.soc._
import riscay.profiles.PowerPolicy

/** Permanent POR-only power and safety-sample state. No application clock or
  * reset advances this loop. Whole-transform simulation budgets are not STA.
  */
class ClickSupervisor(p: SocParameters, policy: PowerPolicy, domain: ResetDomain) extends AsyncModule(domain) {
  val command = twoPhaseInput("command", new SupervisorCommand)
  val reply = twoPhaseOutput("reply", new SupervisorState)
  private val timing = ClickTiming.Simulation
  private val cell = ModelTime.ps(1000)
  private val state = asyncChild("state")(d => new PhaseDecoupledClickBuffer(new SupervisorState, timing, Some(SupervisorState.initial), d))
  private val join = asyncChild("join")(d => new ClickJoin(new SupervisorState, new SupervisorCommand, timing, d))
  private val update = asyncChild("update")(d => new ClickStage(new Joined(new SupervisorState, new SupervisorCommand),
    new SupervisorState, (x: Joined[SupervisorState, SupervisorCommand]) => transition(x.left,x.right), timing, d))
  private val fork = asyncChild("fork")(d => new ClickFork(new SupervisorState, d))
  val start = IO(Input(Bool())); state.start.get := start; contract.endpoint("start",start)
  TwoPhase.connect(join.left,state.out); TwoPhase.connect(join.right,command)
  TwoPhase.connect(update.in,join.out); TwoPhase.connect(fork.in,update.out)
  TwoPhase.connect(state.in,fork.left); TwoPhase.connect(reply,fork.right)

  private def transition(s: SupervisorState, c: SupervisorCommand): SupervisorState = {
    val n = WireDefault(s)
    def sat(a: UInt, b: UInt): UInt = { val sum=a +& b; Mux(sum(32), "hffffffff".U, sum(31,0)) }
    val a=c.capture
    n.sample.age := sat(s.sample.age,c.elapsedUpper)
    when(a.seen) {
      n.sample.sequence := s.sample.sequence + a.count
      n.sample.valid := a.valid; n.sample.fault := !a.valid
      n.sample.calibrated := a.valid && a.calibrated
      when(a.hadValid) { n.sample.value := a.value; n.sample.age := a.tailAge; n.sample.never := false.B }
    }
    val v=n.sample
    val good=v.valid && !v.never && v.age < p.freshLimitMs.max(0).U && v.value >= 8000.U && v.value <= 18000.U
    val prefixAge=sat(s.sample.age,Mux(a.hadValid,a.firstAge,c.elapsedUpper))
    val historyGood=s.sample.valid && !s.sample.never && prefixAge < p.freshLimitMs.max(0).U &&
      s.sample.value >= 8000.U && s.sample.value <= 18000.U && !a.failed &&
      (!a.hadValid || (a.minimum >= 8000.U && a.maximum <= 18000.U &&
        a.maximumGap < p.freshLimitMs.max(0).U && a.tailAge < p.freshLimitMs.max(0).U))
    // Retain hazards consumed between policy ticks, even if later commands
    // publish a recovered sample before the next evaluation.
    val unsafe = !good || (s.sample.valid && !s.sample.never && !historyGood)
    n.sensingFault := s.mode === 1.U && (s.sensingFault || unsafe)
    val inactive=c.gpio(2)
    val gpioStable= !c.gpioChanged(2)
    val conditions=Seq(inactive,!inactive,good && v.value >= policy.restartMv.U && inactive,
      good && v.value < policy.shutdownMv.U)
    val continuous=Seq(gpioStable,gpioStable,
      gpioStable && historyGood && s.sample.value >= policy.restartMv.U && (!a.hadValid || a.minimum >= policy.restartMv.U),
      historyGood && s.sample.value < policy.shutdownMv.U && (!a.hadValid || a.maximum < policy.shutdownMv.U))
    val limits=Seq(policy.ackStableMs,policy.ackStableMs,policy.restartConfirmMs,policy.lowConfirmMs)
    // Input discontinuities cancel qualification; queued time alone is never
    // evidence of stable inputs. An interrupted/coalesced outage gets no credit.
    for(i <- 0 until 4) {
      when(!conditions(i) || !continuous(i) || c.observationGap) {
        n.counts(i) := 0.U; n.observed(i) := false.B
      }.elsewhen(c.tick) {
        n.observed(i) := true.B
        val credit=Mux(s.observed(i),c.observationMs,c.observationMs-c.firstObservationMs)
        val total=sat(s.counts(i),credit)
        n.counts(i) := Mux(total >= limits(i).U,limits(i).U,total)
      }
    }
    val halt=s.qualified && s.counts(1) >= policy.ackStableMs.U
    def off(): Unit = {
      n.mode := 0.U; n.waitOff := true.B; n.waitRun := false.B; n.waitShutdown := false.B; n.qualified := false.B
      n.counts(0) := 0.U; n.counts(1) := 0.U; n.counts(2) := 0.U
    }
    when(!policy.enabled.B) { n.mode := 3.U; n.fault := 1.U }
      .elsewhen(c.tick) {
        when(inactive && gpioStable && !c.observationGap && !s.waitRun && (s.mode === 1.U || s.mode === 2.U) && s.counts(0) >= policy.ackStableMs.U) {
          n.qualified := true.B
        }
        switch(s.mode) {
          is(0.U) {
            when(!s.waitOff && conditions(2) && continuous(2) && !c.observationGap &&
              s.counts(0) >= policy.ackStableMs.U && s.counts(2) >= policy.restartConfirmMs.U &&
              c.now-s.offAt >= policy.minimumOffMs.U) {
              n.mode := 1.U; n.waitRun := true.B; n.qualified := false.B; n.counts(0) := 0.U; n.counts(1) := 0.U; n.fault := 0.U
            }
          }
          is(1.U) {
            when(halt) { off(); n.fault := 5.U }
              .elsewhen(s.sensingFault || unsafe || s.counts(3) >= policy.lowConfirmMs.U) {
                n.mode := 2.U; n.waitShutdown := true.B; n.fault := Mux(!s.sensingFault && !unsafe,2.U,3.U)
              }
          }
          is(2.U) {
            when(halt) { off(); n.fault := 5.U }
              .elsewhen(!s.waitShutdown && c.now-s.shutdownAt >= policy.shutdownTimeoutMs.U) {
                off(); n.timeouts := s.timeouts+1.U; n.fault := 4.U
                when(s.timeouts === 2.U) { n.mode := 3.U }
              }
          }
        }
      }
    // Record logical dwell epochs after the clocked output projection applies
    // the transition; queued bridge time must not predate that feedback. LF
    // quantization and publication latency still need physical timing bounds.
    when(s.mode === 0.U && s.waitOff && !c.power) { n.offAt := c.now; n.waitOff := false.B }
    when(s.mode === 2.U && s.waitShutdown && c.shutdown) { n.shutdownAt := c.now; n.waitShutdown := false.B }
    when(s.mode === 1.U && s.waitRun) {
      n.counts(0) := 0.U; n.counts(1) := 0.U
      n.observed(0) := false.B; n.observed(1) := false.B; n.qualified := false.B
      when(c.power) { n.waitRun := false.B }
    }
    n
  }
}
