// SPDX-License-Identifier: Apache-2.0
package riscay.desync

import chisel3._
import chisel3.util._
import riscay._
import riscay.soc._

/** Single fast-clock service island. Host, CPU and memory completion are
  * arbitrated on this edge. All retained state has POR lifetime; application
  * cancellation is synchronous and never resets an accepted SRAM write.
  */
class ClockedFabric(p: SocParameters) extends Module {
  val io=IO(new Bundle {
    val frontClock=Input(Clock())
    val request=Flipped(Decoupled(new MemoryRequest));val response=Decoupled(new MemoryResponse)
    val scl=Input(Bool());val sda=Input(Bool());val sdaLow=Output(Bool())
    val gpioIn=Input(UInt(32.W));val gpioOut=Output(UInt(32.W));val gpioOe=Output(UInt(32.W))
    val adcMiso=Input(Bool());val adcCsN=Output(Bool());val adcSclk=Output(Bool())
    val applicationCancel=Input(Bool());val resetComplete=Output(Bool())
    val watchdogReason=Input(Bool());val watchdogAck=Input(Bool());val heartbeat=Output(Bool())
    val crashCount=Input(UInt(32.W));val sleepEntries=Input(UInt(32.W));val clockRunning=Input(Bool())
    val timeGray=Input(UInt(32.W));val consumedGray=Output(UInt(32.W))
    val mode=Output(UInt(3.W));val programmed=Output(Bool());val locked=Output(Bool())
    val canSleep=Output(Bool());val activity=Output(Bool());val observedGpio=Output(UInt(32.W))
    val hostSelected=Output(Bool());val hostRejected=Output(Bool())
    val spiClaimed=Output(Bool());val adcBusy=Output(Bool())
    val commit=Valid(new MemoryRequest)
  })
  val config=p.config
  private val applicationResets=scala.collection.mutable.ArrayBuffer.empty[() => Unit]
  private def applicationReg[T <: Data](init: T): T = {
    val q=RegInit(init);applicationResets+=(() => q:=init);q
  }
  val control=Module(new ClockedControl(p))
  val controlState=control.state
  val command=WireDefault(0.U.asTypeOf(new ControlCommand))
  control.command:=command;control.valid:=false.B
  val program=Module(new ClockedSram(config.programBytes)).suggestName("programSram")
  val ram=Module(new ClockedSram(config.workingRamBytes))
  for(m <- Seq(program,ram)) {
    m.io.request.valid:=false.B;m.io.request.bits:=0.U.asTypeOf(new SramWordRequest)
    m.io.response.ready:=true.B
  }
  // Pin sampling stays on the ungated service edge, so START is recognized
  // even when SCL rose before the work clock woke. An entire address byte
  // precedes any snapshot/frame commit, allowing the gate to open without a
  // mailbox or payload copy. Both clocks have the same parent/phase.
  val host=withClock(io.frontClock) {Module(new ClockedI2cTarget(p.i2cAddress,p.i2cIdleCycles))}
  withClock(io.frontClock) {
    when(host.io.frame.valid || host.io.readStart) {
      assert(io.clockRunning,"CLOCKED_HOST_COMMIT_WITH_GATE_CLOSED")
    }
  }
  host.io.scl:=io.scl;host.io.sda:=io.sda;host.io.applicationCancel:=io.applicationCancel
  io.sdaLow:=host.io.pullLow;io.hostSelected:=host.io.selected;io.hostRejected:=host.io.rejected
  val resetNeeded=RegInit(true.B)
  val cpuMemoryPending=applicationReg(false.B)
  val responseValid=applicationReg(false.B);val response=Reg(new MemoryResponse)
  io.response.valid:=responseValid && !io.applicationCancel;io.response.bits:=response
  when(io.response.fire) {responseValid:=false.B}
  val loaderPending=controlState.loaderPending
  val memoryBusy=program.io.busy || ram.io.busy || loaderPending
  val programmed=controlState.programmed;val locked=controlState.locked;val started=controlState.started
  val mode=Mux(io.applicationCancel && (controlState.mode===3.U || controlState.mode===4.U),
    Mux(programmed,2.U,0.U),controlState.mode)
  io.mode:=mode;io.programmed:=programmed;io.locked:=locked
  val canProgram= !locked && !started && !controlState.bootSession && !controlState.persistPending &&
    !io.applicationCancel && !program.io.busy && !loaderPending
  io.resetComplete:= !resetNeeded && !io.applicationCancel
  val selector=controlState.selector;val appIndex=controlState.appIndex
  val sampleIndex=controlState.sampleIndex;val sampleValue=controlState.sampleValue

