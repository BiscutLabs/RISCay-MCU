// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._
import riscay.soc._

/** This variant owns clock, reset, wake and endpoint integration. */
abstract class ClickPlatform(p: SocParameters, board: SocParameters => BoardProfile) extends SocTop(p) {
  val watchdog = withClockAndReset(watchdogClock, reset) { Module(new Watchdog(p.watchdogCycles, p.watchdogHoldCycles)) }
  val assertion = reset.asBool || watchdog.io.expired
  val release = withClockAndReset(serviceClock, assertion.asAsyncReset) {
    val stages = RegInit(3.U(2.W)); stages := Cat(stages(0), false.B); stages
  }
  systemReset := assertion || release.orR
  resetReason := watchdog.io.reason
  // Reset pins assert immediately. POR-only logic consumes a conventional
  // two-flop copy instead; both assertion and release cross before use as data.
  val cpuResetActive = withClockAndReset(serviceClock, reset) {
    val first = RegNext(systemReset, true.B)
    RegNext(first, true.B)
  }
  val watchdogReasonActive = withClockAndReset(serviceClock, reset) {
    val first = RegNext(watchdog.io.reason, false.B)
    RegNext(first, false.B)
  }
  val crashCount = withClockAndReset(serviceClock, reset) {
    val previous = RegNext(cpuResetActive, true.B)
    val count = RegInit(0.U(32.W))
    when(cpuResetActive && !previous && !count.andR) { count := count + 1.U }
    count
  }
  protected val workClock = Wire(Clock())
  protected val fabric = withClockAndReset(workClock, reset) { Module(new ClickServices(p, board)) }
  // Persistent native Click phases and state reset only on POR.
  val programAccess = asyncChild("program_access")(d => new SramAccess(d))
  val ramAccess = asyncChild("ram_access")(d => new SramAccess(d))
  programAccess.clock := workClock; ramAccess.clock := workClock
  programAccess.io <> fabric.io.program; ramAccess.io <> fabric.io.ram
  val control = asyncChild("control")(d => new ClickControl(p, d))
  val controlCommandBridge = asyncChild("control_command_bridge")(d => new DecoupledToClick(new ControlCommand, d))
  val controlReplyBridge = asyncChild("control_reply_bridge")(d => new ClickToDecoupled(new ControlReply, d))
  controlCommandBridge.clock := workClock; controlReplyBridge.clock := workClock
  val controlStart = withClockAndReset(serviceClock, reset) {
    val stages = RegInit(0.U(2.W)); stages := Cat(stages(0), true.B); stages.andR
  }
  control.start := controlStart
  chiselasync.protocol.TwoPhase.connect(control.command, controlCommandBridge.out)
  chiselasync.protocol.TwoPhase.connect(controlReplyBridge.in, control.reply)
  controlCommandBridge.in <> fabric.io.controlCommand
  fabric.io.controlReply <> controlReplyBridge.out
  // Preserve the registered bridge ABI even when this profile ignores state fields.
  dontTouch(controlReplyBridge.out)
  val telemetry = asyncChild("telemetry")(d => new ClickTelemetry(p, fabric.telemetryWords, d))
  val telemetryCommandBridge = asyncChild("telemetry_command_bridge")(d =>
    new DecoupledToClick(new TelemetryCommand(p.config.measurements.size), d))
  val telemetryReplyBridge = asyncChild("telemetry_reply_bridge")(d =>
    new ClickToDecoupled(new TelemetryReply(p.config.measurements.size, fabric.telemetryWords.size), d))
  telemetry.start := controlStart
  chiselasync.protocol.TwoPhase.connect(telemetry.command, telemetryCommandBridge.out)
  chiselasync.protocol.TwoPhase.connect(telemetryReplyBridge.in, telemetry.reply)
  telemetryCommandBridge.clock := workClock; telemetryReplyBridge.clock := workClock
  telemetryCommandBridge.in <> fabric.telemetryCommand
  fabric.telemetryReply <> telemetryReplyBridge.out
  dontTouch(telemetryReplyBridge.out)
  // Click reply acceptance returns the clocked bridge to idle on that edge.
  // The outstanding command covers reply wait; native guard drainage is clockless.
  fabric.io.telemetryDraining := !telemetryCommandBridge.in.ready
  // Immutable profile selects this design's native permanent controller.
  val supervisorBridges = board(p) match {
    case profile: riscay.profiles.GroundlarkBoard =>
      val supervisor = asyncChild("supervisor")(d => new ClickSupervisor(p,profile.policy,d))
      val supervisorCommandBridge = asyncChild("supervisor_command_bridge")(d => new DecoupledToClick(new SupervisorCommand, d))
      val supervisorReplyBridge = asyncChild("supervisor_reply_bridge")(d => new ClickToDecoupled(new SupervisorState, d))
      supervisorCommandBridge.clock := workClock; supervisorReplyBridge.clock := workClock
      supervisor.start := controlStart
      chiselasync.protocol.TwoPhase.connect(supervisor.command,supervisorCommandBridge.out)
      chiselasync.protocol.TwoPhase.connect(supervisorReplyBridge.in,supervisor.reply)
      supervisorCommandBridge.in <> fabric.boardCommand
      supervisorReplyBridge.out.ready := fabric.boardReply.ready
      fabric.boardReply.valid := supervisorReplyBridge.out.valid
      val result=supervisorReplyBridge.out.bits
      val power=result.mode === 1.U || result.mode === 2.U
      val shutdown=result.mode === 2.U
      fabric.boardReply.bits.outputs := Cat(0.U(30.W),shutdown,power)
      fabric.boardReply.bits.registers := VecInit(Seq(result.mode.pad(32),Cat(0.U(31.W),power),Cat(0.U(31.W),shutdown),
        Cat(0.U(31.W),result.qualified && result.counts(1) >= profile.policy.ackStableMs.U),result.fault.pad(32),result.timeouts.pad(32)))
      dontTouch(supervisorReplyBridge.out)
      fabric.io.boardDraining := !supervisorCommandBridge.in.ready
      Some((supervisorCommandBridge,supervisorReplyBridge))
    case _: GenericBoard =>
      fabric.boardCommand.ready := true.B; fabric.boardReply.valid := false.B
      fabric.boardReply.bits := 0.U.asTypeOf(new BoardResult); fabric.io.boardDraining := false.B
      None
    case _ => throw new IllegalArgumentException("Board profile needs a native implementation in this design")
  }
  p.lowPower match {
    case Some(lp) =>
      val scaler = asyncChild("elapsed_scaler")(d => new ElapsedTicks(
        Seq(lp.tickMicros, lp.minimumTickMicros, lp.maximumTickMicros), d))
      scaler.clock := workClock; scaler.io <> fabric.io.elapsedScaling
    case None =>
      fabric.io.elapsedScaling.consumed := 0.U; fabric.io.elapsedScaling.valid := false.B
      fabric.io.elapsedScaling.single := false.B; fabric.io.elapsedScaling.busy := false.B
      fabric.io.elapsedScaling.elapsed := 0.U.asTypeOf(fabric.io.elapsedScaling.elapsed)
  }
  p.adc match {
    case Some(a) =>
      val scaler = asyncChild("sample_scaler")(d => new SampleScaler(a.numerator, a.denominator, d))
      scaler.clock := workClock; scaler.io <> fabric.io.sampleScaling
    case None =>
      fabric.io.sampleScaling.busy := false.B; fabric.io.sampleScaling.done := false.B
      fabric.io.sampleScaling.value := 0.U
  }
  fabric.io.cpuReset := systemReset
  fabric.io.cpuResetActive := cpuResetActive
  fabric.io.crashCount := crashCount
  fabric.io.frontClock := serviceClock
  p.lowPower match {
    case Some(lp) =>
      val timebase = withClockAndReset(watchdogClock, reset) { Module(new SleepTimebase(lp)) }
      val gate = withClockAndReset(serviceClock, reset) { Module(new RetainedClock) }
      gate.io.gray := timebase.io.gray; gate.io.consumedGray := fabric.io.consumedGray
      gate.io.canSleep := fabric.io.canSleep; gate.io.activity := fabric.io.activity
      gate.io.drainDemand := fabric.io.drainDemand
      gate.io.forceRun := cpuResetActive
      workClock := gate.io.clockOut; fabric.io.clockRunning := gate.io.running
      fabric.io.timeGray := gate.io.synchronizedGray
      sleepEntries := gate.io.entries; sleeping := !gate.io.running
      if(lp.stopServiceClock) {
        val wake = withClockAndReset(serviceClock, reset) { Module(new ServiceClockWake) }
        val mask = ((BigInt(1) << p.config.gpioCount) - 1).U(32.W)
        wake.io.event := timebase.io.gray =/= fabric.io.consumedGray || ((gpioIn ^ fabric.io.observedGpio) & mask).orR
        wake.io.scl := scl; wake.io.sda := sda
        wake.io.selected := fabric.io.hostSelected; wake.io.rejected := fabric.io.hostRejected
        wake.io.running := gate.io.running || systemReset
        serviceClockEnable := wake.io.enable
      } else { serviceClockEnable := true.B }
    case None =>
      workClock := serviceClock; fabric.io.clockRunning := true.B
      fabric.io.timeGray := 0.U; sleepEntries := 0.U; sleeping := false.B
      serviceClockEnable := true.B
  }
  fabric.io.sleepEntries := sleepEntries
  fabric.io.scl := scl; fabric.io.sda := sda; sdaLow := fabric.io.sdaLow
  fabric.io.gpioIn := gpioIn; gpioOut := fabric.io.gpioOut; gpioOe := fabric.io.gpioOe
  fabric.io.adcMiso := adcMiso; adcCsN := fabric.io.adcCsN; adcSclk := fabric.io.adcSclk
  fabric.io.watchdogReason := watchdogReasonActive; watchdog.io.heartbeat := fabric.io.heartbeat
  fabric.io.watchdogAck := watchdog.io.acknowledge
  mode := fabric.io.mode; programmed := fabric.io.programmed; locked := fabric.io.locked
  commit := fabric.io.commit
}
