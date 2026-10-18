// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{ClickTiming,ModelTime}
import chiselasync.protocol.TwoPhase
import riscay.soc._

/** Native conversion ownership, frame definition, bit assembly and priming.
  * A fixed wire recipe is immutable throughout POR; no clock controls the
  * protocol state, scaling or retirement. The clocked player only times slots.
  */
class ClickSpiAdc(p: AdcParameters,domain: ResetDomain) extends AsyncModule(domain) {
  val timestamp=IO(Input(UInt(64.W)))
  val sampleView=IO(Output(new SampleRecord))
  val sampleComplete=IO(Output(Bool()))
  val command=twoPhaseInput("command",Bool())
  val reply=twoPhaseOutput("reply",new SpiResult)
  val wave=twoPhaseOutput("wave",Bool())
  val capture=twoPhaseInput("capture",new SpiCapture)
  val program=IO(Output(new SpiWaveform)); dontTouch(program)
  // Mode 0: sixteen rising captures and sixteen falling edges. Terminal CS
  // release shares the final falling edge, after its complete high half-phase.
  program.initialCsN:=false.B; program.initialSclk:=false.B
  program.occupied:="hffffffff".U; program.csN:="h80000000".U; program.sclk:="h55555555".U
  private val timing=OwnerTiming.base
  private val cell=ModelTime.ps(1000)
  private val state=asyncChild("state")(d => new PhaseDecoupledClickBuffer(Bool(),timing,Some(false.B),d))
  val start=IO(Input(Bool())); state.start.get:=start; contract.endpoint("start",start)
  private val owner=asyncChild("owner")(d => new ClickJoin(Bool(),Bool(),timing,d))
  private val issue=asyncChild("issue")(d => new ClickFork(new Joined(Bool(),Bool()),d))
  private val captured=asyncChild("captured")(d => new ClickJoin(new Joined(Bool(),Bool()),new SpiCapture,timing,d))
  TwoPhase.connect(owner.left,state.out); TwoPhase.connect(owner.right,command)
  TwoPhase.connect(issue.in,owner.out)
  wave.req:=issue.left.req; wave.bits:=issue.left.bits.right
  issue.left.ack:=wave.ack
  TwoPhase.connect(captured.left,issue.right); TwoPhase.connect(captured.right,capture)
  dontTouch(issue.left)
  // Keep capture field names in the exported ABI: a 33-bit CPU response
  // has the same structural shape but a different declared payload schema.
  chisel3.aop.Select.getDeep(captured) { case m: RawModule => Seq(m); case _ => Seq.empty }.foreach(chisel3.experimental.doNotDedup(_))
  private val assemble=asyncChild("assemble")(d => new ClickStage(
    new Joined(new Joined(Bool(),Bool()),new SpiCapture),new SpiRaw,
    (x: Joined[Joined[Bool,Bool],SpiCapture]) => {
      val r=Wire(new SpiRaw); r.primed:=x.left.left; r.complete:=x.right.complete
      // Slot zero is the first rising edge. Four leading bits are ignored.
      r.raw:=Cat((4 until 16).map(i => x.right.samples(2*i))); r
    },timing,d))
  private val split=asyncChild("split")(d => new ClickFork(new SpiRaw,d))
  private val scale=asyncChild("scale")(d => new ClickSample(p.numerator,p.denominator,d))
  private val scaled=asyncChild("scaled")(d => new ClickJoin(new SpiRaw,UInt(32.W),timing,d))
  TwoPhase.connect(assemble.in,captured.out); TwoPhase.connect(split.in,assemble.out)
  scale.command.req:=split.left.req; scale.command.bits:=split.left.bits.raw
  split.left.ack:=scale.command.ack
  dontTouch(split.left)
  TwoPhase.connect(scaled.left,split.right); TwoPhase.connect(scaled.right,scale.reply)
  private val finish=asyncChild("finish")(d => new ClickStage(new SpiFinishWork,new SpiResult,
    (x: SpiFinishWork) => {
      val r=Wire(new SpiResult); r.nextPrimed:=x.raw.primed || x.raw.complete
      r.publish:=x.raw.primed && x.raw.complete
      r.sample:=x.sample
      r.sample.value:=(x.scaled+p.offset.S(32.W).asUInt)(31,0)
      when(r.publish) {
        r.sample.timestamp:=x.timestamp;r.sample.sequence:=x.sample.sequence+1.U
        r.sample.valid:=true.B;r.sample.calibrated:=p.calibrated.B;r.sample.seen:=true.B;r.sample.fault:=false.B
      }
      r
    },timing,d))
  finish.in.req:=scaled.out.req;scaled.out.ack:=finish.in.ack
  finish.in.bits.raw:=scaled.out.bits.left;finish.in.bits.scaled:=scaled.out.bits.right
  finish.in.bits.sample:=sampleView;finish.in.bits.timestamp:=timestamp
  val bank=asyncChild("sample_bank")(d => new ClickBuffer(new SampleRecord,timing,d))
  bank.in.req:=reply.ack;bank.in.bits:=Mux(finish.out.bits.publish,finish.out.bits.sample,sampleView)
  sampleView:=bank.out.bits;sampleComplete:=bank.out.req
  bank.out.ack:=state.in.ack
  // No next waveform/sequence update before the closed sample bank publishes.
  state.in.bits:=finish.out.bits.nextPrimed;state.in.req:=sampleComplete
  finish.out.ack:=state.in.ack;reply.req:=finish.out.req;reply.bits:=finish.out.bits
  dontTouch(state.in);dontTouch(finish.out)
  contract.endpoint("timestamp",timestamp);contract.endpoint("sample_view",sampleView)
  contract.endpoint("sample_complete",sampleComplete)
  contract.endpoint("reset",reset)
}