  val housekeeping=Module(new ClockedHousekeeping(p))
  val h=WireDefault(0.U.asTypeOf(new HousekeepingCommand));housekeeping.command:=h
  val timing=housekeeping.state;val effects=housekeeping.result
  val elapsed=WireDefault(0.U(64.W));val upperElapsed=WireDefault(0.U(64.W))
  val scalingBusy=WireDefault(false.B)
  if(p.lowPower.nonEmpty) {
    val lp=p.lowPower.get
    val scaler=Module(new ClockedElapsedTicks(Seq(lp.tickMicros,lp.minimumTickMicros,lp.maximumTickMicros)))
    scaler.io.target:=Cat((0 until 32).reverse.map(i => io.timeGray(31,i).xorR))
    elapsed:=scaler.io.elapsed(0);upperElapsed:=scaler.io.elapsed(2)
    h.timeValid:=scaler.io.valid;h.target:=scaler.io.publicationTarget
    io.consumedGray:=scaler.io.consumed ^ (scaler.io.consumed >> 1)
    scalingBusy:=scaler.io.busy
  } else {
    val divider=RegInit(0.U(log2Ceil(p.serviceHz/1000).max(1).W))
    val pulse=divider===(p.serviceHz/1000-1).U
    divider:=Mux(pulse,0.U,divider+1.U)
    elapsed:=Mux(pulse,1.U,0.U);upperElapsed:=elapsed;h.timeValid:=pulse
    io.consumedGray:=0.U
  }
  h.elapsed:=elapsed(31,0);h.elapsedOverflow:=elapsed(63,32).orR
  h.resetApplication:=io.applicationCancel;h.started:=started
  val now=timing.now;val wakeMask=timing.wakeMask;val sleepRemaining=timing.lease
  val samplePeriod=timing.period;val periodPending=timing.periodPending
  val tick=elapsed.orR
  val upperTime=RegInit(0.U(SampleTime.Width.W))
  val upperSum=upperTime +& upperElapsed
  val upperTimeNext=Mux(upperSum > SampleTime.Maximum.U,SampleTime.Maximum.U,upperSum(SampleTime.Width-1,0))
  when(tick) {upperTime:=upperTimeNext}

  val gpioFirst=RegNext(io.gpioIn,0.U);val gpio=RegNext(gpioFirst,0.U)
  val gpioPrevious=RegNext(gpio,0.U);io.observedGpio:=gpio
  val gpioMask=((BigInt(1)<<config.gpioCount)-1).U(32.W)
  val output=if(p.retainGpioOnWatchdog) RegInit(0.U(config.gpioCount.max(1).W)) else applicationReg(0.U(config.gpioCount.max(1).W))
  val enable=if(p.retainGpioOnWatchdog) RegInit(0.U(config.gpioCount.max(1).W)) else applicationReg(0.U(config.gpioCount.max(1).W))
  if(p.spiBoot) {
    when(io.applicationCancel) {output:=output & "hffffffc7".U;enable:=enable & "hffffffc7".U}
  }
  val recoveryMask=Mux(io.applicationCancel,
    (if(!p.retainGpioOnWatchdog) 0.U else if(p.spiBoot) "hffffffc7".U else "hffffffff".U),"hffffffff".U)
  val gpioOutputView=output.pad(32) & gpioMask & recoveryMask
  val gpioEnableView=enable.pad(32) & gpioMask & recoveryMask
  io.gpioOut:=gpioOutputView;io.gpioOe:=gpioEnableView
  val application=config.application.registers.map(r => r.word -> applicationReg(0.U(32.W))).toMap
  def applicationWord(word: UInt): UInt=MuxLookup(word,"hffffffff".U(32.W))(
    application.toSeq.map {case(i,q) => i.U -> q})
  def applicationExists(word: UInt): Bool=application.keys.map(i => word===i.U).foldLeft(false.B)(_ || _)

