// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._
import riscay.soc._

/** Temporary two-credit descriptor ledger. Wide payload and epoch live in native banks. */
private class ControlMailbox extends Module with InlineInstance {
  val io = IO(new Bundle {
    val enq = Flipped(Decoupled(new ControlDescriptor)); val deq = Decoupled(new ControlDescriptor)
    val count = Output(UInt(2.W))
  })
  val first = RegInit(0.U.asTypeOf(new ControlDescriptor))
  val second = RegInit(0.U.asTypeOf(new ControlDescriptor))
  val count = RegInit(0.U(2.W))
  io.count := count; io.enq.ready := count =/= 2.U; io.deq.valid := count =/= 0.U; io.deq.bits := first
  when(io.enq.fire && io.deq.fire) { first := io.enq.bits }
    .elsewhen(io.enq.fire) {
      when(count === 0.U) { first := io.enq.bits }.otherwise { second := io.enq.bits }
      count := count + 1.U
    }.elsewhen(io.deq.fire) { first := second; count := count - 1.U }
}

/** Clocked endpoints behind this variant's native asynchronous fabric. */
class FourPhaseServices(p: SocParameters, boardFactory: SocParameters => BoardProfile) extends ServiceEndpoint(p.config.programBytes) {
  val config = p.config
  val board = boardFactory(p)
  val telemetryWords = config.application.registers.map(_.word).toVector
  val telemetryCommand = IO(Decoupled(new TelemetryCommand(config.measurements.size)))
  val telemetryReply = IO(Flipped(Decoupled(new TelemetryReply(config.measurements.size, telemetryWords.size))))
  val program = Module(new SramBank(config.programBytes))
  val ram = Module(new SramBank(config.workingRamBytes))
  program.io.request <> io.program.bytes; io.program.completions <> program.io.response
  ram.io.request <> io.ram.bytes; io.ram.completions <> ram.io.response
  for(request <- Seq(io.program.request, io.ram.request)) {
    request.valid := false.B
    request.bits := 0.U.asTypeOf(new SramWordRequest)
  }
  // Native state owns decisions; this is a coherent clock-domain snapshot.
  val controlState = RegInit(ControlState.initial(p.config.programBytes))
  val controlOutstanding = RegInit(false.B)
  val loaderControlPending = RegInit(false.B)
  private val applicationResets=scala.collection.mutable.ArrayBuffer.empty[() => Unit]
  def applicationReg[T <: Data](init: T): T = {
    val value=RegInit(init); applicationResets+=(() => value:=init); value
  }
  val haltPending = applicationReg(false.B)
  val mmioCurrent = applicationReg(false.B)
  val mmioCommitPending = RegInit(false.B)
  val mmioCommit = Reg(new ControlCommand)
  val resetObserved = RegNext(io.cpuResetActive, true.B)
  val resetEdge = io.cpuResetActive && !resetObserved
  val resetNeeded = RegInit(true.B)
  val resetRecovery = RegInit(true.B)
  val resetPending = resetNeeded || resetEdge
  val loaderPending = WireDefault(controlState.loaderPending); dontTouch(loaderPending)
  val receivedWords = WireDefault(controlState.received >> 2); dontTouch(receivedWords)
  val loaderWrite = WireDefault(false.B)
  val controlBusy = Wire(Bool())
  val memoryBusy = io.program.busy || io.ram.busy || loaderPending
  val rom = VecInit(p.bootWords.map(_.U(32.W)))
  val telemetryOutstanding = RegInit(false.B)
  val telemetryRecoveryBlocked = io.telemetrySource.recoveryDebt || io.telemetrySource.returnFence
  val telemetryCommitPending = applicationReg(false.B)
  val telemetryCommit = Reg(new TelemetryCommand(config.measurements.size))
  io.telemetryCommitFields.elements.foreach { case (name, field) => field := telemetryCommit.elements(name) }
  val telemetryBarrier = telemetryOutstanding || telemetryRecoveryBlocked || telemetryCommitPending || !io.telemetryCommandIdle || io.telemetryDraining
  // Clocked completion of the existing native bank turn. Before receipt
  // acceptance the old bank is stable; afterward readers wait for completion.
  val telemetryBankReady=IO(Input(Bool()))
  val bankReadReady=IO(Output(Bool()))
  val telemetryWork = Wire(Bool())
  val telemetryAccepted = WireDefault(false.B)
  val telemetryElapsed = RegInit(0.U(32.W))
  val telemetryCaptures = RegInit(0.U.asTypeOf(Vec(config.measurements.size, new TelemetryCapture)))
  // Retain the complete registered boundary, including profile-constant flags.
  telemetryCaptures.foreach(dontTouch(_))
  val telemetryInFlight = RegInit(0.U.asTypeOf(new TelemetryCommand(config.measurements.size)))
  val hostSamples = RegInit(TelemetryState.initial(p, telemetryWords.size).samples.getOrElse(0.U.asTypeOf(Vec(0, new Sample))))
  def saturatingAdd(a: UInt, b: UInt): UInt = {
    val sum = a +& b; Mux(sum(32), "hffffffff".U(32.W), sum(31,0))
  }
  // Clock-domain status projection preserves the ABI's third-edge reset
  // observation even when the native reset command is backpressured.
  val mode = RegInit(0.U(3.W))
  val programmed = controlState.programmed; val locked = controlState.locked
  // Persistent native state consumes the synchronized reset command before
  // any further CPU command. Raw reset is reserved for output isolation.
  val started = applicationReg(false.B)
  val lastError = controlState.lastError
  val imageLength = controlState.imageLength; val entry = controlState.entry
  val received = controlState.received; val imageId = controlState.imageId
  io.mode := mode; io.programmed := programmed; io.locked := locked
  val canProgram = !locked && !started && !controlState.bootSession && !controlState.persistPending && !io.applicationCancel && !io.program.busy && !loaderPending && !controlBusy

