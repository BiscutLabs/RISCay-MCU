// SPDX-License-Identifier: Apache-2.0
package riscay
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import riscay.soc._

// Same probes as the clocked fixtures; no architectural state is added.
class DesyncFabricFixture(p: SocParameters) extends riscay.desync.DesyncSoc(p) {
  val resetSettled=IO(Output(Bool()));resetSettled:= !(cpuResetActive || coreReset || systemReset)
  val request=IO(Flipped(Decoupled(new MemoryRequest)))
  val response=IO(Decoupled(new MemoryResponse))
  val timeNow=IO(Output(UInt(32.W)))
  timeNow:=chisel3.util.experimental.BoringUtils.bore(fabric.housekeeping.state.now)
  core.request.ready:=false.B;core.response.valid:=false.B;core.response.bits:=0.U.asTypeOf(new MemoryResponse)
  fabric.io.request<>request;response<>fabric.io.response
  trace:=0.U.asTypeOf(new Retirement);traceEvent:=false.B
}
class DesyncKickFixture(p: SocParameters) extends DesyncFabricFixture(p) {
  val ack=IO(Input(Bool()));val heartbeat=IO(Output(Bool()))
  fabric.io.watchdogAck:=ack;heartbeat:=fabric.io.heartbeat
}
class DesyncWaitValidationFixture(p: SocParameters) extends DesyncFabricFixture(p) {
  val sleepEligible=IO(Output(Bool()));sleepEligible:=fabric.io.canSleep
}
class DesyncResetCrossingFixture(p: SocParameters) extends DesyncFabricFixture(p) {
  val heartbeatEnabled=IO(Input(Bool()))
  val resetObserved=IO(Output(Bool()));resetObserved:=cpuResetActive
  val gatedClock=IO(Output(Clock()));gatedClock:=workClock
  watchdog.io.heartbeat:=Mux(heartbeatEnabled,fabric.io.heartbeat,false.B)
}


class DesyncRecoveryFixture(p: SocParameters) extends DesyncFabricFixture(p) {
  val recovery=IO(Input(Bool()))
  applicationResetRequest:=reset.asBool || watchdog.io.expired || recovery
  val cancel=IO(Output(Bool()));cancel:=cpuResetActive
  val work=IO(Output(Clock()));work:=workClock
  val samplePublished=IO(Output(Bool()));samplePublished:=BoringUtils.bore(fabric.publish(0).valid)
  val sampleAge=IO(Output(UInt(32.W)));sampleAge:=BoringUtils.bore(fabric.hostSamples(0).age)
}


class DesyncEventFixture(p: SocParameters) extends DesyncFabricFixture(p) {
  val injectedEvents=IO(Input(UInt(6.W)));BoringUtils.drive(fabric.events):=injectedEvents
  val eventView=IO(Output(UInt(6.W)));eventView:=BoringUtils.bore(fabric.pending)
  val eventCut=IO(Output(Bool()));eventCut:=BoringUtils.bore(fabric.mmioObserved)
  val eventCancel=IO(Output(Bool()));eventCancel:=fabric.io.applicationCancel
  val eventArriving=IO(Output(Bool()));eventArriving:=fabric.io.request.valid &&
    fabric.io.request.bits.address>=MemoryMap.mmio.U &&
    fabric.io.request.bits.address<(MemoryMap.mmio+MemoryMap.mmioBytes).U && fabric.io.request.bits.operation=/=Operation.Halt.U
  val eventReplace=IO(Output(Bool()));eventReplace:=BoringUtils.bore(fabric.replaceDeadline)
  val eventClear=IO(Output(Bool()));eventClear:=fabric.io.request.fire &&
    fabric.io.request.bits.operation===2.U && fabric.io.request.bits.address===(MemoryMap.mmio+12).U &&
    !BoringUtils.bore(fabric.control.result.memory.error)
}


class DesyncGenericBootFixture(p: SocParameters)
    extends riscay.desync.DesyncSoc(p) {
  val recovery=IO(Input(Bool()))
  applicationResetRequest := reset.asBool || watchdog.io.expired || recovery
  val spiOwned=IO(Output(Bool())); spiOwned:=fabric.io.spiClaimed
  val adcBusy=IO(Output(Bool())); adcBusy:=fabric.io.adcBusy
  val gpioEvent=IO(Output(Bool())); gpioEvent:=BoringUtils.bore(fabric.gpioActivity)
  val loaderWrite=IO(Output(Bool())); loaderWrite:=BoringUtils.bore(fabric.programLoaderCommit)
  val pauseBootStatus=IO(Input(Bool()));val statusWaiting=IO(Output(Bool()))
  statusWaiting:=core.request.valid && core.request.bits.operation===1.U &&
    core.request.bits.address===(MemoryMap.mmio+76).U &&
    BoringUtils.bore(fabric.controlState.bootSession) && BoringUtils.bore(fabric.controlState.bootIndex)===0.U
  fabric.io.request.valid:=core.request.valid && !(pauseBootStatus && statusWaiting)
  core.request.ready:=fabric.io.request.ready && !(pauseBootStatus && statusWaiting)
}
