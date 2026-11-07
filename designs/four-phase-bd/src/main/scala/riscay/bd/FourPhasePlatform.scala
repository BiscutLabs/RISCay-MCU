// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._
import riscay.soc._

/** This variant owns clock, reset, wake and endpoint integration. */
abstract class FourPhasePlatform(p: SocParameters, board: SocParameters => BoardProfile,
    clockedCpuResponse: Boolean = true, owners: OwnerTiming = OwnerTiming(),
    preserveHierarchy: Boolean = false) extends SocTop(p) {
  val watchdog = withClockAndReset(watchdogClock, reset) { Module(new Watchdog(p.watchdogCycles, p.watchdogHoldCycles, preserveHierarchy)) }
  // Every pulse restarts the release history on the ungated service clock.
  // Eight edges hold at least 350 ns at the 20 MHz ceiling for observation.
  // This legacy digital pulse qualifier does not qualify physical reset settling.
  protected val applicationResetRequest = WireDefault(reset.asBool || watchdog.io.expired)
  val release = withClockAndReset(serviceClock, applicationResetRequest.asAsyncReset) {
    val n=ApplicationResetContract.qualifierEdges
    val stages = RegInit(((BigInt(1)<<n)-1).U(n.W)); stages := Cat(stages(n-2,0), false.B); stages
  }
  systemReset := applicationResetRequest || release.orR
  resetReason := watchdog.io.reason
  // Isolation/debt assert immediately. POR-only coordination consumes a
  // two-flop copy; both assertion and release cross before use as data.
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
  protected val fabric = withClockAndReset(workClock, reset) { Module(new FourPhaseServices(p, board, preserveHierarchy)) }
  // Synchronous cutoff precedes destructive native reset. These defaults apply
  // only to externally clocked verification clients; production binds ingress.
  protected val requestClosed=WireDefault(true.B)
  protected val requestRebased=WireDefault(true.B)
  protected val requestRebaseIdle=WireDefault(true.B)
  protected val resetBoundary=withClockAndReset(serviceClock,reset) { Module(new FourPhaseResetBoundary(ApplicationResetContract.nativeHoldEdges,ApplicationResetContract.nativeReleaseEdges, preserveHierarchy)) }
  resetBoundary.io.observed:=cpuResetActive
  protected val applicationCancel=WireDefault(resetBoundary.io.close)
  protected val nativeApplicationReset=WireDefault(resetBoundary.io.nativeReset)
  protected val nativeCoreReset=WireDefault(resetBoundary.io.coreReset)
  Seq(applicationResetRequest,applicationCancel,nativeApplicationReset,nativeCoreReset).foreach(dontTouch(_))
  protected val applicationIsolation=systemReset || applicationCancel
  contract.endpoint("application_reset_request",applicationResetRequest)
  contract.endpoint("application_cutoff",applicationCancel)
  contract.endpoint("native_application_reset",nativeApplicationReset)
  contract.endpoint("core_reset",nativeCoreReset)
  protected val applicationBridges=scala.collection.mutable.ArrayBuffer.empty[FourPhaseQuiescingBridge]
  protected def closeBridge(b: FourPhaseQuiescingBridge): Unit = {
    b.close:=applicationCancel; b.rebase:=resetBoundary.io.rebase; applicationBridges+=b
  }
  fabric.io.applicationCancel:=applicationCancel
  // Application presentation cancels with the CPU. The POR-owned effect owners
  // below continue their accepted work and suppress old-lifetime completions.
  protected val completion=asyncChild("completion")(d => new FourPhaseCompletion(d))
  val completionPlan=asyncChild("completion_plan_bridge")(d => new DecoupledToFourPhaseQuiescing(new CompletionPlan,d))
  val completionTelemetry=asyncChild("completion_telemetry_bridge")(d => new DecoupledToFourPhaseQuiescing(Bool(),d))
  val completionHousekeeping=asyncChild("completion_housekeeping_bridge")(d => new DecoupledToFourPhaseQuiescing(Bool(),d))
  completion.reset:=nativeApplicationReset.asAsyncReset
  Seq(completionPlan,completionTelemetry,completionHousekeeping).foreach(closeBridge)
  Seq(completionPlan,completionTelemetry,completionHousekeeping).foreach(_.clock:=workClock)
  Seq(completionPlan,completionTelemetry,completionHousekeeping).foreach { bridge =>
    dontTouch(bridge.in); dontTouch(bridge.out)
  }
  completionPlan.in <> fabric.io.completionPlan
  completionTelemetry.in <> fabric.io.completionTelemetry; completionHousekeeping.in <> fabric.io.completionHousekeeping
  chiselasync.protocol.FourPhase.connect(completion.plan,completionPlan.out)
  chiselasync.protocol.FourPhase.connect(completion.telemetry,completionTelemetry.out)
  chiselasync.protocol.FourPhase.connect(completion.housekeeping,completionHousekeeping.out)
  protected val admission=asyncChild("admission")(d => new FourPhaseAdmission(d))
  val admissionGrant=asyncChild("admission_grant_bridge")(d => new FourPhaseQuiescingToDecoupled(Bool(),d))
  admission.reset:=nativeApplicationReset.asAsyncReset
  closeBridge(admissionGrant)
  admissionGrant.clock:=workClock
  chiselasync.protocol.FourPhase.connect(admission.returned,completion.creditReturn)
  admission.responseIdle:= !completion.response.req && !completion.response.ack
  chiselasync.protocol.FourPhase.connect(admissionGrant.in,admission.grant)
  fabric.io.admissionGrant <> admissionGrant.out
  dontTouch(admissionGrant.in); dontTouch(admissionGrant.out)
  // Idle only confirms drainage. The native grant owns admission credit.
  withClockAndReset(workClock,reset) {
    val completionReturned = !completion.response.req && !completion.response.ack
    val completionReturnedFirst=RegNext(completionReturned,false.B)
    val second=RegNext(completionReturnedFirst,false.B)
    when(applicationCancel) { completionReturnedFirst:=false.B; second:=false.B }
    fabric.io.completionIdle:=second && !applicationCancel
  }
  if(clockedCpuResponse) {
    // Verification/service-bus clients have an actual clocked consumer.
    val bridge=asyncChild("completion_fixture_bridge")(d => new FourPhaseQuiescingToDecoupled(new MemoryResponse,d))
    closeBridge(bridge); bridge.clock:=workClock
    chiselasync.protocol.FourPhase.connect(bridge.in,completion.response)
    fabric.io.completionResponse <> bridge.out
  } else {
    // Production SoCs attach the native Fabric directly to completion.response.
    fabric.io.completionResponse.valid:=false.B
    fabric.io.completionResponse.bits:=0.U.asTypeOf(new MemoryResponse)
    fabric.io.response.ready:=false.B
  }

  val host = asyncChild("i2c")(d => new I2cTarget(p.i2cAddress,p.i2cIdleCycles,d,borrowFrames=true))
  host.clock := serviceClock; host.scl := scl; host.sda := sda
  host.frameAcceptEnable := fabric.io.clockRunning
  host.snapshotAcceptEnable := fabric.io.clockRunning && fabric.bankReadReady
  fabric.io.i2c <> host.host; sdaLow := host.pullLow
  val programAccess = asyncChild("program_access")(d => new ProgramAccess(d,log2Ceil(p.config.programBytes).max(2),p.config.programBytes))
  val programReturn = asyncChild("program_return")(d => new FourPhaseProgramReturn(d))
  val ramAccess = asyncChild("ram_access")(d => new RamAccess(d,log2Ceil(p.config.workingRamBytes).max(2),p.config.workingRamBytes))
  val ramReturn = asyncChild("ram_return")(d => new FourPhaseRamReturn(d))
  programAccess.clock := workClock; ramAccess.clock := workClock
  programAccess.io <> fabric.io.program; ramAccess.io <> fabric.io.ram
  // POR identity/effects survive application reset. CPU reply eligibility
  // follows coordinated native reset; service debt cancels uncommitted grants.
  val ramSource=asyncChild("ram_source")(d => new FourPhaseRamSource(d))
  val ramReserve=asyncChild("ram_reserve_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val ramGrant=asyncChild("ram_grant_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  val ramDecision=asyncChild("ram_decision_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  Seq(ramReserve,ramDecision).foreach { b =>
    b.clock:=workClock; dontTouch(b.in); dontTouch(b.out)
  }
  ramGrant.clock:=workClock; dontTouch(ramGrant.in); dontTouch(ramGrant.out)
  chiselasync.protocol.FourPhase.connect(ramSource.reserve,ramReserve.out)
  chiselasync.protocol.FourPhase.connect(ramGrant.in,ramSource.grant)
  chiselasync.protocol.FourPhase.connect(ramSource.decision,ramDecision.out)
  chiselasync.protocol.FourPhase.connect(ramSource.publication,ramReturn.publication)
  chiselasync.protocol.FourPhase.connect(ramReturn.word,ramAccess.word)
  ramAccess.captureRequest:=ramReturn.captureRequest
  ramReturn.captureAcknowledge:=ramAccess.captureAcknowledge
  ramAccess.returnIdle:=ramReturn.idle
  ramReturn.applicationReset:=nativeApplicationReset.asAsyncReset
  ramReturn.eligible:=ramSource.eligible
  completion.ram.req:=ramReturn.response.req; completion.ram.bits:=ramReturn.response.bits
  ramReturn.response.ack:=completion.ram.ack
  ramReserve.in <> fabric.io.ramSource.reserve; fabric.io.ramSource.grant <> ramGrant.out
  ramDecision.in <> fabric.io.ramSource.decision
  ramSource.applicationReset:=nativeApplicationReset.asAsyncReset
  // Effects and application presentation return before publication ACK. Owner
  // occupancy is deliberately excluded: publication must not wait for itself.
  ramSource.wordDrained:=ramAccess.effectsDrained && ramReturn.presentationSettled
  fabric.io.ramSource.eligible:=ramSource.eligible
  val ramOwnerIdle=withClockAndReset(workClock,reset) {
    val first=RegNext(ramSource.idle,false.B); RegNext(first,false.B)
  }
  val ramSourceEmpty=ramOwnerIdle && !ramAccess.io.busy && ramReserve.in.ready &&
    ramDecision.in.ready && !ramGrant.out.valid
  val ramServiceDebt=withClockAndReset(workClock,reset) {
    val debt=RegInit(true.B); val previousSafe=RegInit(false.B)
    previousSafe:=ramSourceEmpty && !applicationCancel
    when(applicationCancel) { debt:=true.B; previousSafe:=false.B }
      .elsewhen(previousSafe && ramSourceEmpty) { debt:=false.B }
    debt
  }
  fabric.io.ramSource.resetDebt:=ramServiceDebt
  fabric.io.ramSource.draining:=ramServiceDebt || !ramSourceEmpty
  // Persistent command/state loop and both crossings are POR-only. Application
  // reset is synchronized service data, never a reset of image/lock state.
  val programSource=asyncChild("program_source")(d => new FourPhaseProgramSource(d))
  val programReserve=asyncChild("program_reserve_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val programGrant=asyncChild("program_grant_bridge")(d => new chiselasync.clocked.FourPhaseToDecoupled(Bool(),2,d))
  val programDecision=asyncChild("program_decision_bridge")(d => new chiselasync.clocked.DecoupledToFourPhase(Bool(),2,d))
  val programStored=asyncChild("program_stored_bridge")(d => new FourPhaseStoredReceipt(d))
  Seq(programReserve,programDecision).foreach { b =>
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
  chiselasync.protocol.FourPhase.connect(programSource.publication,programReturn.publication)
  chiselasync.protocol.FourPhase.connect(programReturn.word,programAccess.word)
  programAccess.captureRequest:=programReturn.captureRequest
  programReturn.captureAcknowledge:=programAccess.captureAcknowledge
  programAccess.returnIdle:=programReturn.idle
  programReturn.applicationReset:=nativeApplicationReset.asAsyncReset
  programReturn.eligible:=programSource.cpuPresentationPermit
  completion.memory.req:=programReturn.response.req; completion.memory.bits:=programReturn.response.bits
  programReturn.response.ack:=completion.memory.ack
  programReserve.in <> fabric.io.programSource.reserve; fabric.io.programSource.grant <> programGrant.out
  programDecision.in <> fabric.io.programSource.decision
  programSource.applicationReset:=nativeApplicationReset.asAsyncReset
  // Capture/effects and CPU settlement cannot wait for publication or Stored return.
  programSource.wordDrained:=programAccess.effectsDrained && programReturn.presentationSettled
  fabric.io.programSource.eligible:=programSource.eligible
  val programOwnerIdle=withClockAndReset(workClock,reset) {
    val first=RegNext(programSource.idle,false.B); RegNext(first,false.B)
  }
  val programSourceEmpty=programOwnerIdle && !programAccess.io.busy && programReserve.in.ready &&
    programDecision.in.ready && !programGrant.out.valid && !programStored.out.valid
  val programServiceDebt=withClockAndReset(workClock,reset) {
    val debt=RegInit(true.B); val previousSafe=RegInit(false.B)
    previousSafe:=programSourceEmpty && !applicationCancel
    when(applicationCancel) { debt:=true.B; previousSafe:=false.B }
      .elsewhen(previousSafe && programSourceEmpty) { debt:=false.B }
    debt
  }
  fabric.io.programSource.resetDebt:=programServiceDebt
  fabric.io.programSource.draining:=programServiceDebt || !programSourceEmpty
  // Persistent command/state loop and both crossings are POR-only. Application
  // reset is synchronized service data, never a reset of image/lock state.
  val control = asyncChild("control")(d => new FourPhaseControl(p, d, owners))
  val controlCommandBridge = asyncChild("control_command_bridge")(d =>
    new chiselasync.clocked.DecoupledToFourPhase(new ControlCommandHeader, 2, d))
  val controlReplyBridge = asyncChild("control_reply_bridge")(d =>
    new FourPhaseServiceReplyReceipt(new ControlReply(p.config.programBytes), d))
  controlCommandBridge.clock := workClock; controlReplyBridge.clock := workClock
  // Borrow the immutable native bank; the periodic sender owns metadata only.
  // Its full settling cycle precedes request, and idle follows native capture
  // completion (including the complete BD return-to-zero).
  control.command.req := controlCommandBridge.out.req
  controlCommandBridge.out.ack := control.command.ack
  controlCommandBridge.out.bits.elements.foreach { case (name, field) =>
    control.command.bits.elements(name) := field
  }
  control.command.bits.frame := Mux(controlCommandBridge.out.bits.kind === ControlKind.Host.U,
    fabric.io.controlFrame, 0.U.asTypeOf(new HostFrame))
  host.frameCommandBank.get:=fabric.io.controlFrameBank
  host.frameCommandHost.get:=controlCommandBridge.out.bits.kind === ControlKind.Host.U
  host.frameCommandAck.get:=control.command.ack
  chiselasync.protocol.FourPhase.connect(controlReplyBridge.in, control.reply)
  controlCommandBridge.in.valid := fabric.io.controlCommand.valid
  fabric.io.controlCommand.ready := controlCommandBridge.in.ready
  controlCommandBridge.in.bits.elements.foreach { case (name, field) =>
    field := fabric.io.controlCommand.bits.elements(name)
  }
  fabric.io.controlCommandIdle := controlCommandBridge.in.ready
  fabric.io.controlReply <> controlReplyBridge.out
  // Preserve the complete held native reply ABI, including profile-unused fields.
  dontTouch(controlReplyBridge.out)
  val housekeeping=asyncChild("housekeeping")(d => new FourPhaseHousekeeping(p,d))
  val housekeepingCommandBridge=asyncChild("housekeeping_command_bridge")(d =>
    new chiselasync.clocked.DecoupledToFourPhase(Bool(), 2, d))
  val housekeepingReplyBridge=asyncChild("housekeeping_reply_bridge")(d =>
    new FourPhaseServiceReplyReceipt(new HousekeepingEffects, d))
  housekeepingCommandBridge.clock:=workClock; housekeepingReplyBridge.clock:=workClock
  housekeeping.command.req:=housekeepingCommandBridge.out.req
  housekeepingCommandBridge.out.ack:=housekeeping.command.ack
  housekeeping.command.bits:=fabric.io.housekeepingPayload
  housekeeping.command.bits.recovery:=housekeepingCommandBridge.out.bits
  chiselasync.protocol.FourPhase.connect(housekeepingReplyBridge.in,housekeeping.reply)
  housekeepingCommandBridge.in.valid:=fabric.housekeepingCommand.valid
  housekeepingCommandBridge.in.bits:=fabric.housekeepingCommand.bits.recovery
  fabric.housekeepingCommand.ready:=housekeepingCommandBridge.in.ready
  fabric.io.housekeepingCommandIdle:=housekeepingCommandBridge.in.ready
  fabric.housekeepingReply <> housekeepingReplyBridge.out
  dontTouch(housekeepingReplyBridge.out)
  fabric.housekeepingView:=housekeeping.view
  val housekeepingReturning=withClockAndReset(workClock,reset) {
    val pending=RegInit(false.B)
    when(housekeepingReplyBridge.out.fire) { pending:=true.B }
      .elsewhen(!housekeepingReplyBridge.in.ack) { pending:=false.B }
    pending
  }
  // This registered ACK falls only after guarded bank capture and the
  // synchronized reply return. Same-edge readers capture the previous bank.
  fabric.housekeepingBankReady:= !housekeepingReturning
  fabric.io.housekeepingDraining:= !housekeepingCommandBridge.in.ready ||
    (housekeepingReturning && housekeepingReplyBridge.in.ack)
  val telemetry = asyncChild("telemetry")(d => new FourPhaseTelemetry(p, fabric.telemetryWords, d,qualifyCommit=true))
  fabric.telemetryView := telemetry.view
  fabric.sampleView:=telemetry.sampleView
  val telemetryCommandBridge = asyncChild("telemetry_command_bridge")(d =>
    new chiselasync.clocked.DecoupledToFourPhase(new TelemetryCommandHeader(p.softwareSampleChannels.size), 2, d))
  val telemetryReplyBridge = asyncChild("telemetry_reply_bridge")(d =>
    new FourPhaseTelemetryReceipt(new TelemetryEffects, d))
  telemetry.command.req:=telemetryCommandBridge.out.req
  telemetryCommandBridge.out.ack:=telemetry.command.ack
  telemetryCommandBridge.out.bits.elements.foreach { case (name, field) =>
    telemetry.command.bits.elements(name):=field
  }
  fabric.io.telemetryCommitFields.elements.foreach { case (name, field) =>
    telemetry.command.bits.elements(name):=Mux(telemetryCommandBridge.out.bits.kind === TelemetryKind.Commit.U,
      field,0.U.asTypeOf(field))
  }
  telemetry.command.bits.sample.foreach(_ := Mux(telemetryCommandBridge.out.bits.kind === TelemetryKind.Commit.U,
    fabric.softwareCommit,0.U.asTypeOf(fabric.softwareCommit)))
  chiselasync.protocol.FourPhase.connect(telemetryReplyBridge.in, telemetry.reply)
  telemetryReplyBridge.applyBank:=fabric.telemetryApplyBank
  telemetry.commitAck.get:=telemetryReplyBridge.bankAck
  telemetryCommandBridge.clock := workClock; telemetryReplyBridge.clock := workClock
  telemetryCommandBridge.in.valid:=fabric.telemetryCommand.valid
  fabric.telemetryCommand.ready:=telemetryCommandBridge.in.ready
  telemetryCommandBridge.in.bits.elements.foreach { case (name, field) =>
    field:=fabric.telemetryCommand.bits.elements(name)
  }
  fabric.io.telemetryCommandIdle:=telemetryCommandBridge.in.ready
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
  fabric.telemetryBankReady:= !telemetryReturning
  fabric.io.telemetryDraining := !telemetryCommandBridge.in.ready ||
    (telemetryReturning && telemetryReplyBridge.in.ack)

  // Reserve/decision/publication all originate on this receiving work edge.
  // One POR slot owns that arbitration; only the real command/reply cross to
  // the native bank. Cancellation revokes presentation, never accepted effects.
  val telemetrySlot=withClockAndReset(workClock,reset) { Module(new FourPhasePublicationSlot) }
  telemetrySlot.io.client <> fabric.io.telemetrySource
  telemetrySlot.io.cancel:=applicationCancel
  telemetrySlot.io.commandAccepted:=telemetryCommandBridge.in.fire
  telemetrySlot.io.channelsReturned:=telemetryCommandBridge.in.ready &&
    !telemetryReplyBridge.in.ack && fabric.telemetryBankReady
  val housekeepingSlot=withClockAndReset(workClock,reset) { Module(new FourPhasePublicationSlot) }
  housekeepingSlot.io.client <> fabric.io.housekeepingSource
  housekeepingSlot.io.cancel:=applicationCancel
  housekeepingSlot.io.commandAccepted:=housekeepingCommandBridge.in.fire
  housekeepingSlot.io.channelsReturned:=housekeepingCommandBridge.in.ready &&
    !housekeepingReplyBridge.in.ack && fabric.housekeepingBankReady
  Seq(telemetrySlot,housekeepingSlot).foreach { slot =>
    dontTouch(slot.io.client); dontTouch(slot.io.cancel)
  }

  p.lowPower match {
    case Some(lp) =>
      val scaler = asyncChild("elapsed_scaler")(d => new ElapsedTicks(
        Seq(lp.tickMicros, lp.minimumTickMicros, lp.maximumTickMicros), d, owners.elapsedOwner, owners.elapsedStep))
      scaler.clock := workClock; scaler.io <> fabric.io.elapsedScaling
    case None =>
      fabric.io.elapsedScaling.publicationTarget := 0.U; fabric.io.elapsedScaling.consumed := 0.U; fabric.io.elapsedScaling.valid := false.B
      fabric.io.elapsedScaling.single := false.B; fabric.io.elapsedScaling.busy := false.B
      fabric.io.elapsedScaling.elapsed := 0.U.asTypeOf(fabric.io.elapsedScaling.elapsed)
      fabric.io.elapsedScaling.publicationElapsed := 0.U.asTypeOf(fabric.io.elapsedScaling.publicationElapsed)
  }
  val spiAdc=p.adc.map(a => asyncChild("spi_adc")(d => new SpiAdc(a,p.lowPower.isEmpty,d)))
  spiAdc match {
    case Some(adc) =>
      adc.clock:=workClock; adc.io <> fabric.io.adc; adc.miso:=adcMiso
      adcCsN:=adc.csN
      adcSclk := (if(p.spiBoot) Mux(fabric.io.spiClaimed, fabric.io.gpioOut(3) && fabric.io.gpioOe(3), adc.sclk) else adc.sclk)
    case None =>
      fabric.io.adc.busy:=false.B; fabric.io.adc.done:=false.B; fabric.io.adc.sample:=0.U.asTypeOf(fabric.io.adc.sample);fabric.io.adc.sampleReady:=true.B
      fabric.io.adc.result:=0.U.asTypeOf(fabric.io.adc.result)
      adcCsN:=true.B; adcSclk := (if(p.spiBoot) fabric.io.gpioOut(3) && fabric.io.gpioOe(3) else false.B)
  }
  resetBoundary.io.closed:=requestClosed && fabric.io.presentationClosed && applicationBridges.map(_.closed).reduce(_ && _)
  resetBoundary.io.rebased:=requestRebased && applicationBridges.map(_.rebased).reduce(_ && _)
  resetBoundary.io.rebaseIdle:=requestRebaseIdle && applicationBridges.map(b => !b.rebased).reduce(_ && _)
  fabric.io.cpuReset := applicationIsolation
  fabric.io.cpuResetActive := cpuResetActive
  fabric.io.crashCount := crashCount
  fabric.io.frontClock := serviceClock
  p.lowPower match {
    case Some(lp) =>
      val timebase = withClockAndReset(watchdogClock, reset) { Module(new SleepTimebase(lp, preserveHierarchy)) }
      val gate = withClockAndReset(serviceClock, reset) { Module(new RetainedClock) }
      gate.io.gray := timebase.io.gray; gate.io.consumedGray := fabric.io.consumedGray
      gate.io.canSleep := fabric.io.canSleep; gate.io.activity := fabric.io.activity
      gate.io.drainDemand := fabric.io.drainDemand
      gate.io.forceRun := resetBoundary.io.forceRun
      workClock := gate.io.clockOut; fabric.io.clockRunning := gate.io.running
      fabric.io.timeGray := gate.io.synchronizedGray
      sleepEntries := gate.io.entries; sleeping := !gate.io.running
      if(lp.stopServiceClock) {
        val wake = withClockAndReset(serviceClock, reset) { Module(new ServiceClockWake) }
        val mask = p.gpioEventMask.U(32.W)
        wake.io.event := timebase.io.gray =/= fabric.io.consumedGray || ((fabric.io.gpioIn ^ fabric.io.observedGpio) & mask).orR
        wake.io.scl := scl; wake.io.sda := sda
        wake.io.selected := fabric.io.hostSelected; wake.io.rejected := fabric.io.hostRejected
        wake.io.running := gate.io.running || applicationIsolation
        serviceClockEnable := wake.io.enable
      } else { serviceClockEnable := true.B }
    case None =>
      workClock := serviceClock; fabric.io.clockRunning := true.B
      fabric.io.timeGray := 0.U; sleepEntries := 0.U; sleeping := false.B
      serviceClockEnable := true.B
  }
  fabric.io.sleepEntries := sleepEntries
  fabric.io.gpioIn := (if(p.spiBoot) (gpioIn & "hffffffbf".U) | (adcMiso.asUInt << 6) else gpioIn); gpioOut := fabric.io.gpioOut; gpioOe := fabric.io.gpioOe
  fabric.io.watchdogReason := watchdogReasonActive; watchdog.io.heartbeat := fabric.io.heartbeat
  fabric.io.watchdogAck := watchdog.io.acknowledge
  mode := fabric.io.mode; programmed := fabric.io.programmed; locked := fabric.io.locked
  commit := fabric.io.commit
}