  val housekeepingCommand = IO(Decoupled(new HousekeepingCommand))
  val housekeepingReply = IO(Flipped(Decoupled(new HousekeepingReply)))
  val housekeepingState = RegInit(HousekeepingState.initial(p))
  val housekeepingOutstanding = RegInit(false.B)
  val housekeepingInFlight = RegInit(0.U.asTypeOf(new HousekeepingCommand))
  val housekeepingBarrierBusy = Wire(Bool())
  // One retained bank serves ordered actions and background commands. Its
  // payload survives reply publication until the command sender fully returns.
  val housekeepingOrdered = Reg(new HousekeepingCommand)
  io.housekeepingPayload := housekeepingOrdered
  io.housekeepingPayload.recovery := false.B
  val housekeepingBankAvailable = !housekeepingOutstanding && io.housekeepingCommandIdle
  val housekeepingOrderedPending = RegInit(false.B)
  val housekeepingQueued = RegInit(0.U.asTypeOf(new HousekeepingCommand))
  val housekeepingRecoveryBlocked = io.housekeepingSource.recoveryDebt || io.housekeepingSource.returnFence
  val housekeepingWork = Wire(Bool())
  val housekeepingAction = WireDefault(0.U.asTypeOf(new HousekeepingCommand))
  val now = housekeepingState.now; io.now := now
  val wakeMask = Mux(housekeepingRecoveryBlocked,15.U,housekeepingState.wakeMask)
  val sleepRemaining = Mux(housekeepingRecoveryBlocked,0.U,housekeepingState.lease)
  val deadline = Mux(housekeepingRecoveryBlocked,0.U,housekeepingState.deadline)
  val parked = WireDefault(false.B)
  val heartbeat = RegInit(false.B); io.heartbeat := heartbeat
  val kickPending = applicationReg(false.B)
  val ack0 = RegNext(io.watchdogAck,false.B); val ack = RegNext(ack0,false.B)
  val spiClaimRequested = if(p.spiBoot) RegInit(true.B) else WireDefault(false.B)
  // This state belongs to the physical SPI boundary. Native transaction state
  // is not clocked here; the grant waits for its complete busy/return envelope.
  val spiClaimed = if(p.spiBoot) RegInit(true.B) else WireDefault(false.B)
  io.spiClaimed := spiClaimed
  if(p.spiBoot) {
    when(spiClaimRequested && !io.adc.busy) { spiClaimed := true.B }
    when(io.applicationCancel) { spiClaimRequested := true.B }
  }
  val adcLaunchPending = RegInit(false.B)
  io.elapsedScaling.target := Cat((0 until 32).reverse.map(i => io.timeGray(31,i).xorR))
  val rawElapsed = Wire(Vec(3,UInt(32.W)))
  val rawTimeValid = Wire(Bool()); val rawTarget = Wire(UInt(32.W)); val rawSingle = Wire(Bool())
  if(p.lowPower.nonEmpty) {
    rawElapsed := io.elapsedScaling.elapsed; rawTimeValid := io.elapsedScaling.valid
    rawTarget := io.elapsedScaling.publicationTarget; rawSingle := io.elapsedScaling.single
    io.consumedGray := housekeepingState.consumed ^ (housekeepingState.consumed >> 1)
  } else {
    val divider = RegInit(0.U(log2Ceil(p.serviceHz / 1000).max(1).W))
    val pulse = divider === (p.serviceHz / 1000 - 1).U
    divider := Mux(pulse,0.U,divider+1.U)
    rawElapsed.foreach(_ := Mux(pulse,1.U,0.U))
    rawTimeValid := pulse; rawTarget := 0.U; rawSingle := pulse; io.consumedGray := 0.U
  }
  // Measurement/GPIO observation ingress remains independent of housekeeping.
  // Final housekeeping publication alone acknowledges LF work via consumedGray.
  val housekeepingPublished = housekeepingReply.fire
  val kick=housekeepingPublished && housekeepingReply.bits.kick &&
    (!housekeepingRecoveryBlocked || housekeepingReply.bits.resetApplication)
  // ENTER_LOADER deliberately expires the existing independent watchdog.
  // Once its reset retires the old application, ROM/idle-loader kicks resume.
  // No new reset-domain crossing or request-derived clock is introduced.
  when((kick || kickPending) && !(controlState.loaderHold && controlState.started)) {
    when(ack === heartbeat) { heartbeat:= !heartbeat; kickPending:=false.B }
      .otherwise { kickPending:=true.B }
  }
  val elapsed = rawElapsed(0); val upperElapsed = rawElapsed(2)
  val tick = elapsed =/= 0.U
  val leaseExpired = housekeepingPublished && !housekeepingRecoveryBlocked && housekeepingReply.bits.leaseExpired
  val scalingBusy = io.elapsedScaling.busy || housekeepingWork || rawTimeValid
  val gpio = withClock(io.frontClock) {
    val first = RegNext(io.gpioIn, 0.U); RegNext(first, 0.U)
  }
  io.observedGpio := gpio
  val gpioPrevious = RegNext(gpio, 0.U)
  val telemetryView=IO(Input(new TelemetryRegisters(config.gpioCount,telemetryWords.size)))
  val output=telemetryView.output.pad(32);val enable=telemetryView.enable.pad(32)
  val gpioMask = ((BigInt(1) << config.gpioCount) - 1).U(32.W)
  val application=telemetryWords.zip(telemetryView.application.toSeq.flatMap(_.toSeq)).toMap
  val appIndex = controlState.appIndex
  def applicationWord(word: UInt): UInt = MuxLookup(word, "hffffffff".U(32.W))(
    config.application.registers.map(r => r.word.U ->
      Mux(io.applicationCancel || telemetryRecoveryBlocked,0.U,application(r.word))))
  def applicationExists(word: UInt): Bool = config.application.registers.map(r => word === r.word.U).foldLeft(false.B)(_ || _)

  // Native telemetry receives the retained acquisition stream.
  val publish = Wire(Vec(config.measurements.size, Valid(new Acquisition)))
  publish.foreach { x => x.valid := false.B; x.bits := 0.U.asTypeOf(new Acquisition) }
  val sampleIndex = controlState.sampleIndex; val sampleValue = controlState.sampleValue
  val periodUpdate = Wire(Valid(UInt(32.W))); periodUpdate.valid := false.B; periodUpdate.bits := 0.U
  val samplePeriod = housekeepingState.period
  val periodPending = housekeepingState.periodPending ||
    (housekeepingOrderedPending && housekeepingOrdered.periodUpdate) || housekeepingInFlight.periodUpdate
  val adcBusy = WireDefault(false.B)
  def validPeriod(value: UInt): Bool = (p.lowPower.nonEmpty && p.adc.nonEmpty).B &&
    value >= p.minimumSampleMs.U && value <= p.maximumSampleMs.max(0).U
  val publishAge=Wire(Vec(config.measurements.size,UInt(32.W))); publishAge.foreach(_ := 0.U)
  io.adc.start := false.B; io.adc.ageStep := Mux(tick,upperElapsed,0.U)
  p.adc.foreach { adcParameters =>
    adcBusy := io.adc.busy
    if(p.lowPower.nonEmpty) {
      io.adc.start := adcLaunchPending && !io.adc.busy && !spiClaimRequested
      when(io.adc.start) { adcLaunchPending := false.B }
      adcBusy := io.adc.busy || (!spiClaimRequested && (adcLaunchPending || housekeepingState.requested || periodPending))
    }
    publish(0) := io.adc.result; publishAge(0) := io.adc.age
  }
  // Generic GPIO reset policy; profile pin descriptors never drive hardware.
  // Pads are continuous: keep isolation through native capture and full return,
  // not just the receipt edge which authorizes the bank write.
  val gpioRecovery = io.applicationCancel || telemetryRecoveryBlocked
  val recoveryMask = Mux(gpioRecovery,
    (if(!p.retainGpioOnWatchdog) 0.U(32.W) else if(p.spiBoot) "hffffffc7".U else "hffffffff".U),"hffffffff".U)
  val gpioOutputView = output & gpioMask & recoveryMask
  val gpioEnableView = enable & gpioMask & recoveryMask
  io.gpioOut := (if(p.retainGpioOnWatchdog) Mux(io.cpuReset, gpioOutputView & (if(p.spiBoot) "hffffffc7".U else "hffffffff".U), gpioOutputView) else Mux(io.cpuReset, 0.U, gpioOutputView))
  io.gpioOe := (if(p.retainGpioOnWatchdog) Mux(io.cpuReset, gpioEnableView & (if(p.spiBoot) "hffffffc7".U else "hffffffff".U), gpioEnableView) else Mux(io.cpuReset, 0.U, gpioEnableView))

