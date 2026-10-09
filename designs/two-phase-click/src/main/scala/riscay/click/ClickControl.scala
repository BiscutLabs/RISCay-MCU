// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ClickTiming
import chiselasync.protocol.TwoPhase
import riscay._
import riscay.soc._

/** POR-owned native state token. Application reset is a serialized command;
  * accepted SRAM completion is accounted independently of application lifetime.
  * Peripheral commits route through explicit endpoint boundaries.
  */
class ClickControl(p: SocParameters, domain: ResetDomain) extends AsyncModule(domain) {
  val command = twoPhaseInput("command", new ControlCommand)
  val reply = twoPhaseOutput("reply", new ControlReply)
  val start = IO(Input(Bool()))
  private val timing = ClickTiming.Simulation
  private val state = asyncChild("state")(d => new PhaseDecoupledClickBuffer(new ControlState,
    timing, Some(ControlState.initial), d))
  private val join = asyncChild("join")(d => new ClickJoin(new ControlState, new ControlCommand, timing, d))
  private val update = asyncChild("update")(d => new ClickStage(new Joined(new ControlState, new ControlCommand),
    new ControlReply, (x: Joined[ControlState, ControlCommand]) => transition(x.left, x.right), timing, d))
  private val fork = asyncChild("fork")(d => new ClickFork(new ControlReply, d))
  // The registered fork contract describes its complete payload on both branches.
  // Retain the fields that the state feedback branch does not consume.
  dontTouch(fork.left)
  state.start.get := start
  TwoPhase.connect(join.left, state.out); TwoPhase.connect(join.right, command)
  TwoPhase.connect(update.in, join.out); TwoPhase.connect(fork.in, update.out)
  state.in.bits := fork.left.bits.state; state.in.req := fork.left.req; fork.left.ack := state.in.ack
  TwoPhase.connect(reply, fork.right)
  contract.endpoint("start", start)

  private def transition(s: ControlState, c: ControlCommand): ControlReply = {
    val r = WireDefault(0.U.asTypeOf(new ControlReply)); r.kind := c.kind; r.state := s
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
      3.U -> 1.U, 4.U -> 1.U, 5.U -> 1.U, 6.U -> 1.U, 7.U -> 5.U, 8.U -> 1.U))
    switch(c.kind) {
      is(ControlKind.Stored.U) {
        when(s.loaderPending) {
          n.received := s.received + 4.U; n.crc := ImageCrc.word(s.crc, s.loaderWord); n.loaderPending := false.B
        }
      }
      is(ControlKind.ResetApplication.U) {
        n.started := false.B; n.appIndex := 0.U
        when(s.mode === 3.U || s.mode === 4.U) { n.mode := Mux(s.programmed, 2.U, 0.U) }
      }
      is(ControlKind.Halt.U) { n.mode := 4.U }
      is(ControlKind.Host.U) {
        when(f.overflow || length === 0.U || f.length =/= length) { n.lastError := 1.U }
          .elsewhen(op === 0.U) { n.selector := Cat(f.bytes(1), f.bytes(2), f.bytes(3)) }
          .elsewhen(c.cpuResetActive || ((c.programBusy || s.loaderPending) && op >= 1.U && op <= 6.U)) {
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
              is(1.U) {
                when(!canProgram) { n.lastError := Mux(s.locked, 2.U, 3.U) }
                  .elsewhen(parameter(0) === 0.U || parameter(0) > config.programBytes.U || parameter(0)(1,0) =/= 0.U ||
                    parameter(1) >= parameter(0) || parameter(1)(1,0) =/= 0.U) { n.lastError := 4.U }
                  .elsewhen(parameter(3) =/= "h00010000".U || parameter(4) > config.workingRamBytes.U ||
                    (parameter(5) & ~gpioMask).orR || parameter(6) > config.measurements.size.U) { n.lastError := 5.U }
                  .otherwise {
                    n.mode := 1.U; n.programmed := false.B; n.received := 0.U; n.crc := "hffffffff".U
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
                    when(op === 5.U || op === 6.U) { n.started := true.B; n.mode := 3.U }
                  }
              }
            }
          }
      }
      is(ControlKind.Mmio.U, ControlKind.MmioCommit.U) {
        val q = c.memory
        r.memory.error := true.B
        when(!c.cpuResetActive && q.address >= MemoryMap.mmio.U && q.address < (MemoryMap.mmio + 76).U &&
            q.address(1,0) === 0.U && q.mask === 15.U) {
          val offset = q.address(6,0)
          when(q.operation === Operation.Read.U) {
            r.memory.error := false.B; r.memory.data := c.peripheralData
            switch(offset) {
              is(0.U) { r.memory.data := s.entry + MemoryMap.program.U; r.memory.error := !s.started }
              is(36.U) { r.memory.data := s.sampleIndex }
              is(40.U) { r.memory.data := s.sampleValue }
              is(48.U) { r.memory.data := s.appIndex }
              is(52.U) { r.memory.error := !appExists(s.appIndex) }
            }
          }.elsewhen(q.operation === Operation.Write.U) {
            switch(offset) {
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
