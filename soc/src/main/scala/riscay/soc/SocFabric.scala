// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance
import riscay._

object MemoryMap {
  val program = 0x10000000L
  val ram = 0x20000000L
  val mmio = 0x30000000L
  // lui x1,0x30000; lw x2,0(x1) (wait for START); jalr x0,x2,0
  val boot = Vector(0x300000b7L, 0x0000a103L, 0x00010067L)
}
object ImageCrc {
  // CRC-32/ISO-HDLC, init ffffffff, reflected 04c11db7, xorout ffffffff.
  def word(previous: UInt, data: UInt): UInt = {
    var result = previous
    for (i <- 0 until 32) {
      result = (result >> 1) ^ Mux(result(0) ^ data(i), "hedb88320".U(32.W), 0.U(32.W))
    }
    result
  }
}

/** Identical on-chip storage and peripherals for both asynchronous CPUs.
  * Every side effect commits on one service-clock edge. RAM has no reset clear;
  * image validity gates execution, and software initializes working RAM.
  */
class SocFabric(p: SocParameters, boardFactory: SocParameters => BoardController) extends Module with InlineInstance {
  val io = IO(new Bundle {
    val request = Flipped(Decoupled(new MemoryRequest))
    val response = Decoupled(new MemoryResponse)
    val scl = Input(Bool()); val sda = Input(Bool()); val sdaLow = Output(Bool())
    val gpioIn = Input(UInt(32.W)); val gpioOut = Output(UInt(32.W)); val gpioOe = Output(UInt(32.W))
    val adcMiso = Input(Bool()); val adcCsN = Output(Bool()); val adcSclk = Output(Bool())
    val watchdogReason = Input(Bool()); val heartbeat = Output(Bool())
    val watchdogAck = Input(Bool())
    val mode = Output(UInt(3.W)); val programmed = Output(Bool()); val locked = Output(Bool())
    val now = Output(UInt(32.W))
    val commit = Valid(new MemoryRequest)
  })
  val config = p.config
  val program = Reg(Vec(config.programBytes / 4, UInt(32.W)))
  val ram = Reg(Vec(config.workingRamBytes / 4, Vec(4, UInt(8.W))))
  val rom = VecInit(MemoryMap.boot.map(_.U(32.W)))
  val mode = RegInit(0.U(3.W))
  val programmed = RegInit(false.B); val locked = RegInit(false.B); val started = RegInit(false.B)
  val lastError = RegInit(0.U(8.W))
  val imageLength = RegInit(0.U(32.W)); val entry = RegInit(0.U(32.W))
  val imageId = RegInit(0.U(32.W)); val expectedCrc = RegInit(0.U(32.W))
  val received = RegInit(0.U(32.W)); val crc = RegInit("hffffffff".U(32.W))
  io.mode := mode; io.programmed := programmed; io.locked := locked
  val canProgram = !locked && !started

  val divider = RegInit(0.U(log2Ceil(p.serviceHz / 1000).max(1).W))
  val tick = divider === (p.serviceHz / 1000 - 1).U
  divider := Mux(tick, 0.U, divider + 1.U)
  val now = RegInit(0.U(32.W)); when(tick) { now := now + 1.U }; io.now := now
  val heartbeat = RegInit(false.B); io.heartbeat := heartbeat
  val ack0 = RegNext(io.watchdogAck, false.B); val ack = RegNext(ack0, false.B)
  val kick = WireDefault(false.B)
  when(((tick && !started) || kick) && ack === heartbeat) { heartbeat := !heartbeat }
  val gpioSync0 = RegNext(io.gpioIn, 0.U); val gpio = RegNext(gpioSync0, 0.U)
  val gpioPrevious = RegNext(gpio, 0.U)
  val output = RegInit(config.application.pins.filter(_.resetHigh).map(x => BigInt(1) << x.index).sum.U(32.W))
  val enable = RegInit(config.application.pins.filter(_.output).map(x => BigInt(1) << x.index).sum.U(32.W))
  val gpioMask = ((BigInt(1) << config.gpioCount) - 1).U(32.W)
  val application = RegInit(VecInit(Seq.fill(64)(0.U(32.W))))
  val appIndex = RegInit(0.U(6.W))

