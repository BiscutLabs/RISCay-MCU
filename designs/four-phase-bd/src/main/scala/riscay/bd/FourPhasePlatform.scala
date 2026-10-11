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
  // Every pulse restarts the release history on the ungated service clock.
  // Eight edges hold at least 350 ns at the 20 MHz ceiling, beyond the
  // 250 ns application-island reset-settlement budget. Assertion is immediate.
  protected val applicationResetRequest = WireDefault(reset.asBool || watchdog.io.expired)
  val release = withClockAndReset(serviceClock, applicationResetRequest.asAsyncReset) {
    val n=ApplicationResetContract.releaseEdges
    val stages = RegInit(((BigInt(1)<<n)-1).U(n.W)); stages := Cat(stages(n-2,0), false.B); stages
  }
  systemReset := applicationResetRequest || release.orR
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
  protected val admission=asyncChild("admission")(d => new FourPhaseAdmission(d))
  val admissionGrant=asyncChild("admission_grant_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  Seq(admission,admissionGrant).foreach(_.reset:=fabric.io.cpuReset.asAsyncReset)
  admissionGrant.clock:=workClock
  chiselasync.protocol.FourPhase.connect(admission.returned,completion.creditReturn)
  admission.responseIdle:= !completion.response.req && !completion.response.ack
  chiselasync.protocol.FourPhase.connect(admissionGrant.in,admission.grant)
  fabric.io.admissionGrant <> admissionGrant.out
  dontTouch(admissionGrant.in); dontTouch(admissionGrant.out)
  // Idle only confirms drainage. The native grant owns admission credit.
  withClockAndReset(workClock,fabric.io.cpuReset.asAsyncReset) {
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
  // POR identity/effects survive application reset. Only CPU reply eligibility
  // resets immediately; retained reset debt cancels queued uncommitted grants.
  val ramSource=asyncChild("ram_source")(d => new FourPhaseRamSource(d))
  val ramReserve=asyncChild("ram_reserve_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val ramGrant=asyncChild("ram_grant_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  val ramDecision=asyncChild("ram_decision_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val ramPublication=asyncChild("ram_publication_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  Seq(ramReserve,ramDecision,ramPublication).foreach { b =>
    b.clock:=workClock; dontTouch(b.in); dontTouch(b.out)
  }
  ramGrant.clock:=workClock; dontTouch(ramGrant.in); dontTouch(ramGrant.out)
  chiselasync.protocol.FourPhase.connect(ramSource.reserve,ramReserve.out)
  chiselasync.protocol.FourPhase.connect(ramGrant.in,ramSource.grant)
  chiselasync.protocol.FourPhase.connect(ramSource.decision,ramDecision.out)
  chiselasync.protocol.FourPhase.connect(ramSource.publication,ramPublication.out)
  ramReserve.in <> fabric.io.ramSource.reserve; fabric.io.ramSource.grant <> ramGrant.out
  ramDecision.in <> fabric.io.ramSource.decision; ramPublication.in <> fabric.io.ramSource.publication
  ramSource.applicationReset:=fabric.io.cpuReset.asAsyncReset
  ramSource.wordDrained:= !ramAccess.io.busy // Excludes its own receipt bridges.
  fabric.io.ramSource.eligible:=ramSource.eligible
  val ramOwnerIdle=withClockAndReset(workClock,reset) {
    val first=RegNext(ramSource.idle,false.B); RegNext(first,false.B)
  }
  val ramSourceEmpty=ramOwnerIdle && !ramAccess.io.busy && ramReserve.in.ready &&
    ramDecision.in.ready && ramPublication.in.ready && !ramGrant.out.valid
  val ramResetDebt=withClockAndReset(workClock,fabric.io.cpuReset.asAsyncReset) {
    val debt=RegInit(true.B)
    // Restart the release history on EVERY raw pulse, even between clock edges.
    val previousSafe=RegInit(false.B)
    previousSafe:=ramSourceEmpty && !fabric.io.cpuResetActive
    when(previousSafe && ramSourceEmpty && !fabric.io.cpuResetActive) { debt:=false.B }
    debt
  }
  fabric.io.ramSource.resetDebt:=ramResetDebt
  fabric.io.ramSource.draining:=ramResetDebt || !ramSourceEmpty
  // Persistent command/state loop and both crossings are POR-only. Application
  // reset is synchronized service data, never a reset of image/lock state.
  val programSource=asyncChild("program_source")(d => new FourPhaseProgramSource(d))
  val programReserve=asyncChild("program_reserve_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val programGrant=asyncChild("program_grant_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  val programDecision=asyncChild("program_decision_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val programPublication=asyncChild("program_publication_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val programStored=asyncChild("program_stored_bridge")(d => new FourPhaseStoredReceipt(d))
  Seq(programReserve,programDecision,programPublication).foreach { b =>
    b.clock:=workClock; dontTouch(b.in); dontTouch(b.out)
  }
  programGrant.clock:=workClock; dontTouch(programGrant.in); dontTouch(programGrant.out)
  programStored.clock:=workClock; dontTouch(programStored.in); dontTouch(programStored.out)
  chiselasync.protocol.FourPhase.connect(programStored.in,programSource.stored)
  fabric.io.programSource.stored <> programStored.out
  fabric.io.programSource.ownerLoader:=programSource.ownerLoader
  chiselasync.protocol.FourPhase.connect(programSource.reserve,programReserve.out)
  chiselasync.protocol.FourPhase.connect(programGrant.in,programSource.grant)
  chiselasync.protocol.FourPhase.connect(programSource.decision,programDecision.out)
  chiselasync.protocol.FourPhase.connect(programSource.publication,programPublication.out)
  programReserve.in <> fabric.io.programSource.reserve; fabric.io.programSource.grant <> programGrant.out
  programDecision.in <> fabric.io.programSource.decision; programPublication.in <> fabric.io.programSource.publication
  programSource.applicationReset:=fabric.io.cpuReset.asAsyncReset
  programSource.wordDrained:= !programAccess.io.busy // Excludes its own receipt bridges.
  fabric.io.programSource.eligible:=programSource.eligible
  val programOwnerIdle=withClockAndReset(workClock,reset) {
    val first=RegNext(programSource.idle,false.B); RegNext(first,false.B)
  }
  val programSourceEmpty=programOwnerIdle && !programAccess.io.busy && programReserve.in.ready &&
    programDecision.in.ready && programPublication.in.ready && !programGrant.out.valid && !programStored.out.valid
  val programResetDebt=withClockAndReset(workClock,fabric.io.cpuReset.asAsyncReset) {
    val debt=RegInit(true.B)
    // Restart the release history on EVERY raw pulse, even between clock edges.
    val previousSafe=RegInit(false.B)
    previousSafe:=programSourceEmpty && !fabric.io.cpuResetActive
    when(previousSafe && programSourceEmpty && !fabric.io.cpuResetActive) { debt:=false.B }
    debt
  }
  fabric.io.programSource.resetDebt:=programResetDebt
  fabric.io.programSource.draining:=programResetDebt || !programSourceEmpty
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

  // Native receipt ownership is POR-only. The client recovery fence remains
  // clocked until 10b2c2; debt alone never pauses its own recovery dispatch.
  val telemetrySource=asyncChild("telemetry_source")(d => new FourPhasePublicationSource(d))
  val telemetryReserve=asyncChild("telemetry_reserve_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val telemetryGrant=asyncChild("telemetry_grant_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  val telemetryDecision=asyncChild("telemetry_decision_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val telemetryPublication=asyncChild("telemetry_publication_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val telemetryDrain=asyncChild("telemetry_drain_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  Seq(telemetryReserve,telemetryDecision,telemetryPublication).foreach { b =>
    b.clock:=workClock; dontTouch(b.in); dontTouch(b.out)
  }
  Seq(telemetryGrant,telemetryDrain).foreach { b => b.clock:=workClock; dontTouch(b.in); dontTouch(b.out) }
  chiselasync.protocol.FourPhase.connect(telemetrySource.reserve,telemetryReserve.out)
  chiselasync.protocol.FourPhase.connect(telemetryGrant.in,telemetrySource.grant)
  chiselasync.protocol.FourPhase.connect(telemetrySource.decision,telemetryDecision.out)
  chiselasync.protocol.FourPhase.connect(telemetrySource.publication,telemetryPublication.out)
  chiselasync.protocol.FourPhase.connect(telemetryDrain.in,telemetrySource.drain)
  telemetryReserve.in <> fabric.io.telemetrySource.reserve
  fabric.io.telemetrySource.grant <> telemetryGrant.out
  telemetryDecision.in <> fabric.io.telemetrySource.decision
  telemetryPublication.in <> fabric.io.telemetrySource.publication
  fabric.io.telemetrySource.drain <> telemetryDrain.out
  telemetrySource.applicationReset:=fabric.io.cpuReset.asAsyncReset
  fabric.io.telemetrySource.eligible:=telemetrySource.eligible
  val telemetryOwnerIdle=withClockAndReset(workClock,reset) {
    val first=RegNext(telemetrySource.idle,false.B); RegNext(first,false.B)
  }
  val telemetrySourceEmpty=telemetryOwnerIdle && telemetryReserve.in.ready &&
    telemetryDecision.in.ready && telemetryPublication.in.ready && !telemetryGrant.out.valid && !telemetryDrain.out.valid
  val telemetryResetDebt=withClockAndReset(workClock,fabric.io.cpuReset.asAsyncReset) {
    val debt=RegInit(true.B); val previousSafe=RegInit(false.B)
    val safe=telemetrySourceEmpty && fabric.io.telemetrySource.quiet && !fabric.io.cpuResetActive
    previousSafe:=safe
    when(previousSafe && safe) { debt:=false.B }
    debt
  }
  fabric.io.telemetrySource.occupied:= !telemetrySourceEmpty
  fabric.io.telemetrySource.resetDebt:=telemetryResetDebt
  fabric.io.telemetrySource.draining:=telemetryResetDebt || !telemetrySourceEmpty

  // Native receipt ownership is POR-only. The client recovery fence remains
  // clocked until 10b2c2; debt alone never pauses its own recovery dispatch.
  val housekeepingSource=asyncChild("housekeeping_source")(d => new FourPhasePublicationSource(d))
  val housekeepingReserve=asyncChild("housekeeping_reserve_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val housekeepingGrant=asyncChild("housekeeping_grant_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  val housekeepingDecision=asyncChild("housekeeping_decision_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val housekeepingPublication=asyncChild("housekeeping_publication_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val housekeepingDrain=asyncChild("housekeeping_drain_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  Seq(housekeepingReserve,housekeepingDecision,housekeepingPublication).foreach { b =>
    b.clock:=workClock; dontTouch(b.in); dontTouch(b.out)
  }
  Seq(housekeepingGrant,housekeepingDrain).foreach { b => b.clock:=workClock; dontTouch(b.in); dontTouch(b.out) }
  chiselasync.protocol.FourPhase.connect(housekeepingSource.reserve,housekeepingReserve.out)
  chiselasync.protocol.FourPhase.connect(housekeepingGrant.in,housekeepingSource.grant)
  chiselasync.protocol.FourPhase.connect(housekeepingSource.decision,housekeepingDecision.out)
  chiselasync.protocol.FourPhase.connect(housekeepingSource.publication,housekeepingPublication.out)
  chiselasync.protocol.FourPhase.connect(housekeepingDrain.in,housekeepingSource.drain)
  housekeepingReserve.in <> fabric.io.housekeepingSource.reserve
  fabric.io.housekeepingSource.grant <> housekeepingGrant.out
  housekeepingDecision.in <> fabric.io.housekeepingSource.decision
  housekeepingPublication.in <> fabric.io.housekeepingSource.publication
  fabric.io.housekeepingSource.drain <> housekeepingDrain.out
  housekeepingSource.applicationReset:=fabric.io.cpuReset.asAsyncReset
  fabric.io.housekeepingSource.eligible:=housekeepingSource.eligible
  val housekeepingOwnerIdle=withClockAndReset(workClock,reset) {
    val first=RegNext(housekeepingSource.idle,false.B); RegNext(first,false.B)
  }
  val housekeepingSourceEmpty=housekeepingOwnerIdle && housekeepingReserve.in.ready &&
    housekeepingDecision.in.ready && housekeepingPublication.in.ready && !housekeepingGrant.out.valid && !housekeepingDrain.out.valid
  val housekeepingResetDebt=withClockAndReset(workClock,fabric.io.cpuReset.asAsyncReset) {
    val debt=RegInit(true.B); val previousSafe=RegInit(false.B)
    val safe=housekeepingSourceEmpty && fabric.io.housekeepingSource.quiet && !fabric.io.cpuResetActive
    previousSafe:=safe
    when(previousSafe && safe) { debt:=false.B }
    debt
  }
  fabric.io.housekeepingSource.occupied:= !housekeepingSourceEmpty
  fabric.io.housekeepingSource.resetDebt:=housekeepingResetDebt
  fabric.io.housekeepingSource.draining:=housekeepingResetDebt || !housekeepingSourceEmpty

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
