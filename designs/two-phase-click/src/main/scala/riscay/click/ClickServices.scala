// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._
import riscay.soc._

/** Two explicit register slots; no inferred RAM or unregistered Queue child. */
private class ControlMailbox extends Module with InlineInstance {
  val io = IO(new Bundle {
    val enq = Flipped(Decoupled(new ControlIngress)); val deq = Decoupled(new ControlIngress)
    val count = Output(UInt(2.W))
  })
  val first = RegInit(0.U.asTypeOf(new ControlIngress))
  val second = RegInit(0.U.asTypeOf(new ControlIngress))
  val count = RegInit(0.U(2.W))
  io.count := count; io.enq.ready := count =/= 2.U; io.deq.valid := count =/= 0.U; io.deq.bits := first
  when(io.enq.fire && io.deq.fire) { first := io.enq.bits }
    .elsewhen(io.enq.fire) {
      when(count === 0.U) { first := io.enq.bits }.otherwise { second := io.enq.bits }
      count := count + 1.U
    }.elsewhen(io.deq.fire) { first := second; count := count - 1.U }
}

/** Clocked endpoints behind this variant's native asynchronous fabric. */
class ClickServices(p: SocParameters, boardFactory: SocParameters => BoardProfile) extends ServiceEndpoint {
  val config = p.config
  val board = boardFactory(p)
  require(board.ownedRegisters.subsetOf(config.application.registers.map(_.word).toSet))
  val telemetryWords = config.application.registers.filterNot(r => board.ownedRegisters(r.word)).map(_.word).toVector
  val telemetryCommand = IO(Decoupled(new TelemetryCommand(config.measurements.size)))
  val telemetryReply = IO(Flipped(Decoupled(new TelemetryReply(config.measurements.size, telemetryWords.size))))
  val boardCommand = IO(Decoupled(new SupervisorCommand))
  val boardReply = IO(Flipped(Decoupled(new BoardResult)))
  val boardResult = RegInit(0.U.asTypeOf(new BoardResult))
  val boardWork = WireDefault(false.B)
  boardCommand.valid := false.B; boardCommand.bits := 0.U.asTypeOf(new SupervisorCommand)
  boardReply.ready := false.B
  val program = Module(new SramBank(config.programBytes))
  val ram = Module(new SramBank(config.workingRamBytes))
  Seq((program, io.program), (ram, io.ram)).foreach { case(memory, port) =>
    memory.io.request <> port.bytes; port.completions <> memory.io.response
  }
  Seq(io.program, io.ram).foreach { memory =>
    memory.request.valid := false.B
    memory.request.bits := 0.U.asTypeOf(new SramWordRequest)
    memory.response.ready := true.B
  }
  // Native state owns decisions; this is a coherent clock-domain snapshot.
  val controlState = RegInit(ControlState.initial)
  val controlOutstanding = RegInit(false.B)
  val loaderControlPending = RegInit(false.B)
  val haltPending = withReset(io.cpuReset.asAsyncReset) { RegInit(false.B) }
  val mmioCurrent = withReset(io.cpuReset.asAsyncReset) { RegInit(false.B) }
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
  val rom = VecInit(MemoryMap.boot.map(_.U(32.W)))
  def applicationReg[T <: Data](init: T): T = withReset(io.cpuReset.asAsyncReset) { RegInit(init) }
  val telemetryOutstanding = RegInit(false.B)
  val telemetryResetNeeded = applicationReg(true.B)
  val telemetryRecovery = applicationReg(true.B)
  val telemetryCommitPending = applicationReg(false.B)
  val telemetryCommit = Reg(new TelemetryCommand(config.measurements.size))
  val telemetryBarrier = telemetryOutstanding || telemetryResetNeeded || telemetryRecovery || telemetryCommitPending
  val telemetryWork = Wire(Bool())
  val telemetryAccepted = WireDefault(false.B)
  val telemetryDispatchedEvents = applicationReg(0.U(6.W))
  val telemetryEvents = applicationReg(0.U(6.W))
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
  // Raw application reset only drives reset pins; persistent native state
  // consumes the synchronized reset command before any further CPU command.
  val started = applicationReg(false.B)
  val lastError = controlState.lastError
  val imageLength = controlState.imageLength; val entry = controlState.entry
  val received = controlState.received; val imageId = controlState.imageId
  io.mode := mode; io.programmed := programmed; io.locked := locked
  val canProgram = !locked && !started && !io.cpuResetActive && !io.program.busy && !loaderPending && !controlBusy