  // The work edge arbitrates independent producers against MMIO arrival.
  // This is the sole event bank: no native projection or event transaction.
  val eventPending = applicationReg(0.U(6.W))
  val pendingView = eventPending
  // Diagnostic application observation follows immediate isolation. The actual
  // MMIO/host ABI and WAIT use pendingView and synchronous cancellation; raw
  // reset must never enter their data/enable cones.
  val pending = Mux(io.cpuReset, 0.U(6.W), pendingView)
  val clear = WireDefault(0.U(6.W))
  val replaceDeadline = WireDefault(false.B)
  val hostWake = WireDefault(false.B)
  val due = housekeepingPublished && !housekeepingRecoveryBlocked && !replaceDeadline && housekeepingReply.bits.due
  val acquisition = if(config.measurements.isEmpty) false.B else publish.map(_.valid).reduce(_ || _)
  val gpioActivity = ((gpio ^ gpioPrevious) & p.gpioEventMask.U(32.W)).orR
  val events = WireDefault(Cat(hostWake, leaseExpired, acquisition, gpioActivity, due, tick))
  // Native validation adds a handshake window before the peripheral commit.
  // Preserve every event raised during that window against a software clear.
  val mmioEvents = applicationReg(0.U(6.W))
  // The request may already be waiting while a previous completion drains.
  // Events since its arrival must survive a later clear, not only events since
  // Control dispatch. Otherwise extra return latency loses a coincident GPIO.
  val mmioObserved = applicationReg(false.B)
  val observingMmio = io.request.valid && io.request.bits.address >= MemoryMap.mmio.U &&
    io.request.bits.address < (MemoryMap.mmio + MemoryMap.mmioBytes).U && io.request.bits.operation =/= Operation.Halt.U
  when(observingMmio) {
    mmioEvents := Mux(mmioObserved,mmioEvents,0.U) | events
    mmioObserved := true.B
  }
  when(!io.request.valid || io.request.fire) { mmioObserved := false.B }

  // Replacement consumes only the old deadline, including an expiry on this
  // edge. Other new events still win acknowledgement races.
  val acceptedClear = (clear | Mux(replaceDeadline, 2.U, 0.U))(5,0)
  eventPending := (eventPending & ~acceptedClear) | events

  // Native credit gates admission at the original commit edge. Keep the held
  // request visible above while waiting, including its MMIO event-clear window.
  io.admissionGrant.ready := io.request.fire
  val response = WireDefault(0.U.asTypeOf(new MemoryResponse))
  val waitMemory = WireDefault(false.B)
  val waitRam = WireDefault(false.B)
  io.response <> io.completionResponse
  io.completionPlan.valid := io.request.fire && io.request.bits.operation =/= Operation.Halt.U
  io.completionPlan.bits.response := response
  io.completionPlan.bits.memory := waitMemory
  io.completionPlan.bits.ram := waitRam
  io.completionPlan.bits.telemetry := telemetryAccepted
  io.completionPlan.bits.housekeeping := housekeepingAction.cpuCompletion
  io.completionTelemetry.valid := false.B; io.completionTelemetry.bits := true.B
  io.completionHousekeeping.valid := false.B; io.completionHousekeeping.bits := true.B
  val completionAvailable = io.completionIdle && io.completionPlan.ready &&
    io.completionTelemetry.ready && io.completionHousekeeping.ready
  val req = io.request.bits
  val isRead = req.operation === Operation.Read.U
  val isWrite = req.operation === Operation.Write.U
  val isFetch = req.operation === Operation.Fetch.U
  // Offer the full payload independently of valid. Range/permission/admission
  // checks below alone authorize capture; invalid-cycle bits are don't-care.
  // This also preserves the declared 32-bit address path at the crossing.
  io.ram.request.bits.address := req.address - MemoryMap.ram.U
  io.ram.request.bits.write := isWrite
  io.ram.request.bits.data := req.data; io.ram.request.bits.mask := req.mask
  val fullWord = req.address(1,0) === 0.U && req.mask === 15.U
  val ramOperation = req.address >= MemoryMap.ram.U &&
    req.address < (MemoryMap.ram + config.workingRamBytes).U && (isRead || isWrite)
  io.ramSource.reserve.valid := io.request.valid && ramOperation && !io.applicationCancel &&
    !resetRecovery && !io.ramSource.resetDebt
  io.ramSource.reserve.bits := isWrite
  val ramCommit = io.request.fire && ramOperation
  io.ramSource.grant.ready := io.ramSource.decision.ready && (ramCommit || io.ramSource.resetDebt)
  io.ramSource.decision.valid := io.ramSource.grant.fire
  io.ramSource.decision.bits := ramCommit
  when(ramCommit) {
    assert(io.ramSource.grant.fire && io.ramSource.decision.fire && io.ram.request.fire,
      "RAM_SOURCE_COMMIT_NOT_ATOMIC")
    assert(io.ramSource.eligible && io.ramSource.grant.bits === isWrite,"RAM_SOURCE_GRANT_IDENTITY")
  }
  assert(io.ram.request.fire === ramCommit,"RAM_SOURCE_UNRESERVED_WORD")
  when(io.ramSource.decision.fire && !io.ramSource.decision.bits) {
    assert(io.ramSource.resetDebt && !io.ram.request.fire && !ramCommit,"RAM_SOURCE_CANCELLED_EFFECT")
  }
  // A source reservation precedes acceptance, but does not block higher-priority
  // host work. A late Control winner cancels an uncommitted CPU slot; the next
  // attempt rechecks image permissions. Accepted loader obligations bypass all
  // CPU reset/recovery gates and retain their independent Stored receipt.
  val programCpuOperation = req.address >= MemoryMap.program.U &&
    req.address < (MemoryMap.program + config.programBytes).U && (isRead || isFetch) &&
    programmed && (req.address - MemoryMap.program.U) < imageLength
  val loaderOffer = controlOutstanding && io.controlReply.valid && io.controlReply.bits.programWrite
  io.programSource.reserve.valid := loaderOffer || (io.request.valid && programCpuOperation &&
    !controlBusy && !io.applicationCancel && !resetRecovery && !io.programSource.resetDebt)
  io.programSource.reserve.bits := loaderOffer
  val programCpuCommit = io.request.fire && programCpuOperation
  val programLoaderCommit = io.controlReply.fire && io.controlReply.bits.programWrite
  val programCancel = !io.programSource.grant.bits &&
    (io.programSource.resetDebt || io.applicationCancel || resetRecovery || controlBusy ||
      !io.request.valid || !programCpuOperation)
  io.programSource.grant.ready := io.programSource.decision.ready &&
    (programCpuCommit || programLoaderCommit || programCancel)
  io.programSource.decision.valid := io.programSource.grant.fire
  io.programSource.decision.bits := programCpuCommit || programLoaderCommit
  val programLoaderReady = io.programSource.grant.valid && io.programSource.grant.bits &&
    io.programSource.decision.ready && io.program.request.ready
  io.programSource.stored.ready := io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Stored.U
  when(programCpuCommit || programLoaderCommit) {
    assert(io.programSource.grant.fire && io.programSource.decision.fire && io.program.request.fire,
      "PROGRAM_SOURCE_COMMIT_NOT_ATOMIC")
    assert(io.programSource.grant.bits === programLoaderCommit &&
      io.programSource.ownerLoader === programLoaderCommit,"PROGRAM_SOURCE_GRANT_IDENTITY")
    assert(!programCpuCommit || io.programSource.eligible,"PROGRAM_SOURCE_CPU_NOT_ELIGIBLE")
  }
  assert(io.program.request.fire === (programCpuCommit || programLoaderCommit),"PROGRAM_SOURCE_UNRESERVED_WORD")
  when(io.programSource.decision.fire && !io.programSource.decision.bits) {
    assert(!io.programSource.grant.bits && !io.program.request.fire,"PROGRAM_SOURCE_CANCELLED_EFFECT")
  }
  val bootWait = isRead && fullWord && !started &&
    (req.address === MemoryMap.mmio.U ||
      (req.address === (MemoryMap.mmio+80).U && !controlState.persistPending))
  val waitingRead = isRead && fullWord && req.address === (MemoryMap.mmio + 16).U
  val eventWait = waitingRead && (pendingView & (wakeMask | "h30".U)) === 0.U
  parked := io.request.valid && (eventWait || bootWait)
  val parkedForSleep = p.lowPower.nonEmpty.B && io.request.valid &&
    (bootWait || (eventWait && sleepRemaining =/= 0.U)) && io.admissionGrant.valid && !adcBusy && !memoryBusy && !controlBusy
  io.canSleep := parkedForSleep && !io.programSource.draining && !io.ramSource.draining && !scalingBusy && !tick && !telemetryWork
  if(p.spiBoot) {
    when(io.request.fire && isWrite && req.address === (MemoryMap.mmio+88).U &&
        !io.controlReply.bits.memory.error) {
      spiClaimRequested := req.data(0)
      when(!req.data(0)) { spiClaimed := false.B }
    }
  }
  val nativeMmio = req.address >= MemoryMap.mmio.U && req.address < (MemoryMap.mmio + MemoryMap.mmioBytes).U &&
    req.operation =/= Operation.Halt.U
  val mmioComplete = io.controlReply.fire && io.controlReply.bits.kind === ControlKind.Mmio.U && mmioCurrent
  val cpuAvailable = completionAvailable && !io.applicationCancel && !resetRecovery && io.clockRunning && io.admissionGrant.valid && !bootWait && !eventWait &&
    !memoryBusy && !loaderWrite && !telemetryBarrier && telemetryBankReady && !housekeepingBarrierBusy &&
    !telemetryRecoveryBlocked && !housekeepingRecoveryBlocked
  // Reserve from a validated, held Control reply. An unused parked WAIT owns
  // no source. Engine readiness excludes these reservations, avoiding self-wait.
  val currentMmio=controlOutstanding && mmioCurrent && io.controlReply.valid &&
    io.controlReply.bits.kind === ControlKind.Mmio.U && io.request.valid && nativeMmio
  val successfulWrite=isWrite && !io.controlReply.bits.memory.error
  val telemetryRequired=successfulWrite &&
    Seq(24,28,44,52).map(x => req.address(6,0) === x.U).reduce(_ || _)
  val housekeepingWriteRequired=successfulWrite &&
    Seq(8,32,56,60,64).map(x => req.address(6,0) === x.U).reduce(_ || _)
  val housekeepingRequired=waitingRead || housekeepingWriteRequired
  val publicationAdmission=(!telemetryRequired ||
    (io.telemetrySource.grant.valid && !io.telemetrySource.grant.bits.recovery && io.telemetrySource.decision.ready)) &&
    (!housekeepingRequired || (io.housekeepingSource.grant.valid && !io.housekeepingSource.grant.bits.recovery && io.housekeepingSource.decision.ready))
  val telemetryRecoveryCommit=WireDefault(false.B)
  val housekeepingRecoveryCommit=WireDefault(false.B)
  for((source,required,recoveryCommit) <- Seq(
      (io.telemetrySource,telemetryRequired,telemetryRecoveryCommit),
      (io.housekeepingSource,housekeepingRequired,housekeepingRecoveryCommit))) {
    // Recovery ignores its own debt/fence, but first waits for every older
    // accepted effect and crossing. Queued observations do not enter quiet.
    source.reserve.valid:=Mux(source.recoveryDebt,
      source.quiet && !source.occupied && !io.applicationCancel,
      currentMmio && required && cpuAvailable)
    source.reserve.bits.recovery:=source.recoveryDebt
    source.reserve.bits.tag:=Mux(source.recoveryDebt,false.B,req.data(0))
    val cpuCommitted=io.request.fire && nativeMmio && required
    val committed=cpuCommitted || recoveryCommit
    val cancelCpu=source.returnFence || source.recoveryDebt || io.applicationCancel || !currentMmio || !required
    val cancelRecovery= !source.eligible || io.applicationCancel || !source.recoveryDebt
    source.grant.ready:=source.decision.ready &&
      (committed || Mux(source.grant.bits.recovery,cancelRecovery,cancelCpu))
    source.decision.valid:=source.grant.fire; source.decision.bits:=committed
    source.drain.ready:=source.quiet
    when(committed) {
      assert(source.grant.fire && source.decision.fire && source.eligible,
        "PUBLICATION_SOURCE_COMMIT_NOT_ATOMIC")
      assert(source.grant.bits.recovery === recoveryCommit && source.ownerRecovery === recoveryCommit,
        "PUBLICATION_SOURCE_ROLE_IDENTITY")
      assert(source.grant.bits.tag === Mux(recoveryCommit,false.B,req.data(0)),
        "PUBLICATION_SOURCE_GRANT_IDENTITY")
    }
    when(source.decision.fire && !source.decision.bits) {
      assert(!committed,"PUBLICATION_SOURCE_CANCELLED_EFFECT")
    }
  }
  val ramAdmission = io.ramSource.grant.valid && io.ramSource.decision.ready &&
    !io.ramSource.resetDebt && io.ram.request.ready
  val programAdmission = io.programSource.grant.valid && !io.programSource.grant.bits &&
    io.programSource.decision.ready && !io.programSource.resetDebt && io.program.request.ready
  io.request.ready := cpuAvailable && Mux(nativeMmio, mmioComplete, !controlBusy) &&
    (!ramOperation || ramAdmission) && (!programCpuOperation || programAdmission)

