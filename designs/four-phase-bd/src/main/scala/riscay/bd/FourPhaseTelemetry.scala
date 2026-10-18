// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation}
import chiselasync.protocol.FourPhase
import riscay._
import riscay.soc._

/** The existing Telemetry owner exposes its closed architectural bank. */
class TelemetryRegisters(gpios: Int, words: Int) extends Bundle {
  val output=UInt(gpios.max(1).W); val enable=UInt(gpios.max(1).W);val pending=UInt(6.W)
  val application=if(words>0) Some(Vec(words,UInt(32.W))) else None
}
/** Application/GPIO state lives only in the closed bank, not in the feedback token. */
class TelemetryFeedback(channels: Int) extends Bundle {
  val credit=Bool()
  val samples=if(channels>0) Some(Vec(channels,new Sample)) else None
}

class TelemetryUpdate(channels: Int,gpios: Int,words: Int) extends Bundle {
  val state=new TelemetryFeedback(channels)
  val command=new TelemetryCommand(channels)
  val registers=new TelemetryRegisters(gpios,words)
}

/** POR-owned native telemetry. Application reset remains an ordered command. */
class FourPhaseTelemetry(p: SocParameters, words: Vector[Int], domain: ResetDomain, qualifyCommit: Boolean=false) extends AsyncModule(domain) {
  val command = fourPhaseInput("command", new TelemetryCommand(p.config.measurements.size))
  val reply = fourPhaseOutput("reply", new TelemetryReply(p.config.measurements.size, words.size))
  val view=IO(Output(new TelemetryRegisters(p.config.gpioCount,words.size)))
  val commitAck=if(qualifyCommit) Some(IO(Input(Bool()))) else None
  commitAck.foreach(contract.endpoint("commit_ack",_))
  private val timing=OwnerTiming.base
  private val cell=ModelTime.ps(1000)
  private val resetRef=contract.endpoint("reset",reset)
  contract.endpoint("register_view",view)
  private val feedback=new TelemetryFeedback(p.config.measurements.size)
  private val initialFields: Seq[TelemetryFeedback => (Data,Data)]=Seq[TelemetryFeedback => (Data,Data)](_.credit -> false.B) ++
    (if(p.config.measurements.isEmpty) Seq.empty else Seq[TelemetryFeedback => (Data,Data)](
      _.samples.get -> Vec.Lit(p.config.measurements.indices.map(_ => (new Sample).Lit(
        _.value -> 0.U, _.valid -> false.B, _.calibrated -> false.B, _.age -> 0.U,
        _.sequence -> 0.U, _.never -> true.B, _.fault -> false.B)): _*)))
  private val initial=feedback.Lit(initialFields: _*)
  private val state=asyncChild("state")(d => new FourPhaseFifo(new TelemetryFeedback(p.config.measurements.size),1,
    timing,Seq(initial),cell,d))
  private val join=asyncChild("join")(d => new FourPhaseJoin(new TelemetryFeedback(p.config.measurements.size),
    new TelemetryCommand(p.config.measurements.size),timing,cell,d))
  private val update=asyncChild("update")(d => new FourPhaseStage(
    new TelemetryUpdate(p.config.measurements.size,p.config.gpioCount,words.size),
    new TelemetryReply(p.config.measurements.size,words.size),
    (x: TelemetryUpdate) => transition(x.state,x.command,x.registers),timing,d))
  private val fork=asyncChild("fork")(d => new FourPhaseFork(new TelemetryReply(p.config.measurements.size,words.size),2,cell,d))
  dontTouch(fork.out(0))
  FourPhase.connect(join.left,state.out); FourPhase.connect(join.right,command)
  update.in.req:=join.out.req;join.out.ack:=update.in.ack
  update.in.bits.state:=join.out.bits.left;update.in.bits.command:=join.out.bits.right
  update.in.bits.registers:=view

  // The existing receipt ACK rises after the actual work-clock acceptance
  // edge. Commit the closed bank once at that event; no periodic clock enters
  // this owner. Same-edge observers see the old bank, later edges the new bank.
  // This needs an ACK-to-Q min hold / next-edge max setup boundary constraint.
  private val stored=Module(new EventRegister(view.getWidth,cell))
  private val next=Wire(new TelemetryRegisters(p.config.gpioCount,words.size))
  next.output:=fork.out(1).bits.state.output;next.enable:=fork.out(1).bits.state.enable
  next.pending:=fork.out(1).bits.state.pending
  next.application.foreach(_ := fork.out(1).bits.state.application.get)
  stored.reset:=reset;stored.trigger:=commitAck.getOrElse(reply.ack);stored.d:=next.asUInt
  contract.primitive("register_bank",stored,Map("WIDTH"->BigInt(view.getWidth),"DELAY_FS"->BigInt(cell.fs),
    "RESET_VALUE"->BigInt(0)),resetRef,"sole application/GPIO state; closed outputs; one capture per committed update")
  view:=stored.q.asTypeOf(view)
  FourPhase.connect(fork.in,update.out)
  state.in.bits.credit:=false.B
  state.in.bits.samples.foreach(_ := fork.out(0).bits.state.samples.get)
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
  private def transition(s: TelemetryFeedback, c: TelemetryCommand, registers: TelemetryRegisters): TelemetryReply = {
    val r = WireDefault(0.U.asTypeOf(new TelemetryReply(p.config.measurements.size, words.size)))
    r.kind := c.kind; r.state.pending := registers.pending
    r.state.output := registers.output.pad(32); r.state.enable := registers.enable.pad(32)
    r.state.application.foreach(_ := registers.application.get)
    r.state.samples.foreach(_ := s.samples.get)
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
    n.pending := (Mux(c.kind === TelemetryKind.ResetApplication.U, 0.U, registers.pending) & ~c.clear) | c.events
    when(c.kind === TelemetryKind.Commit.U) {
      switch(c.offset) {
        is(24.U) { n.output := c.data & ((BigInt(1)<<p.config.gpioCount)-1).U(32.W) }
        is(28.U) { n.enable := c.data & ((BigInt(1)<<p.config.gpioCount)-1).U(32.W) }
        is(52.U) { for((word,index) <- words.zipWithIndex) {
          when(c.appIndex === word.U) { n.application.get(index) := c.data }
        } }
      }
    }
    for(i <- p.config.measurements.indices) {
      val capture = c.captures.get(i)
      val old = s.samples.get(i); val next = n.samples.get(i)
      val aged = old.age +& c.elapsedUpper
      next.age := Mux(aged(32), "hffffffff".U, aged(31,0))
      when(capture.seen) {
        next.sequence := old.sequence + capture.count
        next.valid := capture.valid; next.fault := !capture.valid
        next.calibrated := capture.valid && capture.calibrated
      }
      when(capture.hadValid) {
        next.value := capture.value; next.never := false.B; next.age := capture.tailAge
      }
    }
    r
  }
}
