// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ClickTiming,ModelTime}
import chiselasync.primitives.{ControlGate,EventRegister,GateOperation,XorGate}
import riscay._
import riscay.soc._

/** Native selected-input completion join; no arbitration or RTZ conversion.
  * Every selected input is retained until a common capture. Unselected phase
  * acknowledgments retain their previous parity, including an early next input.
  */
class ClickCompletion(domain: ResetDomain) extends AsyncModule(domain) {
  val plan=twoPhaseInput("plan",new CompletionPlan)
  val memory=twoPhaseInput("memory",new MemoryResponse)
  val telemetry=twoPhaseInput("telemetry",Bool())
  val housekeeping=twoPhaseInput("housekeeping",Bool())
  val response=twoPhaseOutput("response",new MemoryResponse)
  val creditReturn=twoPhaseOutput("creditReturn",Bool())
  // Keep the full declared channel ABI even when a particular endpoint always
  // publishes error=false or an effect token has no architectural payload.
  Seq(plan,memory,telemetry,housekeeping,response,creditReturn).foreach(dontTouch(_))
  private val timing=ClickTiming.Simulation
  private val cell=timing.controls.fire.model
  private val resetRef=contract.endpoint("reset",reset)
  // Selected-input comparators and three composed ANDs are deeper than a
  // standard ClickStage. Source/output reuse waits for the entire pulse to drain.
  private val drain=timing.controls.inputPhase.max.fs+20*timing.controls.fire.max.fs+
    timing.clockSkew.fs+math.max(timing.pulseLow.fs,timing.hold.fs)+1
  private val guard=ModelTime(math.max(math.max(timing.acknowledgeDelay.fs,timing.outputDelay.fs),drain))
  private def gate(id: String,op: GateOperation.Value,a: UInt,b: UInt=0.U,
      width: Int=1,delay: ModelTime=cell,initial: Int=0): UInt = {
    val g=Module(new ControlGate(width,op,delay,initial)); g.reset:=reset; g.a:=a; g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),resetRef,"native completion control/data; qualify complete selected-input feedback")
    g.q
  }
  private def and(id: String,a: Bool,b: Bool): Bool = {
    val na=gate(id+"_na",GateOperation.Invert,a.asUInt,initial=1)
    val nb=gate(id+"_nb",GateOperation.Invert,b.asUInt,initial=1)
    val either=gate(id+"_or",GateOperation.Or,na,nb,initial=1)
    gate(id,GateOperation.Invert,either).asBool
  }
  private def xor(id: String,a: Bool,b: Bool): Bool = {
    val g=Module(new XorGate(cell)); g.reset:=reset; g.a:=a; g.b:=b
    contract.primitive(id,g,Map("DELAY_FS"->BigInt(cell.fs)),resetRef,"native completion phase comparator"); g.q
  }
  private def phase(id: String): EventRegister = {
    val g=Module(new EventRegister(1,timing.controls.inputPhase.model)); g.reset:=reset
    contract.primitive(id,g,Map("WIDTH"->BigInt(1),"DELAY_FS"->BigInt(timing.controls.inputPhase.model.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"selected phase feedback captured with payload on the same event"); g
  }
  private val accepted=phase("plan_phase")
  private val memoryPhase=phase("memory_phase")
  private val telemetryPhase=phase("telemetry_phase")
  private val housekeepingPhase=phase("housekeeping_phase")
  private val delayed=gate("request_guard",GateOperation.Buffer,plan.req.asUInt,delay=timing.requestDelay).asBool
  private val pending=xor("plan_pending",delayed,accepted.q.asBool)
  private val occupied=xor("response_occupied",accepted.q.asBool,creditReturn.ack)
  private val sources=Seq(("memory",memory.req,plan.bits.memory,memoryPhase),
    ("telemetry",telemetry.req,plan.bits.telemetry,telemetryPhase),
    ("housekeeping",housekeeping.req,plan.bits.housekeeping,housekeepingPhase))
  // Fixed guard IDs are recognized by the library's timing experiments. The
  // vector guards preserve independent source parities without separate pulses.
  private val readyInputs=Cat(sources.reverse.map { case(_,req,needed,phase) => !needed || (req =/= phase.q.asBool) })
  private val ready=gate("request_delay",GateOperation.Buffer,readyInputs,width=3,delay=timing.requestDelay)
  private val available=sources.zipWithIndex.foldLeft(and("runnable",pending,!occupied)) {
    case(acc,((name,_,_,_),i)) => and(name+"_available",acc,ready(i))
  }
  private val captureEvent=WireDefault(available); dontTouch(captureEvent)
  private val result=Mux(plan.bits.memory,memory.bits,plan.bits.response)
  // Phase feedback belongs to the same bundled-data aperture as the payload.
  // Delay/observe the COMPLETE capture vector, including every selected mux.
  private val captureWidth=(new MemoryResponse).getWidth+4
  private val phaseInputs=Cat(sources.reverse.map { case(_,req,needed,phase) => Mux(needed,req.asUInt,phase.q) })
  private val captureInputs=Cat(phaseInputs,plan.req,result.asUInt)
  private val data=gate("data_delay",GateOperation.Buffer,captureInputs,width=captureWidth,delay=timing.data.model)
  private val registerData=WireDefault(UInt(captureWidth.W),data)
  private val payload=Module(new EventRegister((new MemoryResponse).getWidth,timing.payload.model))
  payload.reset:=reset; payload.trigger:=captureEvent; payload.d:=registerData(32,0)
  contract.primitive("payload",payload,Map("WIDTH"->BigInt((new MemoryResponse).getWidth),
    "DELAY_FS"->BigInt(timing.payload.model.fs),"RESET_VALUE"->BigInt(0)),resetRef,"retained CPU response; common event with every selected phase")
  accepted.trigger:=captureEvent; accepted.d:=registerData(33)
  sources.zipWithIndex.foreach { case((_,_,_,phase),i) =>
    phase.trigger:=captureEvent; phase.d:=registerData(34+i)
  }
  private val captured=WireDefault(UInt(captureWidth.W),Cat(housekeepingPhase.q,telemetryPhase.q,memoryPhase.q,accepted.q,payload.q))
  dontTouch(captured)
  private val acknowledgments=gate("acknowledge_guard",GateOperation.Buffer,
    Cat(housekeepingPhase.q,telemetryPhase.q,memoryPhase.q,accepted.q),width=4,delay=guard)
  plan.ack:=acknowledgments(0); memory.ack:=acknowledgments(1)
  telemetry.ack:=acknowledgments(2); housekeeping.ack:=acknowledgments(3)
  response.req:=gate("output_guard",GateOperation.Buffer,accepted.q,delay=guard).asBool
  response.bits:=payload.q.asTypeOf(new MemoryResponse)
  creditReturn.req:=response.ack; creditReturn.bits:=false.B
  private val resultSources=WireDefault(UInt(76.W),Cat(plan.bits.asUInt,memory.bits.asUInt,
    plan.req,memory.req,telemetry.req,housekeeping.req,memoryPhase.q,telemetryPhase.q,housekeepingPhase.q))
  contract.endpoint("result_sources",resultSources)
  contract.endpoint("captured",captured)
  contract.endpoint("register_data",registerData); contract.endpoint("capture_event",captureEvent)
  contract.dataPathTiming("completion_mux","result_sources","register_data",
    BundledTiming.simulation(dataMax=timing.data.max).copy(dataDelay=timing.data),
    "complete response and selected phase feedback before common capture")
  contract.setupHold("capture_aperture","plan_request","plan_data","register_data",
    "capture_event","captured",timing.setup,timing.hold)
  contract.capacity(1)
}