  io.commit.valid := io.request.fire; io.commit.bits := req
  when(io.request.fire) {
    when(waitingRead) { housekeepingAction.waitAccepted := true.B }
    when(nativeMmio && housekeepingWriteRequired && req.address(6,0) =/= 64.U) { housekeepingAction.write := true.B }
    response.data := 0.U; response.error := true.B
    when(req.operation === Operation.Halt.U) { haltPending := true.B }
      .elsewhen(req.address < (p.bootWords.size * 4).U && !isWrite) {
        response.data := rom(req.address(log2Ceil(p.bootWords.size).max(1)+1, 2)); response.error := false.B
      }.elsewhen(req.address >= MemoryMap.program.U && req.address < (MemoryMap.program + config.programBytes).U) {
        when(programCpuOperation) {
          io.program.request.valid := true.B
          io.program.request.bits.address := req.address - MemoryMap.program.U
          waitMemory := true.B
        }
      }.elsewhen(ramOperation) {
        io.ram.request.valid := true.B
        waitRam := true.B
      }.elsewhen(!isFetch && req.address >= MemoryMap.mmio.U && req.address < (MemoryMap.mmio + MemoryMap.mmioBytes).U && fullWord) {
        val offset = req.address(6, 0)
        response := io.controlReply.bits.memory
        when(isWrite && !io.controlReply.bits.memory.error) {
          switch(offset) {
            is(8.U) { replaceDeadline := true.B; response.error := false.B }
            is(12.U) { clear := req.data(5,0) & ~Mux(mmioObserved, mmioEvents, 0.U(6.W)); response.error := false.B }
            is(24.U) { response.error := false.B }
            is(28.U) { response.error := false.B }
            is(32.U) { when(req.data === "h57444f47".U) { response.error := false.B } }
            is(36.U) { when(req.data < config.measurements.size.U) { response.error := false.B } }
            is(40.U) { response.error := false.B }
            is(44.U) {
              for(i <- config.measurements.indices if !(i == 0 && p.adc.nonEmpty)) {
                when(sampleIndex === i.U) {
                  publish(i).valid := true.B; publish(i).bits.value := sampleValue
                  publish(i).bits.valid := req.data(0); publish(i).bits.calibrated := req.data(1)
                  response.error := false.B
                }
              }
            }
            is(48.U) { when(applicationExists(req.data)) { response.error := false.B } }
            is(52.U) { for((word, value) <- application.toSeq.sortBy(_._1)) {
              when(appIndex === word.U) { response.error := false.B }
            } }
            is(56.U) { when((req.data & "hffffffc0".U) === 0.U) { response.error := false.B } }
            is(60.U) {
              when(p.lowPower.nonEmpty.B && req.data <= p.lowPower.map(_.maximumSleepMs).getOrElse(0).U) {
                response.error := false.B
              }
            }
            is(64.U) { when(validPeriod(req.data)) { periodUpdate.valid := true.B; periodUpdate.bits := req.data; response.error := false.B } }
          }
        }
      }
  }