  val samples = RegInit(0.U.asTypeOf(Vec(config.measurements.size, new Sample)))
  // Separate reset flag avoids requiring a Bundle literal for the whole vector.
  val sampled = RegInit(0.U.asTypeOf(Vec(config.measurements.size, Bool())))
  val publish = Wire(Vec(config.measurements.size, Valid(new Acquisition)))
  publish.foreach { x => x.valid := false.B; x.bits := 0.U.asTypeOf(new Acquisition) }
  val sampleIndex = RegInit(0.U(4.W)); val sampleValue = RegInit(0.U(32.W))
  io.adcCsN := true.B; io.adcSclk := false.B
  p.adc.foreach { adcParameters =>
    val adc = Module(new SpiAdc(adcParameters)); adc.io.miso := io.adcMiso
    io.adcCsN := adc.io.csN; io.adcSclk := adc.io.sclk
    publish(0) := adc.io.result
  }
  for(i <- config.measurements.indices) {
    samples(i).never := !sampled(i)
    when(tick && samples(i).age =/= "hffffffff".U) { samples(i).age := samples(i).age + 1.U }
    when(publish(i).valid) {
      samples(i).sequence := samples(i).sequence + 1.U
      samples(i).valid := publish(i).bits.valid
      samples(i).fault := !publish(i).bits.valid
      samples(i).calibrated := publish(i).bits.calibrated && publish(i).bits.valid
      when(publish(i).bits.valid) {
        samples(i).value := publish(i).bits.value; samples(i).age := 0.U; sampled(i) := true.B
      }
    }
  }
  val board = Module(boardFactory(p))
  board.io.tick := tick; board.io.now := now; board.io.gpio := gpio; board.io.samples := samples
  io.gpioOut := ((output & ~board.io.mask) | (board.io.outputs & board.io.mask)) & gpioMask
  io.gpioOe := ((enable & ~board.io.mask) | (board.io.enables & board.io.mask)) & gpioMask

  val deadline = RegInit(0.U(32.W)); val armed = RegInit(false.B)
  val pending = RegInit(0.U(32.W)); val clear = WireDefault(0.U(32.W))
  val due = armed && (now - deadline).asSInt >= 0.S
  val acquisition = if(config.measurements.isEmpty) false.B else publish.map(_.valid).reduce(_ || _)
  val events = Cat(0.U(28.W), acquisition, ((gpio ^ gpioPrevious) & gpioMask).orR, due, tick)
  pending := (pending & ~clear) | events // New events win an acknowledge race.
  when(due) { armed := false.B }