  val spiClaimRequested=if(p.spiBoot) RegInit(true.B) else WireDefault(false.B)
  val spiClaimed=if(p.spiBoot) RegInit(true.B) else WireDefault(false.B)
  io.spiClaimed:=spiClaimed
  val adcBusy=WireDefault(false.B)
  val publish=Wire(Vec(config.measurements.size,Valid(new Acquisition)))
  publish.foreach {x => x.valid:=false.B;x.bits:=0.U.asTypeOf(new Acquisition)}
  io.adcCsN:=true.B;io.adcSclk:=false.B;h.adcBusy:=adcBusy || spiClaimRequested
  val adcTimestamp=Reg(UInt(SampleTime.Width.W))
  p.adc.foreach {a =>
    val adc=Module(new ClockedSpiAdc(a,autonomous=p.lowPower.isEmpty))
    adc.io.allow:= !spiClaimRequested
    when(adc.io.launched) {adcTimestamp:=Mux(tick,upperTimeNext,upperTime)}
    adc.io.miso:=io.adcMiso;adc.io.start:=effects.startAdc && !spiClaimRequested
    adcBusy:=adc.io.busy;h.discard:=adc.io.done && !adc.io.result.valid
    io.adcCsN:=adc.io.csN;io.adcSclk:=adc.io.sclk;publish(0):=adc.io.result
  }
  if(p.spiBoot) {
    when(spiClaimRequested && !adcBusy) {spiClaimed:=true.B}
    when(io.applicationCancel) {spiClaimRequested:=true.B}
    when(spiClaimed) {io.adcSclk:=io.gpioOut(3) && io.gpioOe(3)}
  }
  io.adcBusy:=adcBusy
  val samples=RegInit(0.U.asTypeOf(Vec(config.measurements.size,new SampleRecord)))
  val hostSamples=Wire(Vec(config.measurements.size,new Sample))
  for(i <- config.measurements.indices) {
    val q=samples(i)
    when(publish(i).valid) {
      q.sequence:=q.sequence+1.U;q.valid:=publish(i).bits.valid;q.fault:= !publish(i).bits.valid
      q.calibrated:=publish(i).bits.valid && publish(i).bits.calibrated
      when(publish(i).bits.valid) {
        q.value:=publish(i).bits.value;q.timestamp:=(if(p.adc.nonEmpty && i==0) adcTimestamp else Mux(tick,upperTimeNext,upperTime));q.seen:=true.B
      }
    }
    val delta=upperTime-q.timestamp
    val age=Mux(upperTime.andR || upperTime<q.timestamp || delta(SampleTime.Width-1,32).orR,"hffffffff".U,delta(31,0))
    hostSamples(i).value:=q.value;hostSamples(i).age:=age;hostSamples(i).sequence:=q.sequence
    hostSamples(i).valid:=q.valid;hostSamples(i).calibrated:=q.calibrated
    hostSamples(i).never:= !q.seen;hostSamples(i).fault:=q.fault
  }

