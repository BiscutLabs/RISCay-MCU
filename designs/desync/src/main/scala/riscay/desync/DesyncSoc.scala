// SPDX-License-Identifier: Apache-2.0
package riscay.desync

import chisel3._
import chisel3.util._
import riscay.soc._

/** Ideal-clock view of the desynchronized region, copied from the clocked MCU.
  * DesyncChip supplies its single self-timed source at serviceClock.
  * The work clock drives CPU, fabric and peripherals;
  * the independent LF clock retains the watchdog and timebase during sleep.
  * Watchdog assertion isolates the pads immediately. POR-owned fabric state
  * receives only a synchronized cancellation, then acknowledges cleanup before
  * the CPU is released. An accepted SRAM transaction always drains.
  */
class DesyncSoc(val p: SocParameters) extends RawModule with SocPorts {
  val reset = IO(Input(AsyncReset()))
  val watchdog = withClockAndReset(watchdogClock,reset) {
    Module(new ClockedWatchdog(p.watchdogCycles,p.watchdogHoldCycles))
  }
  protected val applicationResetRequest = WireDefault(reset.asBool || watchdog.io.expired)
  val release = withClockAndReset(serviceClock,applicationResetRequest.asAsyncReset) {
    val q=RegInit(255.U(8.W)); q:=Cat(q(6,0),false.B); q
  }
  systemReset:=applicationResetRequest || release.orR
  resetReason:=watchdog.io.reason
  val cpuResetActive=withClockAndReset(serviceClock,reset) {
    val first=RegNext(systemReset,true.B); RegNext(first,true.B)
  }
  val watchdogReasonActive=withClockAndReset(serviceClock,reset) {
    val first=RegNext(watchdog.io.reason,false.B); RegNext(first,false.B)
  }
  val crashCount=withClockAndReset(serviceClock,reset) {
    val previous=RegNext(cpuResetActive,true.B); val q=RegInit(0.U(32.W))
    when(cpuResetActive && !previous && !q.andR) {q:=q+1.U}; q
  }
  protected val workClock=Wire(Clock())
  dontTouch(workClock) // Explicit root for ordinary clock-sink inventory and STA.
  protected val fabric=withClockAndReset(workClock,reset) {Module(new ClockedFabric(p))}
  fabric.io.frontClock:=serviceClock
  fabric.io.applicationCancel:=cpuResetActive
  // Close the receiver and synchronously clear the producer on the same work
  // edge. Raw watchdog reset must never change an offered payload underneath
  // POR-owned memory/control state before that edge. Release follows cleanup.
  val coreReset=withClockAndReset(workClock,reset) {
    val held=RegInit(true.B)
    when(cpuResetActive) {held:=true.B}
      .elsewhen(fabric.io.resetComplete) {held:=false.B}
    held
  }
  protected val applicationIsolation=systemReset || cpuResetActive || coreReset
  protected val core=withClockAndReset(workClock,reset.asBool || cpuResetActive || coreReset) {
    Module(new ClockedCore)
  }
  fabric.io.request<>core.request;core.response<>fabric.io.response
  trace:=core.trace;trace.valid:=core.trace.valid && !applicationIsolation
  traceEvent:=core.traceEvent && !applicationIsolation
  fabric.io.scl:=scl;fabric.io.sda:=sda;sdaLow:=fabric.io.sdaLow
  fabric.io.gpioIn:=(if(p.spiBoot) (gpioIn & "hffffffbf".U) | (adcMiso.asUInt<<6) else gpioIn)
  fabric.io.adcMiso:=adcMiso;adcCsN:=fabric.io.adcCsN
  adcSclk:=Mux(fabric.io.spiClaimed && applicationIsolation,false.B,fabric.io.adcSclk)
  // Raw reset has no fan-in to retained data. This last pad-only mask provides
  // immediate isolation; the work-clock owner separately clears its state.
  val isolationMask=if(!p.retainGpioOnWatchdog) 0.U(32.W)
    else if(p.spiBoot) "hffffffc7".U(32.W) else "hffffffff".U(32.W)
  gpioOut:=fabric.io.gpioOut & Mux(applicationIsolation,isolationMask,"hffffffff".U)
  gpioOe:=fabric.io.gpioOe & Mux(applicationIsolation,isolationMask,"hffffffff".U)
  fabric.io.watchdogReason:=watchdogReasonActive;fabric.io.crashCount:=crashCount
  watchdog.io.heartbeat:=fabric.io.heartbeat;fabric.io.watchdogAck:=watchdog.io.acknowledge
  p.lowPower match {
    case Some(lp) =>
      val timebase=withClockAndReset(watchdogClock,reset) {Module(new ClockedTimebase(lp))}
      val gate=withClockAndReset(serviceClock,reset) {Module(new ClockedGate)}
      val wake=withClockAndReset(serviceClock,reset) {Module(new ClockedWake)}
      gate.io.gray:=timebase.io.gray;gate.io.consumedGray:=fabric.io.consumedGray
      gate.io.canSleep:=fabric.io.canSleep;gate.io.activity:=fabric.io.activity
      gate.io.forceRun:=cpuResetActive || wake.io.wake
      gate.io.drainDemand:=cpuResetActive
      workClock:=gate.io.clockOut;fabric.io.clockRunning:=gate.io.running
      fabric.io.timeGray:=gate.io.synchronizedGray;sleepEntries:=gate.io.entries;sleeping:= !gate.io.running
      wake.io.event:=systemReset || timebase.io.gray=/=fabric.io.consumedGray ||
        ((fabric.io.gpioIn ^ fabric.io.observedGpio) & p.gpioEventMask.U(32.W)).orR
      wake.io.scl:=scl;wake.io.sda:=sda
      wake.io.selected:=fabric.io.hostSelected;wake.io.rejected:=fabric.io.hostRejected
      wake.io.running:=gate.io.running || applicationIsolation
      serviceClockEnable:=(if(lp.stopServiceClock) wake.io.enable else true.B)
    case None =>
      workClock:=serviceClock;fabric.io.clockRunning:=true.B;fabric.io.timeGray:=0.U
      sleepEntries:=0.U;sleeping:=false.B;serviceClockEnable:=true.B
  }
  fabric.io.sleepEntries:=sleepEntries
  mode:=fabric.io.mode;programmed:=fabric.io.programmed;locked:=fabric.io.locked;commit:=fabric.io.commit
}

object EmitDesyncSoc extends App {
  require(args.length==1,"Usage: EmitDesyncSoc output-directory")
  val p=SocParameters(riscay.profiles.Groundlark.configuration,staleMs=3000,watchdogCycles=32,
    watchdogHoldCycles=2,adc=Some(AdcParameters(intervalCycles=10000000)),
    lowPower=Some(LowPowerParameters.gf180Slow),spiBoot=true)
  val directory=java.nio.file.Paths.get(args(0))
  DesyncExport.emit(new DesyncSoc(p),directory)
  SramInventory.write(directory,p.config,synchronous=true,metadataFile="desync.json")
  DesyncChip.write(directory)
}
