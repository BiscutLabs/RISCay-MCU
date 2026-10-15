// SPDX-License-Identifier: Apache-2.0
// Isolated experimental owner; physical recipe unqualified. No production instantiation.
package riscay.click.experimental

import chisel3._
import chisel3.util.Cat
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives._
import riscay.soc.SramByteRequest
import riscay.soc.experimental.{ByteModelTiming, MacroBytePins, MacroByteObservations}

/** Native two-phase Click byte owner. reset is cold bootstrap or joined-quiescent rebase.
  * A launch grant commits the byte. Stop never resets active pins or timers.
  */
class ClickMacroByteOwner(domain: ResetDomain, t: ByteModelTiming = ByteModelTiming())
    extends AsyncModule(domain) {
  val request = twoPhaseInput("request", new SramByteRequest)
  val result = twoPhaseOutput("result", UInt(8.W))
  val stopRequest = IO(Input(Bool()))
  val sourceQuiescent = IO(Input(Bool()))
  val rearm = IO(Input(Bool()))
  val pins = IO(new MacroBytePins)
  val observe = IO(Output(new MacroByteObservations))
  private val resetRef = contract.endpoint("bootstrap_reset", reset)

  // Each implementation owns its state. Only public primitive APIs are used.
  private def delay(id: String, input: Bool, ps: Long, resetValue: Int = 0): Bool = {
    val c = Module(new ControlGate(1, GateOperation.Buffer, ModelTime.ps(ps), resetValue))
    c.suggestName(id); c.reset := reset; c.a := input; c.b := 0.U
    contract.primitive(id, c, Map("WIDTH" -> BigInt(1), "OP" -> BigInt(0),
      "DELAY_FS" -> BigInt(ps * 1000), "RESET_VALUE" -> BigInt(resetValue)),
      resetRef, "finite digital guard; no physical bound; reset only after joined quiescence")
    c.q.asBool
  }
  private def held(id: String, common: Bool, set: Bool): Bool = {
    val c = Module(new AsymmetricCElement(1, 1, 0, ModelTime.ps(t.cellPs)))
    c.suggestName(id); c.reset := reset; c.common := common; c.rising := set; c.falling := 0.U
    contract.primitive(id, c, Map("COMMON" -> BigInt(1), "RISING" -> BigInt(1),
      "FALLING" -> BigInt(0), "DELAY_FS" -> BigInt(t.cellPs * 1000), "RESET_VALUE" -> BigInt(0),
      "COMMON_INVERT" -> BigInt(0), "RISING_INVERT" -> BigInt(0), "FALLING_INVERT" -> BigInt(0)),
      resetRef, "retains set until common falls; no combinational Boolean feedback")
    c.q
  }
  private def capture(id: String, input: UInt, trigger: Bool): UInt = {
    val c = Module(new EventRegister(input.getWidth, ModelTime.ps(t.cellPs)))
    c.suggestName(id); c.reset := reset; c.d := input; c.trigger := trigger
    contract.primitive(id, c, Map("WIDTH" -> BigInt(input.getWidth),
      "DELAY_FS" -> BigInt(t.cellPs * 1000), "RESET_VALUE" -> BigInt(0)), resetRef,
      "native event capture; source retained through declared capture setup/hold")
    c.q
  }

  val ready = Wire(Bool()); val fullyReturned = Wire(Bool())
  val retired = Wire(Bool()); val stopGrant = Wire(Bool())
  val launchGrant = Wire(Bool()); val cycleComplete = Wire(Bool())
  val publication = Wire(Bool()); val sourceRelease = Wire(Bool())
  val guardsEmpty = Wire(Bool()); val initialEmpty = Wire(Bool())
  val stopPending = held("stop_history", true.B, stopRequest)
  val armed = held("armed_history", true.B,
    rearm && sourceQuiescent && initialEmpty && guardsEmpty && !stopPending)
  val acceptedInput = Wire(Bool()); val publishedOutput = Wire(Bool())
  val pending = request.req =/= acceptedInput
  val qualifiedPending = delay("request_guard", pending, t.requestPs)
  val contender = held("launch_contender", !retired && !stopGrant,
    qualifiedPending && ready && armed && (request.bits.address < 1024.U))
  retired := held("retired_history", contender, fullyReturned)
  val arbiter = Module(new Mutex(ModelTime.ps(t.mutexPs), MutexPolicy(t.mutexPolicy),
    t.mutexSeed, ModelTime.ps(t.mutexJitterPs)))
  arbiter.suggestName("launch_stop_mutex")
  arbiter.reset := reset; arbiter.request := Cat(stopPending, contender)
  launchGrant := arbiter.grant(0); stopGrant := arbiter.grant(1)
  contract.primitive("launch_stop_mutex", arbiter, Map("RESOLVE_FS" -> BigInt(t.mutexPs * 1000),
    "RESOLVE_MAX_FS" -> BigInt((t.mutexPs + t.mutexJitterPs) * 1000),
    "POLICY" -> BigInt(t.mutexPolicy), "SEED" -> BigInt(t.mutexSeed)), resetRef,
    "finite digital arbitration only; persistent stop/launch; observe grant low before contender reuse")

  val pinBits = capture("pin_payload", request.bits.asUInt, launchGrant)
  val targetInput = capture("target_input", request.req.asUInt, launchGrant).asBool
  val targetOutput = capture("target_output", (!publishedOutput).asUInt, launchGrant).asBool
  val saved = pinBits.asTypeOf(new SramByteRequest)
  val active = saved.enable && (saved.address < 1024.U)
  val pinsCaptured = delay("pins_guard", launchGrant, t.pinsPs)
  sourceRelease := delay("source_hold_guard", launchGrant, t.sourcePs)
  val setupReady = delay("setup_guard", launchGrant, t.setupPs)
  val pulseDone = Wire(Bool())
  pins.A := saved.address(9, 0); pins.D := saved.data
  pins.GWEN := !saved.write; pins.WEN := 0.U
  pins.CEN := delay("cen_driver", !(pinsCaptured && active && !cycleComplete), t.cellPs, 1)
  pins.CLK := delay("clock_driver", setupReady && active && !pulseDone, t.cellPs)
  val highReady = delay("high_guard", pins.CLK, t.highPs)
  val accessReady = delay("access_guard", pins.CLK, t.accessPs)
  val periodReady = delay("period_guard", pins.CLK, t.periodPs)
  val periodSeen = held("period_history", setupReady, periodReady)
  val resultCapture = delay("capture_driver",
    (active && accessReady) || (!active && setupReady), t.cellPs)
  result.bits := capture("result_payload", Mux(saved.write || !active, 0.U(8.W), pins.Q), resultCapture)
  val captureHold = delay("capture_hold_guard", resultCapture, t.captureHoldPs)
  pulseDone := held("pulse_done_history", setupReady, captureHold && (!active || highReady))
  val lowReady = delay("low_guard", !pins.CLK, t.lowPs)
  cycleComplete := held("cycle_history", setupReady,
    pulseDone && !pins.CLK && lowReady && (!active || periodSeen))
  publication := delay("publication_guard", cycleComplete, t.publicationPs)

  acceptedInput := capture("accepted_input", targetInput.asUInt, sourceRelease).asBool
  request.ack := acceptedInput
  publishedOutput := capture("published_output", targetOutput.asUInt, publication).asBool
  result.req := publishedOutput
  // The immutable target phase prevents old ACK equality retiring a new token.
  fullyReturned := publication && cycleComplete && (acceptedInput === targetInput) &&
    (publishedOutput === targetOutput) && (result.ack === targetOutput) && !pins.CLK && pins.CEN
  initialEmpty := !request.req && !acceptedInput && !publishedOutput && !result.ack
  guardsEmpty := !Seq(pinsCaptured, sourceRelease, setupReady, highReady, accessReady,
    periodReady, periodSeen, resultCapture, captureHold, pulseDone, cycleComplete,
    publication).reduce(_ || _) && lowReady && !pins.CLK && pins.CEN
  // A zero grant is observed through this explicit admission gate. Merely dropping
  // and reasserting a contender before grant release is forbidden.
  ready := !contender && !retired && !launchGrant && !stopGrant && guardsEmpty && (result.req === result.ack)
  val electricalQuiescent = stopGrant && !contender && !retired && !launchGrant &&
    guardsEmpty && (result.req === result.ack)
  observe.armed := armed; observe.launchRequest := contender; observe.launchGrant := launchGrant
  observe.stopPending := stopPending; observe.stopGrant := stopGrant; observe.ready := ready
  observe.pinsCaptured := pinsCaptured; observe.sourceRelease := sourceRelease
  observe.setupReady := setupReady; observe.highReady := highReady; observe.accessReady := accessReady
  observe.resultCapture := resultCapture; observe.captureHold := captureHold; observe.pulseDone := pulseDone
  observe.lowReady := lowReady; observe.periodSeen := periodSeen; observe.cycleComplete := cycleComplete
  observe.publication := publication; observe.fullyReturned := fullyReturned; observe.retired := retired
  observe.guardsEmpty := guardsEmpty; observe.electricalQuiescent := electricalQuiescent
  observe.joinedQuiescent := electricalQuiescent && sourceQuiescent
  contract.endpoint("actual_macro_clock", pins.CLK)
  contract.endpoint("actual_macro_enable", pins.CEN)
  contract.endpoint("pin_capture_owned", observe.launchGrant)
  contract.endpoint("source_release", observe.sourceRelease)
  contract.endpoint("result_capture", observe.resultCapture)
  contract.endpoint("joined_quiescence", observe.joinedQuiescent)
}