  io.activity := io.programSource.draining || io.ramSource.draining || scalingBusy || io.i2c.busy || gpioActivity || memoryBusy || controlBusy || telemetryWork
  // The normal seven-edge guard may drain while native maintenance is busy;
  // canSleep/activity still keep the gate open until that work actually drains.
  io.drainDemand := !parkedForSleep || io.i2c.busy || gpioActivity
  io.hostSelected := io.i2c.selected; io.hostRejected := io.i2c.rejected
  val selector = controlState.selector
  private val hostFrames = Module(new ControlMailbox)
  io.i2c.resetActive := io.applicationCancel
  io.i2c.programBusy := io.program.busy || loaderPending || loaderControlPending ||
    (io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Host.U &&
      io.controlCommand.bits.frame.bytes(0) >= 1.U && io.controlCommand.bits.frame.bytes(0) <= 6.U)
  io.hostFrameAccepted := hostFrames.io.enq.fire
  hostFrames.io.enq.valid := io.i2c.frame.valid; hostFrames.io.enq.bits.bank := io.i2c.frameSlot
  hostFrames.io.enq.bits.resetActive := io.applicationCancel || io.i2c.frame.bits.resetActive
  hostFrames.io.enq.bits.programBusy := io.i2c.frame.bits.programBusy || io.program.busy || loaderPending || loaderControlPending ||
    (io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Host.U &&
      io.controlCommand.bits.frame.bytes(0) >= 1.U && io.controlCommand.bits.frame.bytes(0) <= 6.U)
  assert(!io.i2c.frame.valid || hostFrames.io.enq.ready, "CONTROL_HOST_MAILBOX_OVERFLOW")
  // Preserve the original source epoch until D. A complete watchdog episode
  // invalidates precisely older queued frames; a new explicit START stays fresh.
  private val hostHead=io.i2c.heads(hostFrames.io.deq.bits.bank)
  // D frees the descriptor; R clears its tag after sender synchronization.
  // The head accepts at D. A native C-join retains the bank through both
  // actual returns, which can finish before R or trail it independently.
  val hostRetiring = RegInit(false.B)
  val hostRetiringBank = RegInit(0.U(2.W))
  private val retiringHead = io.i2c.heads(hostRetiringBank)
  io.controlFrame := retiringHead.bits.ingress.frame
  io.controlFrameBank := hostRetiringBank
  val hostRetire = hostRetiring && io.controlCommandIdle && io.clockRunning
  private val hostHeadValid=hostFrames.io.deq.valid && hostHead.valid && (!hostRetiring || hostRetire)
  for(i <- 0 until 4) {
    io.i2c.heads(i).ready:=io.clockRunning && hostFrames.io.deq.ready &&
      hostFrames.io.deq.valid && hostFrames.io.deq.bits.bank === i.U
  }
  when(hostRetire) { hostRetiring := false.B }
  when(hostFrames.io.deq.fire) {
    hostRetiring := true.B
    hostRetiringBank := hostFrames.io.deq.bits.bank
  }
  // Reserve a bounded CPU admission turn before starting more background work.
  // A stalled Control computation still permits independent timer maintenance.
  val cpuTimingTurn=io.request.valid && nativeMmio && !bootWait && !eventWait && !io.applicationCancel &&
    (!controlOutstanding || (mmioCurrent && io.controlReply.valid))
  // Bounded host/CPU turns; a continuous host cannot starve ROM progress.
  val cpuTurn = RegInit(true.B)
  // A queued host descriptor owns an already offered turn until dispatch;
  // a CPU arriving later cannot steal it while the native head is stalled.
  when(io.request.fire || ((hostFrames.io.deq.valid || hostFrames.io.enq.fire) && !io.request.valid)) { cpuTurn := false.B }
  when(io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Host.U) { cpuTurn := true.B }
  // Stack accesses need a bounded ROM turn too; a held program reservation
  // must still yield to loader invalidation before its commit decision.
  val cpuAdmissionTurn = cpuTurn && io.request.valid && (nativeMmio || ramOperation) && !bootWait && !eventWait
  val hostTurn = hostHeadValid && !cpuAdmissionTurn
  val mmioLaunch = io.request.valid && nativeMmio && cpuAvailable && (!hostFrames.io.deq.valid || cpuTurn)
  controlBusy := controlOutstanding || hostRetiring || io.programSource.stored.valid || mmioCommitPending || resetPending || haltPending || (hostFrames.io.deq.valid && !cpuAdmissionTurn)
  io.controlCommand.valid := !controlOutstanding &&
    (io.programSource.stored.valid || mmioCommitPending || resetPending || (haltPending && !io.applicationCancel) || hostTurn || mmioLaunch)
  io.controlCommand.bits := 0.U.asTypeOf(new ControlCommand)
  io.controlCommand.bits.kind := Mux(io.programSource.stored.valid, ControlKind.Stored.U,
    Mux(mmioCommitPending, ControlKind.MmioCommit.U, Mux(resetPending, ControlKind.ResetApplication.U,
      Mux(haltPending && !io.applicationCancel, ControlKind.Halt.U, Mux(hostTurn, ControlKind.Host.U, ControlKind.Mmio.U)))))
  io.controlCommand.bits.frame := Mux(hostFrames.io.deq.valid, hostHead.bits.ingress.frame, 0.U.asTypeOf(new HostFrame))
  io.controlCommand.bits.cpuResetActive := io.applicationCancel ||
    (hostTurn && (hostFrames.io.deq.bits.resetActive || hostHead.bits.resetEpoch =/= io.i2c.currentEpoch))
  io.controlCommand.bits.programBusy := io.program.busy ||
    (hostTurn && hostFrames.io.deq.bits.programBusy)
  io.controlCommand.bits.memory := req
  io.controlCommand.bits.applicationWritable := application.keys.toSeq.map(i => appIndex === i.U).foldLeft(false.B)(_ || _)
  val peripheralRead = MuxLookup(req.address(6,0), 0.U(32.W))(Seq(
    4.U -> now, 8.U -> deadline, 12.U -> pendingView, 16.U -> pendingView,
    20.U -> (gpio & gpioMask), 24.U -> gpioOutputView, 28.U -> gpioEnableView,
    52.U -> applicationWord(appIndex), 56.U -> wakeMask, 60.U -> sleepRemaining,
    64.U -> samplePeriod, 68.U -> Cat(0.U(28.W), periodPending, sleepRemaining =/= 0.U, !io.clockRunning, p.lowPower.nonEmpty.B),
    72.U -> io.sleepEntries,
    88.U -> Cat(0.U(29.W), output(5) && enable(5) && !output(3), io.adc.busy, spiClaimed),
    92.U -> (MemoryMap.ram + config.workingRamBytes).U(32.W)))
  // Native view is retained while CPU admission excludes Telemetry work.
  // Never capture its changing invalid bus in an unrelated host/reset command.
  io.controlCommand.bits.peripheralData:=Mux(io.controlCommand.bits.kind === ControlKind.Mmio.U &&
    !telemetryBarrier && telemetryBankReady && !io.applicationCancel,peripheralRead,0.U)
  when(mmioCommitPending && !io.programSource.stored.valid) {
    io.controlCommand.bits := mmioCommit
  }
  when(io.request.fire && nativeMmio && isWrite && !io.controlReply.bits.memory.error) {
    // Native preparation is reversible. The clocked endpoint accepts the write
    // here; its private commit token survives watchdog reset and precedes reset.
    mmioCommitPending := true.B
    mmioCommit := 0.U.asTypeOf(new ControlCommand)
    mmioCommit.kind := ControlKind.MmioCommit.U; mmioCommit.memory := req
    mmioCommit.applicationWritable := io.controlCommand.bits.applicationWritable
  }
  hostFrames.io.deq.ready := io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Host.U
  when(io.controlCommand.fire) {
    controlOutstanding := true.B
    loaderControlPending := io.controlCommand.bits.kind === ControlKind.Host.U &&
      io.controlCommand.bits.frame.bytes(0) >= 1.U && io.controlCommand.bits.frame.bytes(0) <= 6.U
    switch(io.controlCommand.bits.kind) {
      is(ControlKind.ResetApplication.U) { resetNeeded := false.B }
      is(ControlKind.MmioCommit.U) { mmioCommitPending := false.B }
      is(ControlKind.Mmio.U) { mmioCurrent := true.B }
      is(ControlKind.Halt.U) { haltPending := false.B }
    }
  }
  // A reply belongs to the single outstanding command, including reset recovery.
  io.controlReply.ready := controlOutstanding &&
    (io.controlReply.bits.kind =/= ControlKind.Mmio.U || !mmioCurrent ||
      (!telemetryBarrier && telemetryBankReady && !housekeepingBarrierBusy && completionAvailable && !io.applicationCancel &&
        !resetRecovery && io.clockRunning && io.admissionGrant.valid && !bootWait && !eventWait &&
        !memoryBusy && !telemetryRecoveryBlocked && !housekeepingRecoveryBlocked && publicationAdmission)) &&
    (!io.controlReply.bits.periodUpdate || (!housekeepingOrderedPending && housekeepingBankAvailable)) &&
    (!io.controlReply.bits.programWrite || programLoaderReady)
  when(io.controlReply.fire && io.controlReply.bits.kind === ControlKind.Mmio.U && mmioCurrent) {
    assert(io.request.fire,"MMIO_REPLY_WITHOUT_REQUEST_ACCEPTANCE")
  }
  when(io.controlReply.fire) {
    val result = io.controlReply.bits
    controlOutstanding := false.B; loaderControlPending := false.B; controlState := result.state
    mode := Mux((io.applicationCancel || resetRecovery) && (result.state.mode === 3.U || result.state.mode === 4.U),
      Mux(result.state.programmed, 2.U, 0.U), result.state.mode)
    started := result.state.started && !io.applicationCancel && !resetRecovery
    when(result.kind === ControlKind.Mmio.U) { mmioCurrent := false.B }
    when(result.kind === ControlKind.ResetApplication.U && !resetPending) { resetRecovery := false.B }
    when(result.periodUpdate) { periodUpdate.valid := true.B; periodUpdate.bits := result.period }
    when(result.hostWake) { hostWake := true.B }
    when(result.programWrite) {
      loaderWrite := true.B
      io.program.request.valid := true.B
      io.program.request.bits.address := result.state.received
      io.program.request.bits.write := true.B
      io.program.request.bits.data := result.state.loaderWord; io.program.request.bits.mask := 15.U
    }
  }
  when(io.cpuResetActive && (mode === 3.U || mode === 4.U)) { mode := Mux(programmed, 2.U, 0.U) }
  when(resetEdge) {
    resetNeeded := !(io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.ResetApplication.U)
    resetRecovery := true.B
  }