  val responseValid = RegInit(false.B); val response = Reg(new MemoryResponse)
  io.response.valid := responseValid; io.response.bits := response
  when(io.response.fire) { responseValid := false.B }
  val req = io.request.bits
  val isRead = req.operation === Operation.Read.U
  val isWrite = req.operation === Operation.Write.U
  val isFetch = req.operation === Operation.Fetch.U
  val bootWait = isRead && req.address === MemoryMap.mmio.U && !started
  val eventWait = isRead && req.address === (MemoryMap.mmio + 16).U && pending === 0.U
  io.request.ready := !responseValid && !bootWait && !eventWait
  io.commit.valid := io.request.fire; io.commit.bits := req
  when(io.request.fire) {
    responseValid := req.operation =/= Operation.Halt.U
    response.data := 0.U; response.error := true.B
    when(req.operation === Operation.Halt.U) { mode := 4.U }
      .elsewhen(req.address < (MemoryMap.boot.size * 4).U && !isWrite) {
        response.data := rom(req.address(3, 2)); response.error := false.B
      }.elsewhen(req.address >= MemoryMap.program.U && req.address < (MemoryMap.program + config.programBytes).U) {
        when(!isWrite && programmed && (req.address - MemoryMap.program.U) < imageLength) {
          response.data := program((req.address - MemoryMap.program.U)(log2Ceil(config.programBytes).max(3)-1, 2)); response.error := false.B
        }
      }.elsewhen(req.address >= MemoryMap.ram.U && req.address < (MemoryMap.ram + config.workingRamBytes).U && !isFetch) {
        val index = (req.address - MemoryMap.ram.U)(log2Ceil(config.workingRamBytes).max(3)-1, 2)
        response.data := Mux(isWrite, 0.U, ram(index).asUInt); response.error := false.B
        when(isWrite) { for(i <- 0 until 4) { when(req.mask(i)) { ram(index)(i) := req.data(8*i+7, 8*i) } } }
      }.elsewhen(!isFetch && req.address >= MemoryMap.mmio.U && req.address < (MemoryMap.mmio + 56).U && req.address(1,0) === 0.U && req.mask === 15.U) {
        val offset = req.address(5, 0)
        when(isRead) {
          response.error := false.B
          switch(offset) {
            is(0.U) { response.data := entry + MemoryMap.program.U }
            is(4.U) { response.data := now }
            is(8.U) { response.data := deadline }
            is(12.U, 16.U) { response.data := pending }
            is(20.U) { response.data := gpio & gpioMask }
            is(24.U) { response.data := io.gpioOut }
            is(28.U) { response.data := io.gpioOe }
            is(32.U) { response.data := 0.U }
            is(36.U) { response.data := sampleIndex }
            is(40.U) { response.data := sampleValue }
            is(44.U) { response.data := 0.U }
            is(48.U) { response.data := appIndex }
            is(52.U) { response.data := Mux(board.io.registerMask(appIndex), board.io.registers(appIndex), application(appIndex)) }
          }
        }.otherwise {
          switch(offset) {
            is(8.U) { deadline := req.data; armed := true.B; response.error := false.B }
            is(12.U) { clear := req.data; response.error := false.B }
            is(24.U) { output := req.data; response.error := false.B }
            is(28.U) { enable := req.data; response.error := false.B }
            is(32.U) { when(req.data === "h57444f47".U) { kick := true.B; response.error := false.B } }
            is(36.U) { when(req.data < config.measurements.size.U) { sampleIndex := req.data; response.error := false.B } }
            is(40.U) { sampleValue := req.data; response.error := false.B }
            is(44.U) {
              for(i <- config.measurements.indices if !(i == 0 && p.adc.nonEmpty)) {
                when(sampleIndex === i.U) {
                  publish(i).valid := true.B; publish(i).bits.value := sampleValue
                  publish(i).bits.valid := req.data(0); publish(i).bits.calibrated := req.data(1)
                  response.error := false.B
                }
              }
            }
            is(48.U) { when(req.data < 64.U) { appIndex := req.data; response.error := false.B } }
            is(52.U) { when(!board.io.registerMask(appIndex)) { application(appIndex) := req.data; response.error := false.B } }
          }
        }
      }
  }

