// SPDX-License-Identifier: Apache-2.0
package riscay.profiles

import chisel3._
import chisel3.util._
import riscay.soc._

/** Build-time policy. Disabled defaults deliberately cannot energize the Pi.
  * Numeric limits follow Groundlark's power.c; selecting enabled values requires
  * board/battery qualification, not just passing these structural checks.
  */
final case class PowerPolicy(enabled: Boolean = false, shutdownMv: Int = 10000,
    restartMv: Int = 12000, lowConfirmMs: Int = 1000, restartConfirmMs: Int = 1000,
    shutdownTimeoutMs: Int = 10000, minimumOffMs: Int = 30000, ackStableMs: Int = 20) {
  require(ackStableMs >= 2)
  require(!enabled || (shutdownMv >= 8500 && shutdownMv <= 17500 &&
    restartMv >= shutdownMv + 500 && restartMv <= 18000 &&
    lowConfirmMs >= 1000 && lowConfirmMs <= 3600000 &&
    restartConfirmMs >= 1000 && restartConfirmMs <= 3600000 &&
    shutdownTimeoutMs >= 10000 && shutdownTimeoutMs <= 300000 &&
    minimumOffMs >= 30000 && minimumOffMs <= 86400000))
}

/** Permanent, application-independent replacement for the bootstrap power loop.
  * OFF=0 RUN=1 SHUTDOWN=2 LATCHED=3. Current-boot acknowledgement requires
  * a stable inactive level after RUN, followed by a stable active level.
  */
class GroundlarkSupervisor(p: SocParameters, policy: PowerPolicy) extends BoardController(p) {
  override def ownedRegisters: Set[Int] = (0 until 6).toSet
  require(p.config.gpioCount >= 3 && p.config.measurements.nonEmpty)
  val state = RegInit(0.U(2.W)); val fault = RegInit(0.U(3.W))
  val timeouts = RegInit(0.U(2.W)); val offAt = RegInit(0.U(32.W))
  val shutdownAt = RegInit(0.U(32.W))
  val highCount = RegInit(0.U(32.W)); val lowCount = RegInit(0.U(32.W))
  val restartCount = RegInit(0.U(32.W)); val voltageLowCount = RegInit(0.U(32.W))
  val qualified = RegInit(false.B)
  val voltage = io.samples(0)
  val good = voltage.valid && !voltage.never && voltage.age < p.freshLimitMs.max(0).U &&
    voltage.value >= 8000.U && voltage.value <= 18000.U
  val inactive = io.gpio(2)
  val halt = qualified && lowCount >= policy.ackStableMs.U
  // A confirmation accrues only across consecutive matching observations.
  // The amount is the fastest-clock lower time bound, never a count of ms
  // fabricated from a long service outage. Input changes cancel immediately.
  def confirm(condition: Bool, count: UInt, limit: Int): Unit = {
    val observed = RegInit(false.B)
    when(!condition) { count := 0.U; observed := false.B }
      .elsewhen(io.tick) {
        observed := true.B
        when(io.observationMs === 0.U) { count := 0.U; observed := false.B }
          .elsewhen(observed) {
            val next = count +& io.observationMs
            count := Mux(next >= limit.U, limit.U, next)
          }
      }
  }
  confirm(inactive, highCount, policy.ackStableMs)
  confirm(!inactive, lowCount, policy.ackStableMs)
  confirm(good && voltage.value >= policy.restartMv.U && inactive, restartCount, policy.restartConfirmMs)
  confirm(good && voltage.value < policy.shutdownMv.U, voltageLowCount, policy.lowConfirmMs)
  def off(): Unit = {
    state := 0.U; offAt := io.now; qualified := false.B
    highCount := 0.U; lowCount := 0.U; restartCount := 0.U
  }
  when(!policy.enabled.B) { state := 3.U; fault := 1.U }
    .elsewhen(io.tick) {
      when(inactive && (state === 1.U || state === 2.U) && highCount >= policy.ackStableMs.U) { qualified := true.B }
      switch(state) {
        is(0.U) {
          when(good && voltage.value >= policy.restartMv.U && highCount >= policy.ackStableMs.U &&
            restartCount >= policy.restartConfirmMs.U && io.now - offAt >= policy.minimumOffMs.U) {
            state := 1.U; qualified := false.B; highCount := 0.U; lowCount := 0.U; fault := 0.U
          }
        }
        is(1.U) {
          when(halt) { off(); fault := 5.U }
            .elsewhen(!good || voltageLowCount >= policy.lowConfirmMs.U) {
              state := 2.U; shutdownAt := io.now; fault := Mux(good, 2.U, 3.U)
            }
        }
        is(2.U) {
          when(halt) { off(); fault := 5.U }
            .elsewhen(io.now - shutdownAt >= policy.shutdownTimeoutMs.U) {
              off(); timeouts := timeouts + 1.U; fault := 4.U
              when(timeouts === 2.U) { state := 3.U }
            }
        }
      }
    }
  io.mask := 7.U; io.enables := 3.U
  io.outputs := Cat(0.U(30.W), state === 2.U, state === 1.U || state === 2.U)
  io.registers := VecInit(Seq.fill(64)(0.U(32.W)))
  io.registers(0) := state; io.registers(1) := io.outputs(0)
  io.registers(2) := io.outputs(1); io.registers(3) := halt
  io.registers(4) := fault; io.registers(5) := timeouts
}
