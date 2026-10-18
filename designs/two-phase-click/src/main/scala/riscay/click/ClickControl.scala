// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ClickTiming, ModelTime}
import chiselasync.protocol.TwoPhase
import chiselasync.primitives.AsymmetricCElement
import riscay._
import riscay.soc._

/** POR-owned native state token. Application reset is a serialized command;
  * accepted SRAM completion is accounted independently of application lifetime.
  * Peripheral commits route through explicit endpoint boundaries.
  */
class ClickControl(p: SocParameters, domain: ResetDomain,
    owners: OwnerTiming = OwnerTiming()) extends AsyncModule(domain) {
  val command = twoPhaseInput("command", new ControlCommand)
  val reply = twoPhaseOutput("reply", new ControlReply(p.config.programBytes))
  val start = IO(Input(Bool()))
  private val timing = OwnerTiming.passive(owners.controlOwner)
  private val state = asyncChild("state")(d => new PhaseDecoupledClickBuffer(new ControlToken(p.config.programBytes),
    timing, Some(ControlToken.initial(p.config.programBytes)), d))
  private val join = asyncChild("join")(d => new ClickJoin(new ControlToken(p.config.programBytes), new ControlCommand, timing, d))
  private val update = asyncChild("update")(d => new ClickStage(new Joined(new ControlToken(p.config.programBytes), new ControlCommand),
    new ControlReply(p.config.programBytes), (x: Joined[ControlToken, ControlCommand]) => transition(x.left.state, x.right, x.left.pendingCrc), OwnerTiming.passive(owners.controlUpdate), d))
  // Compute only the candidate CRC here; update retains the entire context.
  // Every feedback starts from architectural crc, even while loaderPending
  // survives other commands. Only Stored commits the candidate to that state.
  private val crc = asyncChild("crc")(ClickCrc32.stage)
  private val fork = asyncChild("fork")(d => new ClickFork(new ControlReply(p.config.programBytes), d))
  // The unbuffered fork contract describes its complete payload on both branches.
  // Retain the fields that the state feedback branch does not consume.
  dontTouch(fork.left)
  state.start.get := start
  TwoPhase.connect(join.left, state.out); TwoPhase.connect(join.right, command)
  TwoPhase.connect(update.in, join.out); TwoPhase.connect(fork.in, update.out)
  private val cell = ModelTime.ps(1000)
  private def rendezvous(id: String, a: Bool, b: Bool): Bool = {
    val gate = Module(new AsymmetricCElement(2, 0, 0, cell))
    gate.reset := reset; gate.common := Cat(a,b); gate.rising := 1.U; gate.falling := 0.U
    contract.primitive(id, gate, Map("COMMON" -> BigInt(2), "RISING" -> BigInt(0), "FALLING" -> BigInt(0),
      "DELAY_FS" -> BigInt(cell.fs), "RESET_VALUE" -> BigInt(0), "COMMON_INVERT" -> BigInt(0),
      "RISING_INVERT" -> BigInt(0), "FALLING_INVERT" -> BigInt(0)), contract.endpoint(id+"_reset", reset),
      "retained CRC/context rendezvous with complete native phase acknowledgment")
    gate.q
  }
  crc.in.bits.crc := fork.left.bits.state.crc
  crc.in.bits.word := fork.left.bits.state.loaderWord
  crc.in.bits.pending := fork.left.bits.state.loaderPending
  crc.in.req := fork.left.req
  state.in.bits.state := fork.left.bits.state; state.in.bits.pendingCrc := crc.out.bits
  state.in.req := rendezvous("crc_context_request", fork.left.req, crc.out.req)
  crc.out.ack := state.in.ack
  // Both phase polarities require state capture and CRC ingress acceptance.
  fork.left.ack := rendezvous("crc_context_return", state.in.ack, crc.in.ack)
  TwoPhase.connect(reply, fork.right)
  contract.endpoint("start", start)

  private def transition(s: ControlState, c: ControlCommand, pendingCrc: UInt): ControlReply = {
    val r = WireDefault(0.U.asTypeOf(new ControlReply(p.config.programBytes))); r.kind := c.kind; r.state := s
    val n = r.state
    val config = p.config
    val gpioMask = ((BigInt(1) << config.gpioCount) - 1).U(32.W)
    def validPeriod(value: UInt): Bool = (p.lowPower.nonEmpty && p.adc.nonEmpty).B &&
      value >= p.minimumSampleMs.U && value <= p.maximumSampleMs.max(0).U
    def appExists(word: UInt): Bool = config.application.registers.map(x => word === x.word.U).foldLeft(false.B)(_ || _)
    val canProgram = !s.locked && !s.started && !c.cpuResetActive && !c.programBusy && !s.loaderPending
    val f = c.frame
    def parameter(index: Int): UInt = Cat((0 until 4).reverse.map(i => f.bytes(1 + index * 4 + i)))
    val op = f.bytes(0)
    val length = MuxLookup(op, 0.U)(Seq(0.U -> 4.U, 1.U -> 33.U, 2.U -> 9.U,
      3.U -> 1.U, 4.U -> 1.U, 5.U -> 1.U, 6.U -> 1.U, 7.U -> 5.U, 8.U -> 1.U, 9.U -> 1.U, 10.U -> 1.U))
    switch(c.kind) {
      is(ControlKind.Stored.U) {
        when(s.loaderPending) {
          n.received := s.received + 4.U; n.crc := pendingCrc; n.loaderPending := false.B
        }
      }
      is(ControlKind.ResetApplication.U) {
        n.started := false.B; n.appIndex := 0.U
        // Stored completion has dispatch priority over this reset command.
        when(s.bootSession) { n.bootSession := false.B; n.bootIndex := 0.U; n.mode := 0.U }
        when(s.mode === 3.U || s.mode === 4.U) { n.mode := Mux(s.programmed, 2.U, 0.U) }
      }
      is(ControlKind.Halt.U) { n.mode := 4.U }
      is(ControlKind.Host.U) {
        when(f.overflow || length === 0.U || f.length =/= length) { n.lastError := 1.U }
          .elsewhen(op === 0.U) { n.selector := Cat(f.bytes(1), f.bytes(2), f.bytes(3)) }
          .elsewhen(c.cpuResetActive || ((s.bootSession || s.persistPending) && ((op >= 1.U && op <= 6.U) || op === 9.U || op === 10.U)) || ((c.programBusy || s.loaderPending) && op >= 1.U && op <= 6.U)) {
            n.lastError := 3.U
          }.otherwise {
            n.lastError := 0.U
            switch(op) {
              is(7.U) {
                // Keep the candidate data separate from its effect-enable bit.
                r.period := parameter(0)
                when(validPeriod(parameter(0))) { r.periodUpdate := true.B }
                  .otherwise { n.lastError := 4.U }
              }
              is(8.U) { r.hostWake := true.B }
              is(9.U) {
                when(!p.spiBoot.B) { n.lastError := 5.U }
                  .elsewhen(s.locked) { n.lastError := 2.U }
                  .otherwise { n.loaderHold := true.B }
              }
              is(10.U) {
                when(!p.spiBoot.B) { n.lastError := 5.U }
                  .elsewhen(!canProgram) { n.lastError := Mux(s.locked,2.U,3.U) }
                  .elsewhen(!s.programmed) { n.lastError := 6.U }
                  .otherwise { n.persistPending := true.B; n.persisted := false.B }
              }
              is(1.U) {
                when(!canProgram) { n.lastError := Mux(s.locked, 2.U, 3.U) }
                  .elsewhen(parameter(0) === 0.U || parameter(0) > config.programBytes.U || parameter(0)(1,0) =/= 0.U ||
                    parameter(1) >= parameter(0) || parameter(1)(1,0) =/= 0.U) { n.lastError := 4.U }
                  .elsewhen(parameter(3) =/= "h00010000".U || parameter(4) > config.workingRamBytes.U ||
                    (parameter(5) & ~gpioMask).orR || parameter(6) > config.measurements.size.U) { n.lastError := 5.U }
                  .otherwise {
                    n.mode := 1.U; n.programmed := false.B; n.persisted := false.B; n.received := 0.U; n.crc := "hffffffff".U
                    n.imageLength := parameter(0); n.entry := parameter(1)
                    n.expectedCrc := parameter(2); n.imageId := parameter(7)
                  }
              }
              is(2.U) {
                when(!canProgram) { n.lastError := Mux(s.locked, 2.U, 3.U) }
                  .elsewhen(s.mode =/= 1.U) { n.lastError := 6.U }
                  .elsewhen(parameter(0) =/= s.received || s.received >= s.imageLength) { n.lastError := 4.U }
                  .otherwise { n.loaderPending := true.B; n.loaderWord := parameter(1); r.programWrite := true.B }
              }
              is(3.U) {
                when(!canProgram || s.mode =/= 1.U) { n.lastError := Mux(s.locked, 2.U, 6.U) }
                  .elsewhen(s.received =/= s.imageLength) { n.lastError := 7.U }
                  .elsewhen((~s.crc).asUInt =/= s.expectedCrc) { n.lastError := 8.U }
                  .otherwise { n.programmed := true.B; n.mode := 2.U }
              }
              is(4.U, 5.U, 6.U) {
                when(!s.programmed || (s.started && op =/= 4.U)) { n.lastError := 6.U }
                  .otherwise {
                    when(op === 4.U || op === 6.U) { n.locked := true.B }
                    when(op === 5.U || op === 6.U) { n.started := true.B; n.mode := 3.U; n.loaderHold := false.B }
                  }
              }
            }
          }
      }
      is(ControlKind.Mmio.U, ControlKind.MmioCommit.U) {
        val q = c.memory
        r.memory.error := true.B
        when(!c.cpuResetActive && q.address >= MemoryMap.mmio.U && q.address < (MemoryMap.mmio + MemoryMap.mmioBytes).U &&
            q.address(1,0) === 0.U && q.mask === 15.U) {
          val offset = q.address(6,0)
          when(q.operation === Operation.Read.U) {
            r.memory.error := false.B; r.memory.data := c.peripheralData
            switch(offset) {
              is(0.U) { r.memory.data := s.entry.pad(32) + MemoryMap.program.U(32.W); r.memory.error := !s.started }
              is(76.U,80.U) { r.memory.data := Cat(0.U(8.W), s.mode, 0.U(1.W), s.bootIndex,
                s.lastError, s.persisted, s.persistPending, s.loaderHold, c.programBusy || s.loaderPending, s.bootSession, s.started, s.locked, s.programmed) }
              is(96.U) { r.memory.data := s.imageLength }
              is(100.U) { r.memory.data := s.entry }
              is(104.U) { r.memory.data := s.expectedCrc }
              is(108.U) { r.memory.data := "h00010000".U }
              is(112.U) { r.memory.data := config.workingRamBytes.U }
              is(116.U) { r.memory.data := gpioMask }
              is(120.U) { r.memory.data := config.measurements.size.U }
              is(124.U) { r.memory.data := s.imageId }
              is(36.U) { r.memory.data := s.sampleIndex }
              is(40.U) { r.memory.data := s.sampleValue }
              is(48.U) { r.memory.data := s.appIndex }
              is(52.U) { r.memory.error := !appExists(s.appIndex) }
            }
          }.elsewhen(q.operation === Operation.Write.U) {
            switch(offset) {
              // Command errors are reported in loader status, allowing ROM to
              // fall back without trapping on a malformed external image.
              is(88.U) { r.memory.error := !p.spiBoot.B || q.data > 1.U || (q.data === 0.U && !c.peripheralData(2)) }
              is(80.U, 84.U) { r.memory.error := false.B }
              is(8.U, 12.U, 24.U, 28.U, 40.U) { r.memory.error := false.B }
              is(32.U) { r.memory.error := q.data =/= "h57444f47".U }
              is(36.U) { r.memory.error := q.data >= config.measurements.size.U }
              is(44.U) { r.memory.error := s.sampleIndex >= config.measurements.size.U || (p.adc.nonEmpty.B && s.sampleIndex === 0.U) }
              is(48.U) { r.memory.error := !appExists(q.data) }
              is(52.U) { r.memory.error := !c.applicationWritable }
              is(56.U) { r.memory.error := (q.data & "hffffffc0".U) =/= 0.U }
              is(60.U) { r.memory.error := !p.lowPower.nonEmpty.B || q.data > p.lowPower.map(_.maximumSleepMs).getOrElse(0).U }
              is(64.U) { r.memory.error := !validPeriod(q.data) }
            }
            when(!r.memory.error && c.kind === ControlKind.MmioCommit.U) {
              switch(offset) {
                is(80.U) {
                  n.lastError := 0.U
                  when(q.data === 3.U) {
                    when(!s.programmed || s.bootSession || s.loaderHold || s.persistPending || c.programBusy || s.loaderPending) { n.lastError := 6.U }
                      .otherwise { n.started := true.B; n.mode := 3.U; n.loaderHold := false.B }
                  }.elsewhen((q.data === 6.U || q.data === 7.U) && s.persistPending && !s.locked) {
                    n.persistPending := false.B; n.persisted := q.data === 6.U
                    when(q.data === 7.U) { n.lastError := 9.U }
                  }.elsewhen(!canProgram || s.persistPending) { n.lastError := Mux(s.locked, 2.U, 3.U) }
                    .elsewhen(q.data === 1.U) {
                      when(s.mode === 1.U && !s.bootSession) { n.lastError := 3.U }
                        .otherwise {
                          // BEGIN_OPEN explicitly destroys the old validity
                          // before any header field can replace its metadata.
                          n.programmed := false.B; n.persisted := false.B; n.mode := 1.U; n.bootSession := true.B; n.bootIndex := 0.U
                          n.received := 0.U; n.imageLength := 0.U; n.entry := 0.U; n.crc := "hffffffff".U
                        }
                    }.elsewhen(q.data === 2.U) {
                      when(!s.bootSession || s.bootIndex =/= 8.U) { n.lastError := 6.U }
                        .elsewhen(s.received =/= s.imageLength) { n.lastError := 7.U }
                        .elsewhen((~s.crc).asUInt =/= s.expectedCrc) { n.lastError := 8.U }
                        .otherwise { n.programmed := true.B; n.mode := 2.U; n.bootSession := false.B }
                    }.elsewhen(q.data === 4.U && s.bootSession) {
                      n.bootSession := false.B; n.bootIndex := 0.U; n.mode := 0.U
                    }.otherwise { n.lastError := 6.U }
                }
                is(84.U) {
                  n.lastError := 0.U
                  when(!canProgram || !s.bootSession) { n.lastError := Mux(s.locked, 2.U, 3.U) }
                    .elsewhen(s.bootIndex === 8.U) {
                      when(s.received >= s.imageLength) { n.lastError := 4.U }
                        .otherwise { n.loaderPending := true.B; n.loaderWord := q.data; r.programWrite := true.B }
                    }.otherwise {
                      val invalid = WireDefault(false.B)
                      val incompatible = WireDefault(false.B)
                      switch(s.bootIndex) {
                        is(0.U) { invalid := q.data === 0.U || q.data > config.programBytes.U || q.data(1,0) =/= 0.U
                          when(!invalid) { n.imageLength := q.data } }
                        is(1.U) { invalid := q.data >= s.imageLength || q.data(1,0) =/= 0.U
                          when(!invalid) { n.entry := q.data } }
                        is(2.U) { n.expectedCrc := q.data }
                        is(3.U) { incompatible := q.data =/= "h00010000".U }
                        is(4.U) { incompatible := q.data > config.workingRamBytes.U }
                        is(5.U) { incompatible := (q.data & ~gpioMask).orR }
                        is(6.U) { incompatible := q.data > config.measurements.size.U }
                        is(7.U) { n.imageId := q.data }
                      }
                      when(invalid || incompatible) {
                        n.lastError := Mux(incompatible, 5.U, 4.U); n.bootSession := false.B; n.mode := 0.U
                      }.otherwise { n.bootIndex := s.bootIndex + 1.U }
                    }
                }
                is(36.U) { n.sampleIndex := q.data }
                is(40.U) { n.sampleValue := q.data }
                is(48.U) { n.appIndex := q.data }
              }
            }
          }
        }
      }
    }
    r
  }
}