  val host = Module(new I2cTarget(p.i2cAddress))
  host.io.scl := io.scl; host.io.sda := io.sda; io.sdaLow := host.io.pullLow
  val selector = RegInit(0.U(24.W))
  val frame = host.io.frame.bits
  def parameter(index: Int): UInt = Cat((0 until 4).reverse.map(i => frame.bytes(1 + index * 4 + i)))
  val opcode = frame.bytes(0)
  val desiredLength = MuxLookup(opcode, 0.U)(Seq(0.U -> 4.U, 1.U -> 33.U, 2.U -> 9.U,
    3.U -> 1.U, 4.U -> 1.U, 5.U -> 1.U, 6.U -> 1.U))
  when(host.io.frame.valid) {
    when(frame.overflow || desiredLength === 0.U || frame.length =/= desiredLength) { lastError := 1.U }
      .elsewhen(opcode === 0.U) { selector := Cat(frame.bytes(1), frame.bytes(2), frame.bytes(3)) }
      .otherwise {
        lastError := 0.U
        switch(opcode) {
          is(1.U) {
            when(!canProgram) { lastError := Mux(locked, 2.U, 3.U) }
              .elsewhen(parameter(0) === 0.U || parameter(0) > config.programBytes.U || parameter(0)(1,0) =/= 0.U ||
                parameter(1) >= parameter(0) || parameter(1)(1,0) =/= 0.U) { lastError := 4.U }
              .elsewhen(parameter(3) =/= "h00010000".U || parameter(4) > config.workingRamBytes.U ||
                (parameter(5) & ~gpioMask).orR || parameter(6) > config.measurements.size.U) { lastError := 5.U }
              .otherwise {
                mode := 1.U; programmed := false.B; received := 0.U; crc := "hffffffff".U
                imageLength := parameter(0); entry := parameter(1); expectedCrc := parameter(2); imageId := parameter(7)
              }
          }
          is(2.U) {
            when(!canProgram) { lastError := Mux(locked, 2.U, 3.U) }
              .elsewhen(mode =/= 1.U) { lastError := 6.U }
              .elsewhen(parameter(0) =/= received || received >= imageLength) { lastError := 4.U }
              .otherwise {
                program(received(log2Ceil(config.programBytes).max(3)-1, 2)) := parameter(1); received := received + 4.U
                crc := ImageCrc.word(crc, parameter(1))
              }
          }
          is(3.U) {
            when(!canProgram || mode =/= 1.U) { lastError := Mux(locked, 2.U, 6.U) }
              .elsewhen(received =/= imageLength) { lastError := 7.U }
              .elsewhen((~crc).asUInt =/= expectedCrc) { lastError := 8.U }
              .otherwise { programmed := true.B; mode := 2.U }
          }
          is(4.U, 5.U, 6.U) {
            when(!programmed || (started && opcode =/= 4.U)) { lastError := 6.U }
              .otherwise {
                when(opcode === 4.U || opcode === 6.U) { locked := true.B }
                when(opcode === 5.U || opcode === 6.U) { started := true.B; mode := 3.U }
              }
          }
        }
      }
  }

  def hostWord(space: UInt, instance: UInt, word: UInt): UInt = {
    val result = WireDefault("hffffffff".U(32.W))
    when(space === 0.U && instance === 0.U) {
      val fields = Seq("h00010000".U, config.application.id.U, config.application.version.U,
        config.programBytes.U, config.workingRamBytes.U, config.gpioCount.U,
        config.measurements.size.U, Mux(io.watchdogReason, 2.U, 1.U))
      fields.zipWithIndex.foreach { case (value, i) => when(word === i.U) { result := value } }
    }
    when(space === 1.U && instance === 0.U) {
      val fields = Seq(mode, programmed.asUInt, locked.asUInt, canProgram.asUInt, 0.U, lastError,
        imageId, received)
      fields.zipWithIndex.foreach { case (value, i) => when(word === i.U) { result := value } }
    }
    for(i <- config.measurements.indices) {
      when(space === 2.U && instance === i.U) {
        val s = samples(i)
        val stale = s.age >= p.staleMs.U
        val flags = Cat(0.U(27.W), s.calibrated, s.fault, !sampled(i), stale, s.valid && sampled(i) && !stale)
        val fields = Seq(s.value, flags, Mux(sampled(i), s.age, "hffffffff".U), s.sequence,
          config.measurements(i).unit.U, config.measurements(i).scale10.S(32.W).asUInt)
        fields.zipWithIndex.foreach { case (value, j) => when(word === j.U) { result := value } }
      }
    }
    when(space === 128.U && instance === 0.U) {
      for(register <- config.application.registers) {
        when(word === register.word.U) { result := Mux(board.io.registerMask(register.word), board.io.registers(register.word), application(register.word)) }
      }
    }
    result
  }
  val supported = (0 until 8).map { i =>
    val space = selector(23,16); val instance = selector(15,8); val word = selector(7,0) +& i.U
    val appWord = config.application.registers.map(r => word === r.word.U).foldLeft(false.B)(_ || _)
    (instance === 0.U && (space === 0.U || space === 1.U) && word < 8.U) ||
      (space === 2.U && instance < config.measurements.size.U && word < 6.U) ||
      (space === 128.U && instance === 0.U && appWord)
  }
  host.io.snapshot := Cat(0.U(24.W), Cat(supported.reverse),
    Cat((0 until 8).reverse.map(i => hostWord(selector(23,16), selector(15,8), selector(7,0) +& i.U))))
}