  val pending=applicationReg(0.U(6.W));val clear=WireDefault(0.U(6.W))
  val replaceDeadline=WireDefault(false.B)
  val hostWake=control.valid && control.result.hostWake
  val gpioActivity=((gpio ^ gpioPrevious) & p.gpioEventMask.U(32.W)).orR
  val acquisition=publish.map(_.valid).foldLeft(false.B)(_ || _)
  val events=WireDefault(Cat(hostWake,effects.leaseExpired,acquisition,gpioActivity,effects.due,tick))
  pending:=(pending & ~(clear | Mux(replaceDeadline,2.U,0.U))) | events
  val mmioEvents=applicationReg(0.U(6.W));val mmioObserved=applicationReg(false.B)
  val req=io.request.bits
  val mmio=req.address>=MemoryMap.mmio.U && req.address<(MemoryMap.mmio+MemoryMap.mmioBytes).U
  when(io.request.valid && mmio && req.operation=/=Operation.Halt.U) {
    mmioEvents:=Mux(mmioObserved,mmioEvents,0.U) | events;mmioObserved:=true.B
  }
  when(!io.request.valid || io.request.fire) {mmioObserved:=false.B}
  val isRead=req.operation===Operation.Read.U;val isWrite=req.operation===Operation.Write.U
  val isFetch=req.operation===Operation.Fetch.U
  val fullWord=req.address(1,0)===0.U && req.mask===15.U
  val bootWait=isRead && fullWord && !started && (req.address===MemoryMap.mmio.U ||
    (req.address===(MemoryMap.mmio+80).U && !controlState.persistPending))
  val waitingRead=isRead && fullWord && req.address===(MemoryMap.mmio+16).U
  val eventWait=waitingRead && !(pending & (wakeMask | "h30".U)).orR
  val parked=io.request.valid && (bootWait || eventWait);h.parked:=parked
  val maintenance=adcBusy || scalingBusy || (!spiClaimRequested && (timing.requested || timing.periodPending))
  io.canSleep:=p.lowPower.nonEmpty.B && parked && (bootWait || sleepRemaining=/=0.U) &&
    !responseValid && !memoryBusy && !maintenance && !tick && !resetNeeded
  io.activity:=host.io.busy || gpioActivity || memoryBusy || maintenance
  io.request.ready:= !io.applicationCancel && !resetNeeded && !responseValid && !memoryBusy &&
    !host.io.frame.valid && !bootWait && !eventWait
  io.commit.valid:=io.request.fire;io.commit.bits:=req

  val heartbeat=RegInit(false.B);io.heartbeat:=heartbeat
  val ack0=RegNext(io.watchdogAck,false.B);val ack=RegNext(ack0,false.B)
  val kickPending=applicationReg(false.B)
  when((effects.kick || kickPending) && !(controlState.loaderHold && controlState.started)) {
    when(ack===heartbeat) {heartbeat:= !heartbeat;kickPending:=false.B}
      .otherwise {kickPending:=true.B}
  }
  when(controlState.loaderHold && controlState.started) {kickPending:=false.B}