  // Freeze observations at every accepted write/WAIT boundary. Later elapsed
  // intervals collect in a separate slot and cannot move ahead of that action.
  housekeepingAction.offset := req.address(6,0); housekeepingAction.data := req.data
  housekeepingAction.periodUpdate := periodUpdate.valid; housekeepingAction.period := periodUpdate.bits
  housekeepingAction.cpuCompletion := io.request.fire &&
    (housekeepingAction.write || housekeepingAction.waitAccepted || periodUpdate.valid)
  val housekeepingBarrier = housekeepingAction.write || housekeepingAction.waitAccepted || periodUpdate.valid
  val housekeepingQueuedWork = housekeepingQueued.timeValid || housekeepingQueued.discard
  val housekeepingRetry = housekeepingState.requested && !io.adc.busy && !adcLaunchPending && !spiClaimRequested
  val queueBase=housekeepingQueued
  val queueNext=WireDefault(queueBase)
  val nominalSum=queueBase.elapsed(0) +& rawElapsed(0)
  queueNext.elapsed(0):=nominalSum(31,0)
  queueNext.elapsedOverflow:=queueBase.elapsedOverflow || nominalSum(32)
  queueNext.elapsed(1):=queueBase.elapsed(1)+rawElapsed(1)
  queueNext.elapsed(2):=saturatingAdd(queueBase.elapsed(2),rawElapsed(2))
  when(rawTimeValid) {
    queueNext.timeValid:=true.B; queueNext.target:=rawTarget
    queueNext.single:=rawSingle && !queueBase.timeValid
  }
  queueNext.discard:=queueBase.discard || (io.adc.done && !io.adc.result.valid)
  val housekeepingRecoveryReady=io.housekeepingSource.grant.valid &&
    io.housekeepingSource.grant.bits.recovery && io.housekeepingSource.ownerRecovery &&
    io.housekeepingSource.eligible && io.housekeepingSource.recoveryDebt &&
    io.housekeepingSource.decision.ready && !io.applicationCancel &&
    !housekeepingOrderedPending && !io.housekeepingDraining
  housekeepingCommand.valid := !housekeepingOutstanding && !housekeepingBarrier &&
    (housekeepingOrderedPending || housekeepingRecoveryReady ||
      (!io.housekeepingSource.occupied && (io.applicationCancel || !housekeepingRecoveryBlocked) &&
        (housekeepingQueuedWork || rawTimeValid || queueNext.discard || housekeepingRetry) &&
        !cpuTimingTurn && !mmioLaunch && !(mmioCurrent && io.controlReply.valid) && !io.request.fire))
  housekeepingCommand.bits := queueNext
  housekeepingCommand.bits.recovery := housekeepingRecoveryReady
  housekeepingCommand.bits.resetApplication := housekeepingRecoveryReady || io.applicationCancel
  housekeepingCommand.bits.started := started; housekeepingCommand.bits.parked := parked
  housekeepingCommand.bits.adcBusy := io.adc.busy || adcLaunchPending
  when(housekeepingOrderedPending) {
    housekeepingCommand.bits := housekeepingOrdered
    housekeepingCommand.bits.recovery := false.B
  }
  housekeepingRecoveryCommit:=housekeepingCommand.fire && housekeepingCommand.bits.recovery
  val housekeepingOwnedReply=housekeepingReply.bits.cpuCompletion || housekeepingReply.bits.recovery
  housekeepingReply.ready := housekeepingOutstanding &&
    (!housekeepingOwnedReply || io.housekeepingSource.publication.ready)
  io.housekeepingSource.publication.valid:=housekeepingOutstanding && housekeepingReply.valid && housekeepingOwnedReply
  io.housekeepingSource.publication.bits:=housekeepingReply.bits.state.now(0)
  io.housekeepingSource.quiet:= !housekeepingOutstanding && !housekeepingOrderedPending &&
    !io.housekeepingDraining && io.housekeepingSource.publication.ready
  housekeepingQueued:=queueNext
  when(housekeepingCommand.fire) {
    housekeepingOutstanding:=true.B; housekeepingInFlight:=housekeepingCommand.bits
    when(housekeepingOrderedPending) { housekeepingOrderedPending:=false.B }
      .otherwise {
        // Capture on the existing sender's acceptance edge. Its unchanged
        // settling interval precedes the native request.
        housekeepingOrdered:=housekeepingCommand.bits
        // Recovery identity belongs to the one-bit sender and in-flight role;
        // this bank is read as an ordered command only after a non-recovery write.
        housekeepingOrdered.recovery:=false.B
        housekeepingQueued:=0.U.asTypeOf(new HousekeepingCommand)
      }
  }
  when(housekeepingBarrier) {
    assert(!housekeepingOrderedPending,"HOUSEKEEPING_ORDERED_OVERFLOW")
    assert(housekeepingBankAvailable,"HOUSEKEEPING_BORROW_OVERWRITE")
    housekeepingOrdered:=queueNext
    housekeepingOrdered.write:=housekeepingAction.write
    housekeepingOrdered.offset:=housekeepingAction.offset; housekeepingOrdered.data:=housekeepingAction.data
    housekeepingOrdered.waitAccepted:=housekeepingAction.waitAccepted
    housekeepingOrdered.periodUpdate:=periodUpdate.valid; housekeepingOrdered.period:=periodUpdate.bits
    housekeepingOrdered.cpuCompletion:=housekeepingAction.cpuCompletion
    housekeepingOrdered.recovery:=false.B
    housekeepingOrdered.resetApplication:=io.applicationCancel
    housekeepingOrdered.started:=started; housekeepingOrdered.parked:=parked
    housekeepingOrdered.adcBusy:=io.adc.busy || adcLaunchPending
    housekeepingOrderedPending:=true.B; housekeepingQueued:=0.U.asTypeOf(new HousekeepingCommand)
  }
  when(housekeepingPublished) {
    housekeepingOutstanding:=false.B; housekeepingState:=housekeepingReply.bits.state
    housekeepingInFlight:=0.U.asTypeOf(new HousekeepingCommand)
    when(housekeepingReply.bits.startAdc) { adcLaunchPending:=true.B }
    assert(housekeepingReply.bits.recovery === housekeepingInFlight.recovery,
      "HOUSEKEEPING_RECOVERY_ATTRIBUTION")
    when(housekeepingOwnedReply) {
      assert(housekeepingReply.bits.recovery === io.housekeepingSource.ownerRecovery &&
        io.housekeepingSource.publication.fire,"HOUSEKEEPING_PUBLICATION_IDENTITY")
    }
    when(housekeepingReply.bits.cpuCompletion && !housekeepingReply.bits.recovery &&
        !io.housekeepingSource.ownerRecovery && io.housekeepingSource.eligible &&
        !housekeepingRecoveryBlocked && !io.applicationCancel) {
      io.completionHousekeeping.valid:=true.B
      assert(io.completionHousekeeping.ready,"COMPLETION_HOUSEKEEPING_OVERFLOW")
    }
  }
  housekeepingBarrierBusy:=housekeepingOutstanding || housekeepingOrderedPending || housekeepingRecoveryBlocked ||
    io.housekeepingDraining
  housekeepingWork:=housekeepingOutstanding || housekeepingOrderedPending || housekeepingRecoveryBlocked ||
    housekeepingQueuedWork || housekeepingRetry || io.housekeepingDraining || io.housekeepingSource.draining

