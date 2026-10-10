// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled.FourPhaseStage
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ModelTime}
import chiselasync.primitives.{AsymmetricCElement,ControlGate,GateOperation,PhaseRegister}
import chiselasync.protocol.FourPhase
import riscay._
import riscay.soc._

/** Application-lifetime completion join. Persistent effects are NOT reset here.
  * A held plan selects its completion inputs; every selected input must arrive
  * before capture. Each acknowledgment remains asserted through its own return.
  */
class FourPhaseCompletion(domain: ResetDomain) extends AsyncModule(domain) {
  val plan=fourPhaseInput("plan",new CompletionPlan)
  val memory=fourPhaseInput("memory",new MemoryResponse)
  val telemetry=fourPhaseInput("telemetry",Bool())
  val housekeeping=fourPhaseInput("housekeeping",Bool())
  val response=fourPhaseOutput("response",new MemoryResponse)
  val retired=IO(Output(Bool()))
  // Keep the full declared channel ABI even when a particular endpoint always
  // publishes error=false or an effect token has no architectural payload.
  Seq(plan,memory,telemetry,housekeeping,response).foreach(dontTouch(_))
  private val timing=BundledTiming.Simulation
  private val cell=ModelTime.ps(1000)
  private val resetRef=contract.endpoint("reset",reset)
  private def gate(id: String,op: GateOperation.Value,a: Bool,b: Bool=false.B,
      delay: ModelTime=cell,initial: Int=0): Bool = {
    val g=Module(new ControlGate(1,op,delay,initial)); g.reset:=reset; g.a:=a.asUInt; g.b:=b.asUInt
    contract.primitive(id,g,Map("WIDTH"->BigInt(1),"OP"->BigInt(op.id),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->BigInt(initial)),resetRef,"completion control; preserve and qualify composed return paths")
    g.q.asBool
  }
  private def and(id: String,a: Bool,b: Bool): Bool = {
    val na=gate(id+"_na",GateOperation.Invert,a,initial=1)
    val nb=gate(id+"_nb",GateOperation.Invert,b,initial=1)
    val either=gate(id+"_or",GateOperation.Or,na,nb,initial=1)
    gate(id,GateOperation.Invert,either)
  }
  private val guarded=gate("request_guard",GateOperation.Buffer,plan.req,delay=timing.matchedDelay)
  private val selected=Seq(("memory",memory.req,plan.bits.memory),
    ("telemetry",telemetry.req,plan.bits.telemetry),("housekeeping",housekeeping.req,plan.bits.housekeeping))
  // A rendezvous has a full return barrier, not a combinational AND. No source
  // may reuse its phase until every old request, including the plan, returns.
  private val rendezvous=Module(new AsymmetricCElement(1,3,3,cell)); rendezvous.reset:=reset
  rendezvous.common:=guarded.asUInt
  rendezvous.rising:=Cat(selected.map { case(_,req,needed) => !needed || req })
  rendezvous.falling:=Cat(selected.map { case(_,req,needed) => needed && req })
  contract.primitive("rendezvous",rendezvous,Map("COMMON"->BigInt(1),"RISING"->BigInt(3),"FALLING"->BigInt(3),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,"selected join offer holds through every input return")
  private val result=WireDefault(Mux(plan.bits.memory,memory.bits,plan.bits.response))
  private val reply=asyncChild("reply")(d => new FourPhaseStage(new MemoryResponse,new MemoryResponse,
    (x: MemoryResponse) => x,timing,d))
  reply.in.req:=rendezvous.q; reply.in.bits:=result
  memory.ack:=and("memory_ack",reply.in.ack,plan.bits.memory)
  telemetry.ack:=and("telemetry_ack",reply.in.ack,plan.bits.telemetry)
  housekeeping.ack:=and("housekeeping_ack",reply.in.ack,plan.bits.housekeeping)
  private val complete=Module(new AsymmetricCElement(1,0,3,cell)); complete.reset:=reset
  complete.common:=reply.in.ack.asUInt; complete.rising:=1.U
  complete.falling:=Cat(memory.ack,telemetry.ack,housekeeping.ack)
  plan.ack:=complete.q
  contract.primitive("plan_ack",complete,Map("COMMON"->BigInt(1),"RISING"->BigInt(0),"FALLING"->BigInt(3),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,"plan payload release waits for every source acknowledgment return")
  FourPhase.connect(response,reply.out)
  private val retirement=Module(new PhaseRegister(cell)); retirement.reset:=reset; retirement.trigger:=response.ack
  retired:=retirement.q
  contract.primitive("retirement",retirement,Map("DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0)),resetRef,
    "consumer acknowledgment toggles a persistent retirement observation; synchronize before clocked admission")
  contract.endpoint("retired",retired)
  contract.endpoint("result_sources",Cat(plan.bits.asUInt,memory.bits.asUInt))
  contract.endpoint("result",result)
  contract.dataPathTiming("completion_mux","result_sources","result",timing,
    "held plan selects immediate or completed memory reply",Seq("reply"))
  contract.capacity(1)
}
