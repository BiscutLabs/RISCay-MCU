// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.protocol.TwoPhase
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

class TelemetryUpdate(channels: Int,gpios: Int,words: Int) extends Bundle {
  val state=new TelemetryFeedback(channels)
  val command=new TelemetryCommand(channels)
  val registers=new TelemetryRegisters(gpios,words)
  val samples=if(channels>0) Some(Vec(channels,new SampleRecord)) else None
}

class TelemetryBank(gpios: Int,words: Int,channels: Int) extends Bundle {
  val registers=new TelemetryRegisters(gpios,words)
  val samples=if(channels>0) Some(Vec(channels,new SampleRecord)) else None
}

/** Native phase ownership. The receipt's acceptance phase launches the closed
  * architectural bank; feedback cannot advance before that bank publishes.
  * No phase conversion or periodic storage lives inside this owner.
  */
class ClickTelemetry(p: SocParameters, words: Vector[Int], domain: ResetDomain, qualifyCommit: Boolean=false) extends AsyncModule(domain) {
  val command=twoPhaseInput("command",new TelemetryCommand(p.softwareSampleChannels.size))
  val reply=twoPhaseOutput("reply",new TelemetryReply(p.softwareSampleChannels.size,words.size))
  val start=IO(Input(Bool()))
  val view=IO(Output(new TelemetryRegisters(p.config.gpioCount,words.size)))
  val sampleView=IO(Output(Vec(p.softwareSampleChannels.size,new SampleRecord)))
  val applyBank=if(qualifyCommit) Some(IO(Input(Bool()))) else None
  val bankComplete=IO(Output(Bool()))
  private val timing=OwnerTiming.base
  private val feedback=new TelemetryFeedback(p.softwareSampleChannels.size)
  private val initial=feedback.Lit(_.credit -> false.B)
  private val state=asyncChild("state")(d => new PhaseDecoupledClickBuffer(
    new TelemetryFeedback(p.softwareSampleChannels.size),timing,Some(initial),d))
  private val join=asyncChild("join")(d => new ClickJoin(new TelemetryFeedback(p.softwareSampleChannels.size),
    new TelemetryCommand(p.softwareSampleChannels.size),timing,d))
  private val update=asyncChild("update")(d => new ClickStage(
    new TelemetryUpdate(p.softwareSampleChannels.size,p.config.gpioCount,words.size),
    new TelemetryReply(p.softwareSampleChannels.size,words.size),
    (x: TelemetryUpdate) => transition(x.command,x.registers,x.samples),timing,d))
  private val fork=asyncChild("fork")(d => new ClickFork(
    new TelemetryReply(p.softwareSampleChannels.size,words.size),d))
  private val bank=asyncChild("register_bank")(d => new ClickBuffer(
    new TelemetryBank(p.config.gpioCount,words.size,p.softwareSampleChannels.size),timing,d))
  dontTouch(fork.left);dontTouch(bank.in)
  state.start.get:=start
  TwoPhase.connect(join.left,state.out);TwoPhase.connect(join.right,command)
  update.in.req:=join.out.req;join.out.ack:=update.in.ack
  update.in.bits.state:=join.out.bits.left;update.in.bits.command:=join.out.bits.right
  update.in.bits.registers:=view
  update.in.bits.samples.foreach(_ := sampleView)
  TwoPhase.connect(fork.in,update.out);TwoPhase.connect(reply,fork.right)
  val next=Wire(new TelemetryRegisters(p.config.gpioCount,words.size))
  next.output:=fork.right.bits.state.output;next.enable:=fork.right.bits.state.enable
  next.application.foreach(_ := fork.right.bits.state.application.get)
  // Receipt ACK toggles on both accepted phases, including revoked replies.
  // A revoked application publication recaptures its old registers; accepted
  // software samples still commit. The receipt holds its
  // authorization until a later acceptance; feedback prevents early reuse.
  bank.in.req:=reply.ack
  bank.in.bits.registers:=Mux(applyBank.getOrElse(true.B),next,view)
  bank.in.bits.samples.foreach(_ := fork.right.bits.state.samples.get)
  view:=bank.out.bits.registers
  sampleView:=bank.out.bits.samples.getOrElse(0.U.asTypeOf(sampleView))
  if(p.softwareSampleChannels.nonEmpty) {contract.endpoint("sample_view",sampleView)}
  bankComplete:=bank.out.req
  state.in.bits.credit:=false.B
  state.in.req:=bank.out.req
  bank.out.ack:=state.in.ack;fork.left.ack:=state.in.ack
  contract.endpoint("start",start);contract.endpoint("register_view",view)
  contract.endpoint("bank_complete",bankComplete)
  applyBank.foreach(contract.endpoint("apply_bank",_))

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