  // POR ingress compacts every publication and elapsed interval independently
  // of native backpressure. Telemetry retains the complete
  // publications through independent POR-owned ingress and crossings.
  val ageStep = Mux(tick, upperElapsed, 0.U)
  telemetryElapsed := saturatingAdd(Mux(telemetryCommand.fire, 0.U, telemetryElapsed), ageStep)
  for(i <- config.measurements.indices) {
    val capture = telemetryCaptures(i)
    val base = Mux(telemetryCommand.fire, 0.U.asTypeOf(new TelemetryCapture), capture)
    capture := base
    capture.tailAge := saturatingAdd(base.tailAge, ageStep)
    when(publish(i).valid) {
      capture.seen := true.B; capture.count := base.count + 1.U
      capture.valid := publish(i).bits.valid; capture.calibrated := publish(i).bits.calibrated
      when(publish(i).bits.valid) {
        capture.hadValid := true.B; capture.value := publish(i).bits.value; capture.tailAge := publishAge(i)
      }
    }
  }
  val capturesPending = telemetryCaptures.map(_.seen).foldLeft(false.B)(_ || _)
  val observationPending = telemetryElapsed.orR || capturesPending
  telemetryWork := telemetryBarrier || observationPending || io.telemetryDraining || io.telemetrySource.draining
  telemetryAccepted := io.request.fire && nativeMmio && telemetryRequired
  when(telemetryAccepted) {
    assert(io.telemetryCommandIdle && !telemetryOutstanding,"TELEMETRY_COMMIT_BORROW_OVERWRITE")
    telemetryCommitPending := true.B
    telemetryCommit := 0.U.asTypeOf(new TelemetryCommand(config.measurements.size))
    telemetryCommit.kind := TelemetryKind.Commit.U; telemetryCommit.offset := req.address(6,0)
    telemetryCommit.data := req.data; telemetryCommit.appIndex := appIndex
  }
  // CPU validation has priority over background batching. In particular a tick
  // on every service edge cannot prevent forward progress at serviceHz=1000.
  val telemetryRecoveryReady=io.telemetrySource.grant.valid &&
    io.telemetrySource.grant.bits.recovery && io.telemetrySource.ownerRecovery &&
    io.telemetrySource.eligible && io.telemetrySource.recoveryDebt &&
    io.telemetrySource.decision.ready && !telemetryCommitPending && !io.telemetryDraining
  telemetryCommand.valid := !telemetryOutstanding && !io.applicationCancel && !io.telemetryDraining &&
    (telemetryCommitPending || telemetryRecoveryReady ||
      (!io.telemetrySource.occupied && !telemetryRecoveryBlocked &&
        observationPending && !cpuTimingTurn && !mmioCurrent && !mmioLaunch && !io.request.fire))
  telemetryCommand.bits := 0.U.asTypeOf(new TelemetryCommand(config.measurements.size))
  when(telemetryCommitPending) { telemetryCommand.bits := telemetryCommit }
  when(telemetryRecoveryReady) {
    telemetryCommand.bits.kind := TelemetryKind.ResetApplication.U
    telemetryCommand.bits.recovery := true.B
  }
  telemetryRecoveryCommit:=telemetryCommand.fire && telemetryCommand.bits.recovery
  telemetryCommand.bits.elapsedUpper := telemetryElapsed
  telemetryCommand.bits.captures.foreach(_ := telemetryCaptures)
  when(telemetryCommand.fire) {
    telemetryOutstanding := true.B; telemetryInFlight := telemetryCommand.bits
    when(telemetryCommand.bits.kind === TelemetryKind.Commit.U) { telemetryCommitPending := false.B }
  }
  val telemetryOwnedReply=telemetryReply.bits.kind === TelemetryKind.Commit.U || telemetryReply.bits.recovery
  telemetryReply.ready := telemetryOutstanding && (!telemetryOwnedReply || io.telemetrySource.publication.ready)
  io.telemetrySource.publication.valid:=telemetryOutstanding && telemetryReply.valid && telemetryOwnedReply
  io.telemetrySource.publication.bits:=telemetryReply.bits.state.output(0)
  io.telemetrySource.quiet:= !telemetryOutstanding && !telemetryCommitPending &&
    !io.telemetryDraining && io.telemetrySource.publication.ready
  val telemetryApplyBank=IO(Output(Bool()))
  telemetryApplyBank:= !io.applicationCancel &&
    ((telemetryReply.bits.recovery && io.telemetrySource.ownerRecovery && io.telemetrySource.eligible) ||
      (!telemetryReply.bits.recovery && !telemetryRecoveryBlocked))
  when(telemetryReply.fire) {
    val result = telemetryReply.bits
    telemetryOutstanding := false.B; telemetryInFlight := 0.U.asTypeOf(new TelemetryCommand(config.measurements.size))
    result.state.samples.foreach(hostSamples := _)
    assert(result.recovery === telemetryInFlight.recovery,"TELEMETRY_RECOVERY_ATTRIBUTION")
    when(telemetryOwnedReply) {
      assert(result.recovery === io.telemetrySource.ownerRecovery && io.telemetrySource.publication.fire,
        "TELEMETRY_PUBLICATION_IDENTITY")
    }
    val recovered=result.recovery && io.telemetrySource.ownerRecovery && io.telemetrySource.eligible
    // Only an attributed live publication can complete a CPU write.
    // Revoked replies drain and update retained samples, never application state.
    when(!io.applicationCancel && (recovered || (!result.recovery && !telemetryRecoveryBlocked))) {
      when(result.kind === TelemetryKind.Commit.U && !result.recovery &&
          !io.telemetrySource.ownerRecovery && io.telemetrySource.eligible &&
          !telemetryRecoveryBlocked) {
        io.completionTelemetry.valid := true.B
        assert(io.completionTelemetry.ready,"COMPLETION_TELEMETRY_OVERFLOW")
      }
    }
  }