  val housekeepingCommand = IO(Decoupled(new HousekeepingCommand))
  val housekeepingReply = IO(Flipped(Decoupled(new HousekeepingReply)))
  val housekeepingState = RegInit(HousekeepingState.initial(p))
  val housekeepingOutstanding = RegInit(false.B)
  val housekeepingInFlight = RegInit(0.U.asTypeOf(new HousekeepingCommand))
  val housekeepingBarrierBusy = Wire(Bool())
  val housekeepingOrdered = Reg(new HousekeepingCommand)
  val housekeepingOrderedPending = RegInit(false.B)
  val housekeepingQueued = RegInit(0.U.asTypeOf(new HousekeepingCommand))
  val housekeepingResetNeeded = RegInit(true.B)
  val housekeepingRecovery = applicationReg(true.B)
  val housekeepingWork = Wire(Bool())
  val housekeepingAction = WireDefault(0.U.asTypeOf(new HousekeepingCommand))
  val now = housekeepingState.now; io.now := now
  // This projection includes retained ingress that the native owner has not
  // published yet. Sampling history must progress independently of that owner.
  val boardNow = housekeepingState.boardNow + housekeepingQueued.elapsed(1) +
    Mux(housekeepingOrderedPending,housekeepingOrdered.elapsed(1),0.U) + housekeepingInFlight.elapsed(1)
  val wakeMask = Mux(housekeepingRecovery,15.U,housekeepingState.wakeMask)
  val sleepRemaining = Mux(housekeepingRecovery,0.U,housekeepingState.lease)
  val deadline = Mux(housekeepingRecovery,0.U,housekeepingState.deadline)
  val parked = WireDefault(false.B)
  val heartbeat = RegInit(false.B); io.heartbeat := heartbeat
  val kickPending = applicationReg(false.B)
  val ack0 = RegNext(io.watchdogAck,false.B); val ack = RegNext(ack0,false.B)
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
    (!housekeepingRecovery || housekeepingReply.bits.resetApplication)
  when(kick || kickPending) {
    when(ack === heartbeat) { heartbeat:= !heartbeat; kickPending:=false.B }
      .otherwise { kickPending:=true.B }
  }
  val elapsed = rawElapsed(0); val lowerElapsed = rawElapsed(1); val upperElapsed = rawElapsed(2)
  val observationMs = Mux(rawSingle,lowerElapsed,0.U)
  val tick = elapsed =/= 0.U
  val leaseExpired = housekeepingPublished && !housekeepingRecovery && housekeepingReply.bits.leaseExpired
  val scalingBusy = io.elapsedScaling.busy || housekeepingWork || rawTimeValid
  val gpio = withClock(io.frontClock) {
    val first = RegNext(io.gpioIn, 0.U); RegNext(first, 0.U)
  }
  io.observedGpio := gpio
  val gpioPrevious = RegNext(gpio, 0.U)
  val output = applicationReg(config.application.pins.filter(_.resetHigh).map(x => BigInt(1) << x.index).sum.U(32.W))
  val enable = applicationReg(config.application.pins.filter(_.output).map(x => BigInt(1) << x.index).sum.U(32.W))
  val gpioMask = ((BigInt(1) << config.gpioCount) - 1).U(32.W)
  val application = telemetryWords.map(word => word -> applicationReg(0.U(32.W))).toMap
  val appIndex = controlState.appIndex
  def applicationWord(word: UInt): UInt = MuxLookup(word, "hffffffff".U(32.W))(
    config.application.registers.map(r => r.word.U ->
      (if(board.ownedRegisters(r.word)) boardResult.registers(r.word) else application(r.word))))
  def applicationExists(word: UInt): Bool = config.application.registers.map(r => word === r.word.U).foldLeft(false.B)(_ || _)