  val peripheralData=WireDefault(0.U(32.W))
  val offset=req.address(6,0)
  switch(offset) {
    is(4.U) {peripheralData:=now};is(8.U) {peripheralData:=timing.deadline}
    is(12.U,16.U) {peripheralData:=pending};is(20.U) {peripheralData:=gpio & gpioMask}
    is(24.U) {peripheralData:=gpioOutputView};is(28.U) {peripheralData:=gpioEnableView}
    is(52.U) {peripheralData:=applicationWord(appIndex)}
    is(56.U) {peripheralData:=wakeMask};is(60.U) {peripheralData:=sleepRemaining}
    is(64.U) {peripheralData:=samplePeriod}
    is(68.U) {peripheralData:=Cat(0.U(28.W),periodPending,sleepRemaining=/=0.U,!io.clockRunning,p.lowPower.nonEmpty.B)}
    is(72.U) {peripheralData:=io.sleepEntries}
    is(92.U) {peripheralData:=(MemoryMap.ram+config.workingRamBytes).U}
    is(88.U) {peripheralData:= (if(p.spiBoot) Cat(0.U(29.W),output(5) && enable(5) && !output(3),adcBusy,spiClaimed) else 0.U)}
  }
  command.cpuResetActive:=io.applicationCancel;command.programBusy:=program.io.busy || loaderPending
  command.memory:=req;command.peripheralData:=peripheralData;command.applicationWritable:=applicationExists(appIndex)
  // Wire sampling is a non-backpressurable source. It has edge priority;
  // memory replies remain held and CPU ready stays low on that edge.
  when(host.io.frame.valid) {
    control.valid:=true.B;command.kind:=ControlKind.Host.U;command.frame:=host.io.frame.bits
    command.cpuResetActive:=host.io.frameReset || io.applicationCancel
  }.elsewhen(program.io.response.valid && loaderPending) {
    control.valid:=true.B;command.kind:=ControlKind.Stored.U
  }.elsewhen(resetNeeded) {
    control.valid:=true.B;command.kind:=ControlKind.ResetApplication.U;resetNeeded:=false.B
  }.elsewhen(io.request.fire && (mmio || req.operation===Operation.Halt.U)) {
    control.valid:=true.B
    command.kind:=Mux(req.operation===Operation.Halt.U,ControlKind.Halt.U,ControlKind.MmioCommit.U)
  }
  program.io.response.ready:= !loaderPending || (control.valid && command.kind===ControlKind.Stored.U)
  val programLoaderCommit=control.valid && control.result.programWrite
  when(programLoaderCommit) {
    assert(program.io.request.ready,"CLOCKED_LOADER_WITHOUT_MEMORY_CREDIT")
    program.io.request.valid:=true.B;program.io.request.bits.address:=controlState.received
    program.io.request.bits.write:=true.B;program.io.request.bits.data:=control.result.state.loaderWord
    program.io.request.bits.mask:=15.U
  }
  h.periodUpdate:=control.valid && control.result.periodUpdate;h.period:=control.result.period
  when((program.io.response.fire && !loaderPending) || ram.io.response.fire) {
    cpuMemoryPending:=false.B
    when(cpuMemoryPending && !io.applicationCancel) {
      responseValid:=true.B;response.error:=false.B
      response.data:=Mux(ram.io.response.valid,ram.io.response.bits,program.io.response.bits)
    }
  }
  when(io.request.fire) {
    responseValid:=req.operation=/=Operation.Halt.U;response.data:=0.U;response.error:=true.B
    h.waitAccepted:=waitingRead
    when(req.operation===Operation.Halt.U) {responseValid:=false.B}
      .elsewhen(req.address<(p.bootWords.size*4).U) {
        when(!isWrite) {response.data:=VecInit(p.bootWords.map(_.U(32.W)))(req.address(log2Ceil(p.bootWords.size).max(1)+1,2));response.error:=false.B}
      }.elsewhen(req.address>=MemoryMap.program.U && req.address<(MemoryMap.program+config.programBytes).U) {
        when(!isWrite && programmed && (req.address-MemoryMap.program.U)<controlState.imageLength) {
          program.io.request.valid:=true.B;program.io.request.bits.address:=req.address-MemoryMap.program.U
          responseValid:=false.B;cpuMemoryPending:=true.B
        }
      }.elsewhen(req.address>=MemoryMap.ram.U && req.address<(MemoryMap.ram+config.workingRamBytes).U && !isFetch) {
        ram.io.request.valid:=true.B;ram.io.request.bits.address:=req.address-MemoryMap.ram.U
        ram.io.request.bits.write:=isWrite;ram.io.request.bits.data:=req.data;ram.io.request.bits.mask:=req.mask
        responseValid:=false.B;cpuMemoryPending:=true.B
      }.elsewhen(mmio && !isFetch && fullWord) {
        response:=control.result.memory
        when(isWrite && !control.result.memory.error) {
          h.write:=true.B;h.offset:=offset;h.data:=req.data
          switch(offset) {
            is(8.U) {replaceDeadline:=true.B}
            is(12.U) {clear:=req.data(5,0) & ~Mux(mmioObserved,mmioEvents,0.U(6.W))}
            is(24.U) {output:=req.data};is(28.U) {enable:=req.data}
            is(52.U) {for((word,value) <- application) {when(appIndex===word.U) {value:=req.data}}}
            is(44.U) {for(i <- p.softwareSampleChannels) {when(sampleIndex===i.U) {
              publish(i).valid:=true.B;publish(i).bits.value:=sampleValue
              publish(i).bits.valid:=req.data(0);publish(i).bits.calibrated:=req.data(1)
            }}}
            is(64.U) {h.periodUpdate:=true.B;h.period:=req.data}
            is(88.U) {if(p.spiBoot) {
              spiClaimRequested:=req.data(0);when(!req.data(0)) {spiClaimed:=false.B}
            }}
          }
        }
      }
  }