  // Snapshot the selected service bank once, then share one word mux across
  // byte boundaries. This retains coherent read transactions without eight
  // parallel copies of the entire host-address decoder.
  val bankWords = (HostSchema.device.map(_.word) ++ config.application.registers.map(_.word)).distinct.sorted
  val bankSize = bankWords.size
  val bank = Wire(Vec(bankSize, UInt(32.W)))
  bank.foreach(_ := "hffffffff".U)
  val space = selector(23,16); val instance = selector(15,8)
    when(space === 0.U && instance === 0.U) {
      val fields = Seq("h00010000".U, config.application.id.U, config.application.version.U,
        config.programBytes.U, config.workingRamBytes.U, config.gpioCount.U,
        config.measurements.size.U, Mux(io.watchdogReason, 2.U, 1.U), io.crashCount)
      fields.zipWithIndex.foreach { case (value, i) => bank(i) := value }
    }
    when(space === 1.U && instance === 0.U) {
      val fields = Seq(mode, programmed.asUInt, locked.asUInt, canProgram.asUInt, (loaderPending || loaderControlPending || controlState.persistPending).asUInt, lastError,
        imageId, received, Cat(0.U(24.W),controlState.bootIndex,controlState.bootSession,controlState.persisted,controlState.persistPending,controlState.loaderHold))
      fields.zipWithIndex.foreach { case (value, i) => bank(i) := value }
    }
    when(space === 3.U && instance === 0.U) {
      val features = (if(p.lowPower.nonEmpty) 3 | (if(p.adc.nonEmpty) 4 else 0) |
        (if(p.lowPower.exists(_.stopServiceClock)) 8 else 0) else 0).U
      val status = Cat(0.U(28.W), periodPending, sleepRemaining =/= 0.U, !io.clockRunning, p.lowPower.nonEmpty.B)
      val fields = Seq(features, now, samplePeriod, wakeMask, sleepRemaining, pendingView, io.sleepEntries, status)
      fields.zipWithIndex.foreach { case (value, i) => bank(i) := value }
    }
    when(space === 3.U && instance === 1.U) {
      val lp = p.lowPower
      val fields = Seq(lp.map(_.tickMicros).getOrElse(1000).U,
        lp.map(_.minimumTickMicros).getOrElse(1000).U, lp.map(_.maximumTickMicros).getOrElse(1000).U,
        p.minimumSampleMs.U, p.maximumSampleMs.max(0).U, p.staleMs.U,
        (if(lp.exists(_.stopServiceClock)) LowPowerParameters.hostWakeWaitUs else 0).U,
        p.watchdogCycles.U)
      fields.zipWithIndex.foreach { case (value, i) => bank(i) := value }
    }
    for(i <- config.measurements.indices) {
      when(space === 2.U && instance === i.U) {
        val s = hostSamples(i)
        val age = saturatingAdd(saturatingAdd(s.age, telemetryInFlight.elapsedUpper), telemetryElapsed)
        val uncommitted = telemetryCaptures(i).seen || telemetryInFlight.captures.get(i).seen
        val stale = age >= p.freshLimitMs.max(0).U
        val flags = Cat(0.U(27.W), s.calibrated, s.fault, s.never, stale, s.valid && !s.never && !stale && !uncommitted)
        val fields = Seq(s.value, flags, Mux(s.never, "hffffffff".U, age), s.sequence,
          config.measurements(i).unit.U, config.measurements(i).scale10.S(32.W).asUInt)
        fields.zipWithIndex.foreach { case (value, j) => bank(j) := value }
      }
    }
    when(space === 128.U && instance === 0.U) {
      for(register <- config.application.registers) {
        bank(bankWords.indexOf(register.word)) := applicationWord(register.word.U)
      }
    }
  val supported = (0 until 8).map { i =>
    val space = selector(23,16); val instance = selector(15,8); val word = selector(7,0) +& i.U
    val appWord = config.application.registers.map(r => word === r.word.U).foldLeft(false.B)(_ || _)
    (instance === 0.U && space === 0.U && word < HostSchema.device.size.U) ||
      (instance === 0.U && space === 1.U && word < HostSchema.loader.size.U) ||
      (space === 3.U && instance <= 1.U && word < 8.U) ||
      (space === 2.U && instance < config.measurements.size.U && word < 6.U) ||
      (space === 128.U && instance === 0.U && appWord)
  }
  // Only the application host bank borrows native data. Cancellation/recovery
  // selects constant zero, so reset must never block the host receipt.
  bankReadReady:=space =/= 128.U || instance =/= 0.U || io.applicationCancel ||
    telemetryRecoveryBlocked || telemetryBankReady
  val snapshot = Reg(Vec(bankSize, UInt(32.W)))
  val snapshotSupported = Reg(UInt(8.W))
  when(io.i2c.readStart) {
    assert(bankReadReady,"TELEMETRY_SNAPSHOT_WHILE_BANK_SETTLING")
    snapshot := bank; snapshotSupported := Cat(supported.reverse)
  }
  when(io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Mmio.U) {
    assert(telemetryBankReady && !telemetryBarrier,"TELEMETRY_MMIO_WHILE_BANK_SETTLING")
  }
  val readIndex = selector(7,0) +& io.i2c.wordIndex
  io.i2c.readWord := Mux(io.i2c.wordIndex === 8.U, Cat(0.U(24.W), snapshotSupported),
    MuxLookup(readIndex, "hffffffff".U(32.W))(bankWords.zipWithIndex.map { case(word,i) => word.U -> snapshot(i) }))
  // Cancellation wins over coincident stale replies and staging assignments.
  when(io.applicationCancel) { applicationResets.foreach(_()) }
  io.presentationClosed:=RegNext(io.applicationCancel,false.B)
  when(io.applicationCancel) {
    assert(!io.request.fire && !io.admissionGrant.fire,"APPLICATION_CAPTURE_AFTER_CUTOFF")
    assert(!(io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Halt.U),"APPLICATION_HALT_AFTER_CUTOFF")
    assert(!telemetryCommand.fire,"APPLICATION_TELEMETRY_AFTER_CUTOFF")
  }

}
