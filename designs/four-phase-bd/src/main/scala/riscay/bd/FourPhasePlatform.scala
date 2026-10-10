// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._
import riscay.soc._

/** This variant owns clock, reset, wake and endpoint integration. */
abstract class FourPhasePlatform(p: SocParameters, board: SocParameters => BoardProfile, clockedCpuResponse: Boolean = true) extends SocTop(p) {
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
  protected val fabric = withClockAndReset(workClock, reset) { Module(new FourPhaseServices(p, board)) }
  // Application presentation cancels with the CPU. The POR-owned effect owners
  // below continue their accepted work and suppress old-lifetime completions.
  protected val completion=asyncChild("completion")(d => new FourPhaseCompletion(d))
  val completionPlan=asyncChild("completion_plan_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(new CompletionPlan, 2,d))
  val completionMemory=asyncChild("completion_memory_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(new MemoryResponse, 2,d))
  val completionTelemetry=asyncChild("completion_telemetry_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(), 2,d))
  val completionHousekeeping=asyncChild("completion_housekeeping_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(), 2,d))
  Seq(completion,completionPlan,completionMemory,completionTelemetry,completionHousekeeping)
    .foreach(_.reset:=fabric.io.cpuReset.asAsyncReset)
  Seq(completionPlan,completionMemory,completionTelemetry,completionHousekeeping).foreach(_.clock:=workClock)
  Seq(completionPlan,completionMemory,completionTelemetry,completionHousekeeping).foreach { bridge =>
    dontTouch(bridge.in); dontTouch(bridge.out)
  }
  completionPlan.in <> fabric.io.completionPlan; completionMemory.in <> fabric.io.completionMemory
  completionTelemetry.in <> fabric.io.completionTelemetry; completionHousekeeping.in <> fabric.io.completionHousekeeping
  chiselasync.protocol.FourPhase.connect(completion.plan,completionPlan.out)
  chiselasync.protocol.FourPhase.connect(completion.memory,completionMemory.out)
  chiselasync.protocol.FourPhase.connect(completion.telemetry,completionTelemetry.out)
  chiselasync.protocol.FourPhase.connect(completion.housekeeping,completionHousekeeping.out)
  // A retained phase cannot be missed between service edges. Idle is a separate
  // drainage condition, never evidence that the admitted transaction retired.
  withClockAndReset(workClock,fabric.io.cpuReset.asAsyncReset) {
    val first=RegNext(completion.retired,false.B); val second=RegNext(first,false.B)
    val seen=RegNext(second,false.B)
    fabric.io.completionRetired:=second =/= seen
    val completionReturned = !completion.response.req && !completion.response.ack
    val completionReturnedFirst=RegNext(completionReturned,false.B)
    fabric.io.completionIdle:=RegNext(completionReturnedFirst,false.B)
  }
  if(clockedCpuResponse) {
    // Verification/service-bus clients have an actual clocked consumer.
    val bridge=asyncChild("completion_fixture_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(new MemoryResponse, 2,d))
    bridge.reset:=fabric.io.cpuReset.asAsyncReset; bridge.clock:=workClock
    chiselasync.protocol.FourPhase.connect(bridge.in,completion.response)
    fabric.io.completionResponse <> bridge.out
  } else {
    // Production SoCs attach the native Fabric directly to completion.response.
    fabric.io.completionResponse.valid:=false.B
    fabric.io.completionResponse.bits:=0.U.asTypeOf(new MemoryResponse)
    fabric.io.response.ready:=false.B
  }

  val host = asyncChild("i2c")(d => new I2cTarget(p.i2cAddress,p.i2cIdleCycles,d))
  host.clock := serviceClock; host.scl := scl; host.sda := sda
  fabric.io.i2c <> host.host; sdaLow := host.pullLow
  val programAccess = asyncChild("program_access")(d => new SramAccess(d))
  val ramAccess = asyncChild("ram_access")(d => new SramAccess(d))
  programAccess.clock := workClock; ramAccess.clock := workClock
  programAccess.io <> fabric.io.program; ramAccess.io <> fabric.io.ram
  // Persistent command/state loop and both crossings are POR-only. Application
  // reset is synchronized service data, never a reset of image/lock state.
  val control = asyncChild("control")(d => new FourPhaseControl(p, d))
  val controlCommandBridge = asyncChild("control_command_bridge")(d =>
    new chiselasync.clocked.DecoupledToFourPhase(new ControlCommand, 2, d))
  val controlReplyBridge = asyncChild("control_reply_bridge")(d =>
    new chiselasync.clocked.FourPhaseToDecoupled(new ControlReply, 2, d))
  controlCommandBridge.clock := workClock; controlReplyBridge.clock := workClock
  chiselasync.protocol.FourPhase.connect(control.command, controlCommandBridge.out)
  chiselasync.protocol.FourPhase.connect(controlReplyBridge.in, control.reply)
  controlCommandBridge.in <> fabric.io.controlCommand
  fabric.io.controlReply <> controlReplyBridge.out
  // Preserve the registered bridge ABI even when this profile ignores state fields.
  dontTouch(controlReplyBridge.out)
  val housekeeping=asyncChild("housekeeping")(d => new FourPhaseHousekeeping(p,d))
  val housekeepingCommandBridge=asyncChild("housekeeping_command_bridge")(d =>
    new chiselasync.clocked.DecoupledToFourPhase(new HousekeepingCommand, 2, d))
  val housekeepingReplyBridge=asyncChild("housekeeping_reply_bridge")(d =>
    new chiselasync.clocked.FourPhaseToDecoupled(new HousekeepingReply, 2, d))
  housekeepingCommandBridge.clock:=workClock; housekeepingReplyBridge.clock:=workClock
  chiselasync.protocol.FourPhase.connect(housekeeping.command,housekeepingCommandBridge.out)
  chiselasync.protocol.FourPhase.connect(housekeepingReplyBridge.in,housekeeping.reply)
  housekeepingCommandBridge.in <> fabric.housekeepingCommand
  fabric.housekeepingReply <> housekeepingReplyBridge.out
  dontTouch(housekeepingReplyBridge.out)
  val housekeepingReturning=withClockAndReset(workClock,reset) {
    val pending=RegInit(false.B)
    when(housekeepingReplyBridge.out.fire) { pending:=true.B }
      .elsewhen(!housekeepingReplyBridge.in.ack) { pending:=false.B }
    pending
  }
  fabric.io.housekeepingDraining:= !housekeepingCommandBridge.in.ready ||
    (housekeepingReturning && housekeepingReplyBridge.in.ack)
  val telemetry = asyncChild("telemetry")(d => new FourPhaseTelemetry(p, fabric.telemetryWords, d))
  val telemetryCommandBridge = asyncChild("telemetry_command_bridge")(d =>
    new chiselasync.clocked.DecoupledToFourPhase(new TelemetryCommand(p.config.measurements.size), 2, d))
  val telemetryReplyBridge = asyncChild("telemetry_reply_bridge")(d =>
    new chiselasync.clocked.FourPhaseToDecoupled(new TelemetryReply(p.config.measurements.size, fabric.telemetryWords.size), 2, d))
  chiselasync.protocol.FourPhase.connect(telemetry.command, telemetryCommandBridge.out)
  chiselasync.protocol.FourPhase.connect(telemetryReplyBridge.in, telemetry.reply)
  telemetryCommandBridge.clock := workClock; telemetryReplyBridge.clock := workClock
  telemetryCommandBridge.in <> fabric.telemetryCommand
  fabric.telemetryReply <> telemetryReplyBridge.out
  dontTouch(telemetryReplyBridge.out)
  // The bridge ACK is already a work-clock register. Its falling edge proves
  // the synchronized native request has returned, so no second CDC is needed.
  val telemetryReturning = withClockAndReset(workClock, reset) {
    val returning = RegInit(false.B)
    when(telemetryReplyBridge.out.fire) { returning := true.B }
      .elsewhen(!telemetryReplyBridge.in.ack) { returning := false.B }
    returning
  }
  fabric.io.telemetryDraining := !telemetryCommandBridge.in.ready ||
    (telemetryReturning && telemetryReplyBridge.in.ack)
  // Immutable profile selects this design's native permanent controller.
  val supervisorBridges = board(p) match {
    case profile: riscay.profiles.GroundlarkBoard =>
      val supervisor = asyncChild("supervisor")(d => new FourPhaseSupervisor(p,profile.policy,d))
      val supervisorCommandBridge = asyncChild("supervisor_command_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(new SupervisorCommand, 2, d))
      val supervisorReplyBridge = asyncChild("supervisor_reply_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(new SupervisorState, 2, d))
      supervisorCommandBridge.clock := workClock; supervisorReplyBridge.clock := workClock

      chiselasync.protocol.FourPhase.connect(supervisor.command,supervisorCommandBridge.out)
      chiselasync.protocol.FourPhase.connect(supervisorReplyBridge.in,supervisor.reply)
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
      val returning = withClockAndReset(workClock, reset) {
        val pending=RegInit(false.B)
        when(supervisorReplyBridge.out.fire) { pending := true.B }
          .elsewhen(!supervisorReplyBridge.in.ack) { pending := false.B }
        pending
      }
      fabric.io.boardDraining := !supervisorCommandBridge.in.ready || (returning && supervisorReplyBridge.in.ack)
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
      fabric.io.elapsedScaling.publicationTarget := 0.U; fabric.io.elapsedScaling.consumed := 0.U; fabric.io.elapsedScaling.valid := false.B
      fabric.io.elapsedScaling.single := false.B; fabric.io.elapsedScaling.busy := false.B
      fabric.io.elapsedScaling.elapsed := 0.U.asTypeOf(fabric.io.elapsedScaling.elapsed)
  }
  p.adc match {
    case Some(a) =>
      val adc=asyncChild("spi_adc")(d => new SpiAdc(a,p.lowPower.isEmpty,d))
      adc.clock:=workClock; adc.io <> fabric.io.adc; adc.miso:=adcMiso
      adcCsN:=adc.csN; adcSclk:=adc.sclk
    case None =>
      fabric.io.adc.busy:=false.B; fabric.io.adc.done:=false.B; fabric.io.adc.age:=0.U
      fabric.io.adc.result:=0.U.asTypeOf(fabric.io.adc.result)
      adcCsN:=true.B; adcSclk:=false.B
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
  fabric.io.gpioIn := gpioIn; gpioOut := fabric.io.gpioOut; gpioOe := fabric.io.gpioOe
  fabric.io.watchdogReason := watchdogReasonActive; watchdog.io.heartbeat := fabric.io.heartbeat
  fabric.io.watchdogAck := watchdog.io.acknowledge
  mode := fabric.io.mode; programmed := fabric.io.programmed; locked := fabric.io.locked
  commit := fabric.io.commit
}
