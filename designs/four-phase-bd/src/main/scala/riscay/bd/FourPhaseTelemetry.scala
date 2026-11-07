// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation, PassiveDataAllowance}
import chiselasync.protocol.FourPhase
import riscay._
import riscay.soc._

/** The existing Telemetry owner exposes its closed architectural bank. */
class TelemetryRegisters(gpios: Int, words: Int) extends Bundle {
  val output=UInt(gpios.max(1).W); val enable=UInt(gpios.max(1).W)
  val application=if(words>0) Some(Vec(words,UInt(32.W))) else None
}
/** Application/GPIO state lives only in the closed bank, not in the feedback token. */
class TelemetryFeedback(channels: Int) extends Bundle {
  val credit=Bool()
}

/** Only committed effects cross the retained reply channel. */
class TelemetryEffects extends Bundle {
  val kind=UInt(2.W);val recovery=Bool()
}

/** POR-owned native telemetry. Application reset remains an ordered command. */
class FourPhaseTelemetry(p: SocParameters, words: Vector[Int], domain: ResetDomain, qualifyCommit: Boolean=false) extends AsyncModule(domain) {
  val command = fourPhaseInput("command", new TelemetryCommand(p.softwareSampleChannels.size))
  val reply = fourPhaseOutput("reply", new TelemetryEffects)
  val view=IO(Output(new TelemetryRegisters(p.config.gpioCount,words.size)))
  val sampleView=IO(Output(Vec(p.softwareSampleChannels.size,new SampleRecord)))
  val commitAck=if(qualifyCommit) Some(IO(Input(Bool()))) else None
  commitAck.foreach(contract.endpoint("commit_ack",_))
  private val timing=OwnerTiming.base
  private val cell=ModelTime.ps(1000)
  private val resetRef=contract.endpoint("reset",reset)
  contract.endpoint("register_view",view)
  private val feedback=new TelemetryFeedback(p.softwareSampleChannels.size)
  private val initial=feedback.Lit(_.credit -> false.B)
  private val state=asyncChild("state")(d => new FourPhaseFifo(new TelemetryFeedback(p.softwareSampleChannels.size),1,
    timing,Seq(initial),cell,d))
  private val join=asyncChild("join")(d => new FourPhaseJoin(new TelemetryFeedback(p.softwareSampleChannels.size),
    new TelemetryCommand(p.softwareSampleChannels.size),timing,cell,d))
  private val update=asyncChild("update")(d => new FourPhaseStage(
    new TelemetryEffects,new TelemetryEffects,(x: TelemetryEffects) => x,timing,d))
  private val fork=asyncChild("fork")(d => new FourPhaseFork(new TelemetryEffects,2,cell,d))
  dontTouch(fork.out(0))
  FourPhase.connect(join.left,state.out); FourPhase.connect(join.right,command)
  update.in.req:=join.out.req
  update.in.bits.kind:=join.out.bits.right.kind;update.in.bits.recovery:=join.out.bits.right.recovery
  // The command bank remains borrowed until both effect capture and bank
  // publication finish, including their complete return-to-zero.
  private val commandReturn=Module(new AsymmetricCElement(2,0,0,cell))
  commandReturn.reset:=reset;commandReturn.common:=Cat(update.in.ack,reply.ack)
  commandReturn.rising:=0.U;commandReturn.falling:=0.U
  contract.primitive("command_return",commandReturn,Map("COMMON"->BigInt(2),"RISING"->BigInt(0),"FALLING"->BigInt(0),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,"held command through actual bank capture and both ACK returns")
  join.out.ack:=commandReturn.q
  private val nextState=transition(join.out.bits.right,view,
    if(p.softwareSampleChannels.nonEmpty) Some(sampleView) else None).state
  private val operands=WireDefault(UInt((view.getWidth+sampleView.getWidth+join.out.bits.right.getWidth).W),
    Cat(view.asUInt,sampleView.asUInt,join.out.bits.right.asUInt))
  private def bankData(id: String,value: UInt): UInt = {
    val data=PassiveDataAllowance(this,id,value,timing.dataDelay.model,resetRef)
    contract.endpoint(id+"_source",operands);contract.endpoint(id+"_data",data)
    contract.dataPathTiming(id+"_path",id+"_source",id+"_data",timing,
      "held command plus closed bank; capture on the bank's registered receiving ACK",delayCell=id)
    data
  }

  // The existing receipt ACK rises after the actual work-clock acceptance
  // edge. Commit the closed bank once at that event; no periodic clock enters
  // this owner. Same-edge observers see the old bank, later edges the new bank.
  // This needs an ACK-to-Q min hold / next-edge max setup boundary constraint.
  private val stored=Module(new EventRegister(view.getWidth,cell))
  private val next=Wire(new TelemetryRegisters(p.config.gpioCount,words.size))
  next.output:=nextState.output;next.enable:=nextState.enable
  next.application.foreach(_ := nextState.application.get)
  stored.reset:=reset;stored.trigger:=commitAck.getOrElse(reply.ack);stored.d:=bankData("register_data_delay",next.asUInt)
  contract.primitive("register_bank",stored,Map("WIDTH"->BigInt(view.getWidth),"DELAY_FS"->BigInt(cell.fs),
    "RESET_VALUE"->BigInt(0)),resetRef,"sole application/GPIO state; closed outputs; one capture per committed update")
  view:=stored.q.asTypeOf(view)
  if(p.softwareSampleChannels.nonEmpty) {
    val samples=Module(new EventRegister(sampleView.getWidth,cell))
    samples.reset:=reset;samples.trigger:=reply.ack
    samples.d:=bankData("sample_data_delay",nextState.samples.get.asUInt)
    sampleView:=samples.q.asTypeOf(sampleView)
    contract.primitive("sample_bank",samples,Map("WIDTH"->BigInt(sampleView.getWidth),"DELAY_FS"->BigInt(cell.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"POR software samples; accepted publications survive application cancellation")
  } else {sampleView:=0.U.asTypeOf(sampleView)}
  if(p.softwareSampleChannels.nonEmpty) {contract.endpoint("sample_view",sampleView)}
  FourPhase.connect(fork.in,update.out)
  state.in.bits.credit:=false.B
  // The feedback token cannot permit another transform until the closed bank
  // has captured. The fork retains its full data through both ACK phases.
  private val returned=Module(new AsymmetricCElement(2,0,0,cell))
  returned.reset:=reset;returned.common:=Cat(fork.out(0).req,reply.ack)
  returned.rising:=0.U;returned.falling:=0.U
  contract.primitive("bank_completion",returned,Map("COMMON"->BigInt(2),"RISING"->BigInt(0),"FALLING"->BigInt(0),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,"bank capture precedes feedback; full return-to-zero")
  private val settled=Module(new ControlGate(1,GateOperation.Buffer,ModelTime.ps(10000)))
  settled.reset:=reset;settled.a:=returned.q.asUInt;settled.b:=0.U
  contract.primitive("output_guard",settled,Map("WIDTH"->BigInt(1),"OP"->BigInt(0),
    "DELAY_FS"->BigInt(10000000),"RESET_VALUE"->BigInt(0)),resetRef,
    "relative bank capture-to-feedback ordering model; requires its own same-corner sizing")
  state.in.req:=settled.q.asBool;fork.out(0).ack:=state.in.ack
  FourPhase.connect(reply,fork.out(1))
  contract.endpoint("command_capture",join.out.req)
  contract.endpoint("register_capture",stored.trigger)
  contract.setupHold("register_aperture","command_capture","register_data_delay_source","register_data_delay_data",
    "register_capture","register_view",ModelTime.ps(100),ModelTime.ps(100))
  if(p.softwareSampleChannels.nonEmpty) {
    // Software samples commit on ordinary ACK even when application publication
    // is revoked. Keep their capture root distinct from qualified commitAck.
    contract.endpoint("sample_capture",reply.ack)
    contract.setupHold("sample_aperture","command_capture","sample_data_delay_source","sample_data_delay_data",
      "sample_capture","sample_view",ModelTime.ps(100),ModelTime.ps(100))
  }
  private def transition(c: TelemetryCommand, registers: TelemetryRegisters, samples: Option[Vec[SampleRecord]]): TelemetryReply = {
    val r = WireDefault(0.U.asTypeOf(new TelemetryReply(p.softwareSampleChannels.size, words.size)))
    r.kind := c.kind
    r.state.output := registers.output.pad(32); r.state.enable := registers.enable.pad(32)
    r.state.application.foreach(_ := registers.application.get)
    r.state.samples.foreach(_ := samples.get)
    r.recovery := c.recovery
    val n = r.state
    when(c.kind === TelemetryKind.ResetApplication.U) {
      if(!p.retainGpioOnWatchdog) {
        n.output := 0.U; n.enable := 0.U
      } else if(p.spiBoot) {
        n.output := registers.output.pad(32) & "hffffffc7".U; n.enable := registers.enable.pad(32) & "hffffffc7".U
      }
      n.application.foreach(_.foreach(_ := 0.U))
    }
    when(c.kind === TelemetryKind.Commit.U) {
      switch(c.offset) {
        is(24.U) { n.output := c.data & ((BigInt(1)<<p.config.gpioCount)-1).U(32.W) }
        is(28.U) { n.enable := c.data & ((BigInt(1)<<p.config.gpioCount)-1).U(32.W) }
        is(52.U) { for((word,index) <- words.zipWithIndex) {
          when(c.appIndex === word.U) { n.application.get(index) := c.data }
        } }
      }
    }
    for((channel,index) <- p.softwareSampleChannels.zipWithIndex) {
      val capture=c.sample.get
      val next=n.samples.get(index)
      when(c.kind === TelemetryKind.Commit.U && c.offset === 44.U && capture.index === channel.U) {
        next.sequence:=samples.get(index).sequence+1.U
        next.valid:=c.data(0);next.fault:= !c.data(0)
        next.calibrated:=c.data(0) && c.data(1)
        when(c.data(0)) {
          next.value:=capture.value;next.timestamp:=capture.timestamp;next.seen:=true.B
        }
      }
    }
    r
  }
}