  // Both native consumers receive the same retained acquisition stream.
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
      io.adc.start := adcLaunchPending && !io.adc.busy
      when(io.adc.start) { adcLaunchPending := false.B }
      adcBusy := io.adc.busy || adcLaunchPending || housekeepingState.requested || periodPending
    }
    publish(0) := io.adc.result; publishAge(0) := io.adc.age
  }
  // POR-owned input history. No power policy or qualification counter is
  // clocked here. Min/max, validity gaps and GPIO discontinuities prevent a
  // stalled native consumer from fabricating stable observations.
  if(board.ownedRegisters.nonEmpty) {
    val outstanding=RegInit(false.B); val needed=RegInit(true.B)
    val queued=RegInit(0.U.asTypeOf(new SupervisorCommand))
    // Retain the complete registered ABI even when a board's ADC fixes flags.
    dontTouch(queued.capture)
    val previousGpio=RegNext(gpio,0.U)
    val changes=(gpio ^ previousGpio) & gpioMask
    val ageStep=Mux(tick,upperElapsed,0.U)
    val pub=publish(0)
    boardCommand.valid := needed && !outstanding
    boardCommand.bits := queued; boardCommand.bits.now := boardNow
    boardCommand.bits.power := boardResult.outputs(0); boardCommand.bits.shutdown := boardResult.outputs(1)
    boardReply.ready := outstanding
    when(boardCommand.fire) { outstanding := true.B; needed := false.B }
    when(boardReply.fire) { outstanding := false.B; boardResult := boardReply.bits }
    when(tick || changes.orR || pub.valid) { needed := true.B }
    val base=Mux(boardCommand.fire,0.U.asTypeOf(new SupervisorCommand),queued)
    queued := base; queued.gpio := gpio; queued.gpioChanged := base.gpioChanged | changes
    queued.tick := base.tick || tick
    queued.elapsedUpper := saturatingAdd(base.elapsedUpper,ageStep)
    queued.observationMs := saturatingAdd(base.observationMs,Mux(tick,observationMs,0.U))
    when(tick && !base.tick) { queued.firstObservationMs := observationMs }
    queued.observationGap := base.observationGap || (tick && observationMs === 0.U)
    val capture=queued.capture; val prior=base.capture
    val ageAtPublication=saturatingAdd(prior.tailAge,ageStep)
    capture.tailAge := ageAtPublication
    when(pub.valid) {
      capture.seen := true.B; capture.count := prior.count+1.U
      capture.valid := pub.bits.valid; capture.calibrated := pub.bits.calibrated
      capture.failed := prior.failed || !pub.bits.valid
      when(pub.bits.valid) {
        capture.hadValid := true.B; capture.value := pub.bits.value; capture.tailAge := publishAge(0)
        capture.minimum := Mux(!prior.hadValid || pub.bits.value < prior.minimum,pub.bits.value,prior.minimum)
        capture.maximum := Mux(!prior.hadValid || pub.bits.value > prior.maximum,pub.bits.value,prior.maximum)
        when(!prior.hadValid) { capture.firstAge := ageAtPublication }
          .otherwise { capture.maximumGap := Mux(ageAtPublication > prior.maximumGap,ageAtPublication,prior.maximumGap) }
      }
    }
    boardWork := needed || outstanding || io.boardDraining
  }
  io.gpioOut := ((output & ~board.mask.U(32.W)) | (boardResult.outputs & board.mask.U(32.W))) & gpioMask
  io.gpioOe := ((enable & ~board.mask.U(32.W)) | (board.enables.U(32.W) & board.mask.U(32.W))) & gpioMask

  val pendingState = applicationReg(0.U(6.W))
  // Captured sets are irrevocable and visible while awaiting native commit.
  // A CPU clear/replacement is serialized against in-flight native work.
  val pending = pendingState | telemetryEvents | telemetryDispatchedEvents
  val clear = WireDefault(0.U(32.W))
  val replaceDeadline = WireDefault(false.B)
  val hostWake = WireDefault(false.B)
  val due = housekeepingPublished && !housekeepingRecovery && !replaceDeadline && housekeepingReply.bits.due
  val acquisition = if(config.measurements.isEmpty) false.B else publish.map(_.valid).reduce(_ || _)
  val gpioActivity = ((gpio ^ gpioPrevious) & gpioMask).orR
  val events = Cat(0.U(26.W), hostWake, leaseExpired, acquisition, gpioActivity, due, tick)
  // Native validation adds a handshake window before the peripheral commit.
  // Preserve every event raised during that window against a software clear.
  val mmioEvents = applicationReg(0.U(32.W))
  // The request may already be waiting while a previous completion drains.
  // Events since its arrival must survive a later clear, not only events since
  // Control dispatch. Otherwise extra return latency loses a coincident GPIO.
  val mmioObserved = applicationReg(false.B)
  val observingMmio = io.request.valid && io.request.bits.address >= MemoryMap.mmio.U &&
    io.request.bits.address < (MemoryMap.mmio + 76).U && io.request.bits.operation =/= Operation.Halt.U
  when(observingMmio) {
    mmioEvents := Mux(mmioObserved,mmioEvents,0.U) | events
    mmioObserved := true.B
  }
  when(!io.request.valid || io.request.fire) { mmioObserved := false.B }

  // Replacement consumes only the old deadline, including an expiry on this
  // edge. Other new events still win acknowledgement races.
  val acceptedClear = (clear | Mux(replaceDeadline, 2.U, 0.U))(5,0)
  telemetryEvents := (Mux(telemetryCommand.fire, 0.U, telemetryEvents) & ~acceptedClear) | events(5,0)

  // Native credit gates admission at the original commit edge. Keep the held
  // request visible above while waiting, including its MMIO event-clear window.
  io.admissionGrant.ready := io.request.fire
  val response = WireDefault(0.U.asTypeOf(new MemoryResponse))
  val waitMemory = WireDefault(false.B)
  io.response <> io.completionResponse
  io.completionPlan.valid := io.request.fire && io.request.bits.operation =/= Operation.Halt.U
  io.completionPlan.bits.response := response
  io.completionPlan.bits.memory := waitMemory
  io.completionPlan.bits.telemetry := telemetryAccepted
  io.completionPlan.bits.housekeeping := housekeepingAction.cpuCompletion
  io.completionMemory.valid := false.B; io.completionMemory.bits := 0.U.asTypeOf(new MemoryResponse)
  io.completionTelemetry.valid := false.B; io.completionTelemetry.bits := true.B
  io.completionHousekeeping.valid := false.B; io.completionHousekeeping.bits := true.B
  val completionAvailable = io.completionIdle && io.completionPlan.ready && io.completionMemory.ready &&
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
  io.ramSource.reserve.valid := io.request.valid && ramOperation && !io.cpuResetActive &&
    !resetRecovery && !io.ramSource.resetDebt
  io.ramSource.reserve.bits := isWrite
  val ramCommit = io.request.fire && ramOperation
  io.ramSource.grant.ready := io.ramSource.decision.ready && (ramCommit || io.ramSource.resetDebt)
  io.ramSource.decision.valid := io.ramSource.grant.fire
  io.ramSource.decision.bits := ramCommit
  io.ram.response.ready := io.ramSource.publication.ready
  io.ramSource.publication.valid := io.ram.response.valid
  io.ramSource.publication.bits := io.ram.response.bits(0)
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
    !controlBusy && !io.cpuResetActive && !resetRecovery && !io.programSource.resetDebt)
  io.programSource.reserve.bits := loaderOffer
  val programCpuCommit = io.request.fire && programCpuOperation
  val programLoaderCommit = io.controlReply.fire && io.controlReply.bits.programWrite
  val programCancel = !io.programSource.grant.bits &&
    (io.programSource.resetDebt || io.cpuResetActive || resetRecovery || controlBusy ||
      !io.request.valid || !programCpuOperation)
  io.programSource.grant.ready := io.programSource.decision.ready &&
    (programCpuCommit || programLoaderCommit || programCancel)
  io.programSource.decision.valid := io.programSource.grant.fire
  io.programSource.decision.bits := programCpuCommit || programLoaderCommit
  io.program.response.ready := io.programSource.publication.ready
  io.programSource.publication.valid := io.program.response.valid
  io.programSource.publication.bits := io.program.response.bits(0)
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
  val bootWait = isRead && fullWord && req.address === MemoryMap.mmio.U && !started
  val waitingRead = isRead && fullWord && req.address === (MemoryMap.mmio + 16).U
  val eventWait = waitingRead && (pending & (wakeMask | "h30".U)) === 0.U
  parked := io.request.valid && eventWait
  val parkedForSleep = p.lowPower.nonEmpty.B && io.request.valid &&
    (bootWait || (eventWait && sleepRemaining =/= 0.U)) && io.admissionGrant.valid && !adcBusy && !memoryBusy && !controlBusy
  io.canSleep := parkedForSleep && !io.programSource.draining && !io.ramSource.draining && !scalingBusy && !tick && !telemetryWork && !boardWork
  val nativeMmio = req.address >= MemoryMap.mmio.U && req.address < (MemoryMap.mmio + 76).U &&
    req.operation =/= Operation.Halt.U
  val mmioComplete = io.controlReply.fire && io.controlReply.bits.kind === ControlKind.Mmio.U && mmioCurrent
  val cpuAvailable = completionAvailable && !io.cpuResetActive && !resetRecovery && io.clockRunning && io.admissionGrant.valid && !bootWait && !eventWait &&
    !memoryBusy && !loaderWrite && !telemetryBarrier && !housekeepingBarrierBusy &&
    !io.telemetrySource.resetDebt && !io.housekeepingSource.resetDebt
  // Reserve from a validated, held Control reply. An unused parked WAIT owns
  // no source. Engine readiness excludes these reservations, avoiding self-wait.
  val currentMmio=controlOutstanding && mmioCurrent && io.controlReply.valid &&
    io.controlReply.bits.kind === ControlKind.Mmio.U && io.request.valid && nativeMmio
  val successfulWrite=isWrite && !io.controlReply.bits.memory.error
  val telemetryRequired=successfulWrite &&
    Seq(8,12,24,28,44,52).map(x => req.address(6,0) === x.U).reduce(_ || _)
  val housekeepingWriteRequired=successfulWrite &&
    Seq(8,32,56,60,64).map(x => req.address(6,0) === x.U).reduce(_ || _)
  val housekeepingRequired=waitingRead || housekeepingWriteRequired
  val publicationAdmission=(!telemetryRequired ||
    (io.telemetrySource.grant.valid && io.telemetrySource.decision.ready)) &&
    (!housekeepingRequired || (io.housekeepingSource.grant.valid && io.housekeepingSource.decision.ready))
  for((source,required) <- Seq(io.telemetrySource -> telemetryRequired,io.housekeepingSource -> housekeepingRequired)) {
    source.reserve.valid:=currentMmio && required && cpuAvailable
    source.reserve.bits:=req.data(0)
    val committed=io.request.fire && nativeMmio && required
    val cancelled=source.resetDebt || io.cpuResetActive || !currentMmio || !required
    source.grant.ready:=source.decision.ready && (committed || cancelled)
    source.decision.valid:=source.grant.fire; source.decision.bits:=committed
    source.drain.ready:=source.quiet
    when(committed) {
      assert(source.grant.fire && source.decision.fire && source.eligible,
        "PUBLICATION_SOURCE_COMMIT_NOT_ATOMIC")
      assert(source.grant.bits === req.data(0),"PUBLICATION_SOURCE_GRANT_IDENTITY")
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
  // Accepted stores finish through a watchdog reset, but their CPU completion
  // is discarded. POR may abort a partial word; neither reset clears SRAM bits.
  when(io.program.response.fire && !io.programSource.ownerLoader && io.programSource.eligible &&
      !io.programSource.resetDebt && !io.cpuResetActive) {
    io.completionMemory.valid := true.B
    io.completionMemory.bits.error := false.B
    io.completionMemory.bits.data := io.program.response.bits
    assert(io.completionMemory.ready,"COMPLETION_MEMORY_OVERFLOW")
  }
  // The exclusive SRAM pipeline's actual publication qualifies this retained
  // cancellation attribute. Eligibility alone never denotes a pending response.
  when(io.ram.response.fire && io.ramSource.eligible && !io.ramSource.resetDebt && !io.cpuResetActive) {
    io.completionMemory.valid := true.B
    io.completionMemory.bits.error := false.B
    io.completionMemory.bits.data := io.ram.response.bits
    assert(io.completionMemory.ready,"COMPLETION_MEMORY_OVERFLOW")
  }
  when(io.request.fire) {
    when(waitingRead) { housekeepingAction.waitAccepted := true.B }
    when(nativeMmio && housekeepingWriteRequired && req.address(6,0) =/= 64.U) { housekeepingAction.write := true.B }
    response.data := 0.U; response.error := true.B
    when(req.operation === Operation.Halt.U) { haltPending := true.B }
      .elsewhen(req.address < (MemoryMap.boot.size * 4).U && !isWrite) {
        response.data := rom(req.address(3, 2)); response.error := false.B
      }.elsewhen(req.address >= MemoryMap.program.U && req.address < (MemoryMap.program + config.programBytes).U) {
        when(programCpuOperation) {
          io.program.request.valid := true.B
          io.program.request.bits.address := req.address - MemoryMap.program.U
          waitMemory := true.B
        }
      }.elsewhen(ramOperation) {
        io.ram.request.valid := true.B
        waitMemory := true.B
      }.elsewhen(!isFetch && req.address >= MemoryMap.mmio.U && req.address < (MemoryMap.mmio + 76).U && fullWord) {
        val offset = req.address(6, 0)
        response := io.controlReply.bits.memory
        when(isWrite && !io.controlReply.bits.memory.error) {
          switch(offset) {
            is(8.U) { replaceDeadline := true.B; response.error := false.B }
            is(12.U) { clear := req.data & ~mmioEvents; response.error := false.B }
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

  io.activity := io.programSource.draining || io.ramSource.draining || scalingBusy || io.i2c.busy || gpioActivity || memoryBusy || controlBusy || telemetryWork || boardWork
  // The normal seven-edge guard may drain while native maintenance is busy;
  // canSleep/activity still keep the gate open until that work actually drains.
  io.drainDemand := !parkedForSleep || io.i2c.busy || gpioActivity
  io.hostSelected := io.i2c.selected; io.hostRejected := io.i2c.rejected
  val selector = controlState.selector
  private val hostFrames = Module(new ControlMailbox)
  io.i2c.resetActive := io.cpuResetActive
  io.i2c.programBusy := io.program.busy || loaderPending || loaderControlPending ||
    (io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Host.U &&
      io.controlCommand.bits.frame.bytes(0) >= 1.U && io.controlCommand.bits.frame.bytes(0) <= 6.U)
  io.hostFrameAccepted := hostFrames.io.enq.fire
  hostFrames.io.enq.valid := io.i2c.frame.valid; hostFrames.io.enq.bits.frame := io.i2c.frame.bits.frame
  hostFrames.io.enq.bits.resetActive := io.cpuResetActive || io.i2c.frame.bits.resetActive
  hostFrames.io.enq.bits.programBusy := io.i2c.frame.bits.programBusy || io.program.busy || loaderPending || loaderControlPending ||
    (io.controlCommand.fire && io.controlCommand.bits.kind === ControlKind.Host.U &&
      io.controlCommand.bits.frame.bytes(0) >= 1.U && io.controlCommand.bits.frame.bytes(0) <= 6.U)
  assert(!io.i2c.frame.valid || hostFrames.io.enq.ready, "CONTROL_HOST_MAILBOX_OVERFLOW")
  // Mark exactly the frames already queued at reset; later explicit STARTs
  // belong to the new application lifetime. No wrapping epoch counter.
  val hostResetDebt = RegInit(0.U(2.W))
  when(hostFrames.io.deq.fire && hostResetDebt =/= 0.U) { hostResetDebt := hostResetDebt - 1.U }
  when(resetEdge) { hostResetDebt := hostFrames.io.count - hostFrames.io.deq.fire.asUInt }
  // Reserve a bounded CPU admission turn before starting more background work.
  // A stalled Control computation still permits independent timer maintenance.
  val cpuTimingTurn=io.request.valid && nativeMmio && !bootWait && !eventWait && !io.cpuResetActive &&
    (!controlOutstanding || (mmioCurrent && io.controlReply.valid))
  val mmioLaunch = io.request.valid && nativeMmio && cpuAvailable
  controlBusy := controlOutstanding || io.programSource.stored.valid || mmioCommitPending || resetPending || haltPending || hostFrames.io.deq.valid
  io.controlCommand.valid := !controlOutstanding &&
    (io.programSource.stored.valid || mmioCommitPending || resetPending || haltPending || hostFrames.io.deq.valid || mmioLaunch)
  io.controlCommand.bits := 0.U.asTypeOf(new ControlCommand)
  io.controlCommand.bits.kind := Mux(io.programSource.stored.valid, ControlKind.Stored.U,
    Mux(mmioCommitPending, ControlKind.MmioCommit.U, Mux(resetPending, ControlKind.ResetApplication.U,
      Mux(haltPending, ControlKind.Halt.U, Mux(hostFrames.io.deq.valid, ControlKind.Host.U, ControlKind.Mmio.U)))))
  io.controlCommand.bits.frame := Mux(hostFrames.io.deq.valid, hostFrames.io.deq.bits.frame, 0.U.asTypeOf(new HostFrame))
  io.controlCommand.bits.cpuResetActive := io.cpuResetActive ||
    (hostFrames.io.deq.valid && (hostFrames.io.deq.bits.resetActive || hostResetDebt =/= 0.U))
  io.controlCommand.bits.programBusy := io.program.busy ||
    (hostFrames.io.deq.valid && hostFrames.io.deq.bits.programBusy)
  io.controlCommand.bits.memory := req
  io.controlCommand.bits.applicationWritable := application.keys.toSeq.map(i => appIndex === i.U).foldLeft(false.B)(_ || _)
  io.controlCommand.bits.peripheralData := MuxLookup(req.address(6,0), 0.U(32.W))(Seq(
    4.U -> now, 8.U -> deadline, 12.U -> pending, 16.U -> pending,
    20.U -> (gpio & gpioMask), 24.U -> io.gpioOut, 28.U -> io.gpioOe,
    52.U -> applicationWord(appIndex), 56.U -> wakeMask, 60.U -> sleepRemaining,
    64.U -> samplePeriod, 68.U -> Cat(0.U(28.W), periodPending, sleepRemaining =/= 0.U, !io.clockRunning, p.lowPower.nonEmpty.B),
    72.U -> io.sleepEntries))
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
      (!telemetryBarrier && !housekeepingBarrierBusy && completionAvailable && !io.cpuResetActive &&
        !resetRecovery && io.clockRunning && io.admissionGrant.valid && !bootWait && !eventWait &&
        !memoryBusy && !io.telemetrySource.resetDebt && !io.housekeepingSource.resetDebt && publicationAdmission)) &&
    (!io.controlReply.bits.periodUpdate || !housekeepingOrderedPending) &&
    (!io.controlReply.bits.programWrite || programLoaderReady)
  when(io.controlReply.fire) {
    val result = io.controlReply.bits
    controlOutstanding := false.B; loaderControlPending := false.B; controlState := result.state
    mode := Mux((io.cpuResetActive || resetRecovery) && (result.state.mode === 3.U || result.state.mode === 4.U),
      Mux(result.state.programmed, 2.U, 0.U), result.state.mode)
    started := result.state.started && !io.cpuResetActive && !resetRecovery
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
  val housekeepingReset = housekeepingResetNeeded || housekeepingRecovery
  val housekeepingRetry = housekeepingState.requested && !io.adc.busy && !adcLaunchPending
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
  housekeepingCommand.valid := !housekeepingOutstanding && !housekeepingBarrier &&
    (housekeepingOrderedPending || (!io.housekeepingSource.occupied && (housekeepingReset ||
      ((housekeepingQueuedWork || rawTimeValid || queueNext.discard || housekeepingRetry) && !cpuTimingTurn && !mmioLaunch &&
        !(mmioCurrent && io.controlReply.valid) && !io.request.fire))))
  housekeepingCommand.bits := queueNext
  housekeepingCommand.bits.resetApplication := housekeepingReset || io.cpuResetActive
  housekeepingCommand.bits.started := started; housekeepingCommand.bits.parked := parked
  housekeepingCommand.bits.adcBusy := io.adc.busy || adcLaunchPending
  when(housekeepingOrderedPending) { housekeepingCommand.bits := housekeepingOrdered }
  housekeepingReply.ready := housekeepingOutstanding &&
    (!housekeepingReply.bits.cpuCompletion || io.housekeepingSource.publication.ready)
  io.housekeepingSource.publication.valid:=housekeepingOutstanding && housekeepingReply.valid && housekeepingReply.bits.cpuCompletion
  io.housekeepingSource.publication.bits:=housekeepingReply.bits.state.now(0)
  io.housekeepingSource.quiet:= !housekeepingOutstanding && !housekeepingOrderedPending &&
    !io.housekeepingDraining && io.housekeepingSource.publication.ready
  housekeepingQueued:=queueNext
  when(housekeepingCommand.fire) {
    housekeepingOutstanding:=true.B; housekeepingInFlight:=housekeepingCommand.bits
    when(housekeepingOrderedPending) { housekeepingOrderedPending:=false.B }
      .otherwise { housekeepingResetNeeded:=false.B; housekeepingQueued:=0.U.asTypeOf(new HousekeepingCommand) }
  }
  when(housekeepingBarrier) {
    assert(!housekeepingOrderedPending,"HOUSEKEEPING_ORDERED_OVERFLOW")
    housekeepingOrdered:=queueNext
    housekeepingOrdered.write:=housekeepingAction.write
    housekeepingOrdered.offset:=housekeepingAction.offset; housekeepingOrdered.data:=housekeepingAction.data
    housekeepingOrdered.waitAccepted:=housekeepingAction.waitAccepted
    housekeepingOrdered.periodUpdate:=periodUpdate.valid; housekeepingOrdered.period:=periodUpdate.bits
    housekeepingOrdered.cpuCompletion:=housekeepingAction.cpuCompletion
    housekeepingOrdered.resetApplication:=io.cpuResetActive
    housekeepingOrdered.started:=started; housekeepingOrdered.parked:=parked
    housekeepingOrdered.adcBusy:=io.adc.busy || adcLaunchPending
    housekeepingOrderedPending:=true.B; housekeepingQueued:=0.U.asTypeOf(new HousekeepingCommand)
  }
  when(housekeepingPublished) {
    housekeepingOutstanding:=false.B; housekeepingState:=housekeepingReply.bits.state
    housekeepingInFlight:=0.U.asTypeOf(new HousekeepingCommand)
    when(housekeepingReply.bits.startAdc) { adcLaunchPending:=true.B }
    when(housekeepingReply.bits.resetApplication && !housekeepingResetNeeded && !io.cpuResetActive) {
      housekeepingRecovery:=false.B
    }
    when(housekeepingReply.bits.cpuCompletion && io.housekeepingSource.eligible &&
        !io.housekeepingSource.resetDebt && !io.cpuResetActive) {
      io.completionHousekeeping.valid:=true.B
      assert(io.completionHousekeeping.ready,"COMPLETION_HOUSEKEEPING_OVERFLOW")
    }
  }
  when(resetEdge) { housekeepingResetNeeded:=true.B }
  housekeepingBarrierBusy:=housekeepingOutstanding || housekeepingOrderedPending || housekeepingReset ||
    io.housekeepingDraining
  housekeepingWork:=housekeepingOutstanding || housekeepingOrderedPending || housekeepingReset ||
    housekeepingQueuedWork || housekeepingRetry || io.housekeepingDraining || io.housekeepingSource.draining

  // POR ingress compacts every publication and elapsed interval independently
  // of native backpressure. The separate native supervisor receives the same
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
  val observationPending = telemetryEvents.orR || telemetryElapsed.orR || capturesPending
  telemetryWork := telemetryBarrier || observationPending || io.telemetryDraining || io.telemetrySource.draining
  telemetryAccepted := io.request.fire && nativeMmio && telemetryRequired
  when(telemetryAccepted) {
    telemetryCommitPending := true.B
    telemetryCommit := 0.U.asTypeOf(new TelemetryCommand(config.measurements.size))
    telemetryCommit.kind := TelemetryKind.Commit.U; telemetryCommit.offset := req.address(6,0)
    telemetryCommit.data := req.data; telemetryCommit.appIndex := appIndex; telemetryCommit.clear := acceptedClear
  }
  // CPU validation has priority over background batching. In particular a tick
  // on every service edge cannot prevent forward progress at serviceHz=1000.
  telemetryCommand.valid := !telemetryOutstanding && !io.cpuResetActive &&
    (telemetryCommitPending || (!io.telemetrySource.occupied && (telemetryResetNeeded ||
      (observationPending && !cpuTimingTurn && !mmioCurrent && !mmioLaunch && !io.request.fire))))
  telemetryCommand.bits := 0.U.asTypeOf(new TelemetryCommand(config.measurements.size))
  when(telemetryCommitPending) { telemetryCommand.bits := telemetryCommit }
  when(telemetryResetNeeded) { telemetryCommand.bits.kind := TelemetryKind.ResetApplication.U }
  telemetryCommand.bits.events := telemetryEvents
  telemetryCommand.bits.elapsedUpper := telemetryElapsed
  telemetryCommand.bits.captures.foreach(_ := telemetryCaptures)
  when(telemetryCommand.fire) {
    telemetryOutstanding := true.B; telemetryInFlight := telemetryCommand.bits
    telemetryDispatchedEvents := telemetryCommand.bits.events
    when(telemetryCommand.bits.kind === TelemetryKind.ResetApplication.U) { telemetryResetNeeded := false.B }
    when(telemetryCommand.bits.kind === TelemetryKind.Commit.U) { telemetryCommitPending := false.B }
  }
  telemetryReply.ready := telemetryOutstanding &&
    (telemetryReply.bits.kind =/= TelemetryKind.Commit.U || io.telemetrySource.publication.ready)
  io.telemetrySource.publication.valid:=telemetryOutstanding && telemetryReply.valid &&
    telemetryReply.bits.kind === TelemetryKind.Commit.U
  io.telemetrySource.publication.bits:=telemetryReply.bits.state.output(0)
  io.telemetrySource.quiet:= !telemetryOutstanding && !telemetryCommitPending &&
    !io.telemetryDraining && io.telemetrySource.publication.ready
  when(telemetryReply.fire) {
    val result = telemetryReply.bits
    telemetryDispatchedEvents := 0.U
    telemetryOutstanding := false.B; telemetryInFlight := 0.U.asTypeOf(new TelemetryCommand(config.measurements.size))
    result.state.samples.foreach(hostSamples := _)
    val recovered = result.kind === TelemetryKind.ResetApplication.U && !telemetryResetNeeded && !io.cpuResetActive
    when(recovered) { telemetryRecovery := false.B }
    when(!io.cpuResetActive && (!telemetryRecovery || recovered)) {
      output := result.state.output; enable := result.state.enable; pendingState := result.state.pending
      for((word,index) <- telemetryWords.zipWithIndex) { application(word) := result.state.application.get(index) }
      when(result.kind === TelemetryKind.Commit.U && io.telemetrySource.eligible &&
          !io.telemetrySource.resetDebt) {
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
      val fields = Seq(mode, programmed.asUInt, locked.asUInt, canProgram.asUInt, (loaderPending || loaderControlPending).asUInt, lastError,
        imageId, received)
      fields.zipWithIndex.foreach { case (value, i) => bank(i) := value }
    }
    when(space === 3.U && instance === 0.U) {
      val features = (if(p.lowPower.nonEmpty) 3 | (if(p.adc.nonEmpty) 4 else 0) |
        (if(p.lowPower.exists(_.stopServiceClock)) 8 else 0) else 0).U
      val status = Cat(0.U(28.W), periodPending, sleepRemaining =/= 0.U, !io.clockRunning, p.lowPower.nonEmpty.B)
      val fields = Seq(features, now, samplePeriod, wakeMask, sleepRemaining, pending, io.sleepEntries, status)
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
      (instance === 0.U && space === 1.U && word < 8.U) ||
      (space === 3.U && instance <= 1.U && word < 8.U) ||
      (space === 2.U && instance < config.measurements.size.U && word < 6.U) ||
      (space === 128.U && instance === 0.U && appWord)
  }
  val snapshot = Reg(Vec(bankSize, UInt(32.W)))
  val snapshotSupported = Reg(UInt(8.W))
  when(io.i2c.readStart) { snapshot := bank; snapshotSupported := Cat(supported.reverse) }
  val readIndex = selector(7,0) +& io.i2c.wordIndex
  io.i2c.readWord := Mux(io.i2c.wordIndex === 8.U, Cat(0.U(24.W), snapshotSupported),
    MuxLookup(readIndex, "hffffffff".U(32.W))(bankWords.zipWithIndex.map { case(word,i) => word.U -> snapshot(i) }))
}