/** POR-only admission/publication plus a fixed-rate waveform player.
  * No ADC bit count, field extraction, priming or scaling state lives here.
  * The native pin recipe is POR-immutable. Only its playback position and
  * all 32 observations are retained at this physical boundary.
  */
class SpiAdc(p: AdcParameters,autonomous: Boolean,domain: ResetDomain) extends ClockedBridge(domain,2) {
  val io=IO(new SpiAdcPort); dontTouch(io)
  val miso=IO(Input(Bool())); val csN=IO(Output(Bool())); val sclk=IO(Output(Bool()))
  val native=asyncChild("native")(d => new ClickSpiAdc(p,d))
  native.start:= !localReset.asBool
  val recipe=Wire(new SpiWaveform); recipe:=native.program; dontTouch(recipe)
  private val command=asyncChild("command_bridge")(d => new DecoupledToClick(Bool(),d))
  private val reply=asyncChild("reply_bridge")(d => new ClickServiceReplyReceipt(new SpiResult, d))
  private val wave=asyncChild("wave_bridge")(d => new ClickServiceReplyReceipt(Bool(), d))
  private val capture=asyncChild("capture_bridge")(d => new DecoupledToClick(new SpiCapture,d))
  chisel3.experimental.doNotDedup(capture)
  Seq(command,reply,wave,capture).foreach(_.clock:=clock)
  TwoPhase.connect(native.command,command.out); TwoPhase.connect(reply.in,native.reply)
  TwoPhase.connect(wave.in,native.wave); TwoPhase.connect(native.capture,capture.out)
  dontTouch(wave.out); dontTouch(reply.out)
  private val returned=synchronizedControl(reply.in.req === reply.in.ack)
  private val waveReturned=synchronizedControl(wave.in.req === wave.in.ack)
  val bankComplete=synchronizedControl(native.sampleComplete)
  io.sampleReady:=bankComplete === reply.in.ack
  io.sample:=native.sampleView
  withClockAndReset(clock,localReset) {
    val active=RegInit(false.B); val pending=RegInit(false.B)
    val interval=RegInit(0.U(log2Ceil(p.intervalCycles).W))
    // One admission timestamp is held through conversion and complete native
    // return. It replaces the per-conversion periodic age accumulator.
    val admissionTime=RegInit(0.U(64.W));native.timestamp:=admissionTime
    val slot=RegInit(0.U(5.W)); val playing=RegInit(false.B)
    // Preserve the recipe's original highest-occupied-slot semantics,
    // including holes or an empty recipe; do not hard-code 32 transfers.
    val remaining=recipe.occupied >> slot
    val divider=RegInit(0.U(log2Ceil(p.halfPeriodCycles).max(1).W))
    val cs=RegInit(true.B); val clockLevel=RegInit(false.B)
    val samples=RegInit(0.U(32.W)); val sampled=RegInit(false.B); val complete=RegInit(false.B)
    val drained=returned && waveReturned && command.in.ready && capture.in.ready && !playing && !sampled && io.sampleReady
    val launch= !active && drained && (if(autonomous) interval === 0.U else io.start)
    command.in.valid:=pending; command.in.bits:=active
    when(launch) { active:=true.B; pending:=true.B; interval:=(p.intervalCycles-1).U; admissionTime:=io.upperTime }
      .elsewhen(!active && drained) { when(interval =/= 0.U) { interval:=interval-1.U } }
    when(command.in.fire) { pending:=false.B }
    wave.out.ready:=active && !playing && !sampled && io.sampleReady && !localReset.asBool
    when(wave.out.fire) {
      slot:=0.U; playing:=recipe.occupied.orR
      cs:=recipe.initialCsN; clockLevel:=recipe.initialSclk
      divider:=0.U; samples:=0.U; complete:=false.B
    }
    when(playing) {
      when(divider === (p.halfPeriodCycles-1).U) {
        divider:=0.U; cs:=recipe.csN(slot); clockLevel:=recipe.sclk(slot)
        samples:=Cat(miso,samples(31,1))
        when(remaining === 1.U) { playing:=false.B; sampled:=true.B; complete:=true.B }
          .otherwise { slot:=slot+1.U }
      }.otherwise { divider:=divider+1.U }
    }
    capture.in.valid:=sampled; capture.in.bits.samples:=samples; capture.in.bits.complete:=complete
    when(capture.in.fire) { sampled:=false.B }
    reply.out.ready:=active
    when(reply.out.fire) { active:=false.B }
    io.done:=reply.out.fire; io.result.valid:=io.done && reply.out.bits.publish
    io.result.bits.value:=reply.out.bits.sample.value; io.result.bits.valid:=reply.out.bits.publish
    io.result.bits.calibrated:=p.calibrated.B
    io.busy:=active || pending || !drained || localReset.asBool
    csN:=cs; sclk:=clockLevel
    dontTouch(slot); dontTouch(playing); dontTouch(samples)
  }
  contract.endpoint("reset",reset)
}