  // Read-address acceptance is the atomic point for the complete host bank.
  val bankWords=(HostSchema.device.map(_.word) ++ config.application.registers.map(_.word)).distinct.sorted
  val bank=Wire(Vec(bankWords.size,UInt(32.W)));bank.foreach(_ := "hffffffff".U)
  val space=selector(23,16);val instance=selector(15,8)
  def fields(values: Seq[UInt]): Unit=values.zipWithIndex.foreach {case(v,i) => bank(i):=v}
  when(space===0.U && instance===0.U) {
    fields(Seq("h00010000".U,config.application.id.U,config.application.version.U,config.programBytes.U,
      config.workingRamBytes.U,config.gpioCount.U,config.measurements.size.U,Mux(io.watchdogReason,2.U,1.U),io.crashCount))
  }
  when(space===1.U && instance===0.U) {
    fields(Seq(mode,programmed.asUInt,locked.asUInt,canProgram.asUInt,(loaderPending || controlState.persistPending).asUInt,
      controlState.lastError,controlState.imageId,controlState.received,
      Cat(0.U(24.W),controlState.bootIndex,controlState.bootSession,controlState.persisted,controlState.persistPending,controlState.loaderHold)))
  }
  when(space===3.U && instance===0.U) {
    val features=if(p.lowPower.nonEmpty) 3 | (if(p.adc.nonEmpty) 4 else 0) | (if(p.lowPower.exists(_.stopServiceClock)) 8 else 0) else 0
    fields(Seq(features.U,now,samplePeriod,wakeMask,sleepRemaining,pending,io.sleepEntries,
      Cat(0.U(28.W),periodPending,sleepRemaining=/=0.U,!io.clockRunning,p.lowPower.nonEmpty.B)))
  }
  when(space===3.U && instance===1.U) {
    val lp=p.lowPower
    fields(Seq(lp.map(_.tickMicros).getOrElse(1000).U,lp.map(_.minimumTickMicros).getOrElse(1000).U,
      lp.map(_.maximumTickMicros).getOrElse(1000).U,p.minimumSampleMs.U,p.maximumSampleMs.max(0).U,p.staleMs.U,
      (if(lp.exists(_.stopServiceClock)) LowPowerParameters.hostWakeWaitUs else 0).U,p.watchdogCycles.U))
  }
  for(i <- config.measurements.indices) {
    when(space===2.U && instance===i.U) {
      val s=hostSamples(i);val stale=s.age>=p.freshLimitMs.max(0).U
      fields(Seq(s.value,Cat(0.U(27.W),s.calibrated,s.fault,s.never,stale,s.valid && !s.never && !stale),
        Mux(s.never,"hffffffff".U,s.age),s.sequence,config.measurements(i).unit.U,config.measurements(i).scale10.S(32.W).asUInt))
    }
  }
  when(space===128.U && instance===0.U) {
    for(r <- config.application.registers) {bank(bankWords.indexOf(r.word)):=applicationWord(r.word.U)}
  }
  val supported=(0 until 8).map {i =>
    val word=selector(7,0)+&i.U
    (space===0.U && instance===0.U && word<HostSchema.device.size.U) ||
      (space===1.U && instance===0.U && word<HostSchema.loader.size.U) ||
      (space===3.U && instance<=1.U && word<8.U) ||
      (space===2.U && instance<config.measurements.size.U && word<6.U) ||
      (space===128.U && instance===0.U && applicationExists(word))
  }
  val snapshot=Reg(Vec(bankWords.size,UInt(32.W)));val snapshotSupported=Reg(UInt(8.W))
  when(host.io.readStart) {snapshot:=bank;snapshotSupported:=Cat(supported.reverse)}
  val readIndex=selector(7,0)+&host.io.wordIndex
  host.io.readWord:=Mux(host.io.wordIndex===8.U,Cat(0.U(24.W),snapshotSupported),
    MuxLookup(readIndex,"hffffffff".U(32.W))(bankWords.zipWithIndex.map {case(w,i) => w.U -> snapshot(i)}))
  when(io.applicationCancel) {applicationResets.foreach(_());resetNeeded:=true.B}
}
