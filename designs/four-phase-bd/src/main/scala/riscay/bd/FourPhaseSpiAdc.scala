// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ModelTime}
import chiselasync.protocol.FourPhase
import riscay.soc._

/** Native conversion ownership, frame definition, bit assembly and priming.
  * A fixed wire recipe is immutable throughout POR; no clock controls the
  * protocol state, scaling or retirement. The clocked player only times slots.
  */
class FourPhaseSpiAdc(p: AdcParameters,domain: ResetDomain) extends AsyncModule(domain) {
  val command=fourPhaseInput("command",Bool())
  val reply=fourPhaseOutput("reply",new SpiResult)
  val wave=fourPhaseOutput("wave",Bool())
  val capture=fourPhaseInput("capture",new SpiCapture)
  val program=IO(Output(new SpiWaveform)); dontTouch(program)
  // Mode 0: sixteen rising captures and sixteen falling edges. Terminal CS
  // release shares the final falling edge, after its complete high half-phase.
  program.initialCsN:=false.B; program.initialSclk:=false.B
  program.occupied:="hffffffff".U; program.csN:="h80000000".U; program.sclk:="h55555555".U
  private val timing=BundledTiming.Simulation
  private val cell=ModelTime.ps(1000)
  private val state=asyncChild("state")(d => new FourPhaseFifo(Bool(),1,timing,Seq(false.B),cell,d))

  private val owner=asyncChild("owner")(d => new FourPhaseJoin(Bool(),Bool(),timing,cell,d))
  private val issue=asyncChild("issue")(d => new FourPhaseFork(new Joined(Bool(),Bool()),2,cell,d))
  private val captured=asyncChild("captured")(d => new FourPhaseJoin(new Joined(Bool(),Bool()),new SpiCapture,timing,cell,d))
  FourPhase.connect(owner.left,state.out); FourPhase.connect(owner.right,command)
  FourPhase.connect(issue.in,owner.out)
  wave.req:=issue.out(0).req; wave.bits:=issue.out(0).bits.right
  issue.out(0).ack:=wave.ack
  FourPhase.connect(captured.left,issue.out(1)); FourPhase.connect(captured.right,capture)
  dontTouch(issue.out(0))
  // Keep capture field names in the exported ABI: a 33-bit CPU response
  // has the same structural shape but a different declared payload schema.
  chisel3.aop.Select.getDeep(captured) { case m: RawModule => Seq(m); case _ => Seq.empty }.foreach(chisel3.experimental.doNotDedup(_))
  private val assemble=asyncChild("assemble")(d => new FourPhaseStage(
    new Joined(new Joined(Bool(),Bool()),new SpiCapture),new SpiRaw,
    (x: Joined[Joined[Bool,Bool],SpiCapture]) => {
      val r=Wire(new SpiRaw); r.primed:=x.left.left; r.complete:=x.right.complete
      // Slot zero is the first rising edge. Four leading bits are ignored.
      r.raw:=Cat((4 until 16).map(i => x.right.samples(2*i))); r
    },timing,d))
  private val split=asyncChild("split")(d => new FourPhaseFork(new SpiRaw,2,cell,d))
  private val scale=asyncChild("scale")(d => new FourPhaseSample(p.numerator,p.denominator,d))
  private val scaled=asyncChild("scaled")(d => new FourPhaseJoin(new SpiRaw,UInt(32.W),timing,cell,d))
  FourPhase.connect(assemble.in,captured.out); FourPhase.connect(split.in,assemble.out)
  scale.command.req:=split.out(0).req; scale.command.bits:=split.out(0).bits.raw
  split.out(0).ack:=scale.command.ack
  dontTouch(split.out(0))
  FourPhase.connect(scaled.left,split.out(1)); FourPhase.connect(scaled.right,scale.reply)
  private val finish=asyncChild("finish")(d => new FourPhaseStage(new Joined(new SpiRaw,UInt(32.W)),new SpiResult,
    (x: Joined[SpiRaw,UInt]) => {
      val r=Wire(new SpiResult); r.nextPrimed:=x.left.primed || x.left.complete
      r.publish:=x.left.primed && x.left.complete
      r.value:=(x.right+p.offset.S(32.W).asUInt)(31,0); r
    },timing,d))
  FourPhase.connect(finish.in,scaled.out)
  // Retire only on consumer acceptance. No next waveform may issue before it.
  state.in.bits:=finish.out.bits.nextPrimed; state.in.req:=reply.ack
  finish.out.ack:=state.in.ack; reply.req:=finish.out.req; reply.bits:=finish.out.bits
  dontTouch(state.in); dontTouch(finish.out)
  contract.endpoint("reset",reset)
}

/** POR-only admission/publication plus a fixed-rate waveform player.
  * No ADC bit count, field extraction, priming or scaling state lives here.
  * The complete pin recipe and all 32 observations are retained until consumed.
  */
class SpiAdc(p: AdcParameters,autonomous: Boolean,domain: ResetDomain) extends ClockedBridge(domain,2) {
  val io=IO(new SpiAdcPort); dontTouch(io)
  val miso=IO(Input(Bool())); val csN=IO(Output(Bool())); val sclk=IO(Output(Bool()))
  val native=asyncChild("native")(d => new FourPhaseSpiAdc(p,d))

  val recipe=Wire(new SpiWaveform); recipe:=native.program; dontTouch(recipe)
  private val command=asyncChild("command_bridge")(d => new DecoupledToFourPhase(Bool(),2,d))
  private val reply=asyncChild("reply_bridge")(d => new FourPhaseToDecoupled(new SpiResult,2,d))
  private val wave=asyncChild("wave_bridge")(d => new FourPhaseToDecoupled(Bool(),2,d))
  private val capture=asyncChild("capture_bridge")(d => new DecoupledToFourPhase(new SpiCapture,2,d))
  chisel3.experimental.doNotDedup(capture)
  Seq(command,reply,wave,capture).foreach(_.clock:=clock)
  FourPhase.connect(native.command,command.out); FourPhase.connect(reply.in,native.reply)
  FourPhase.connect(wave.in,native.wave); FourPhase.connect(native.capture,capture.out)
  dontTouch(wave.out); dontTouch(reply.out)
  private val returned=synchronizedControl(!reply.in.req) && !reply.in.ack
  private val waveReturned=synchronizedControl(!wave.in.req) && !wave.in.ack
  withClockAndReset(clock,localReset) {
    val active=RegInit(false.B); val pending=RegInit(false.B)
    val interval=RegInit(0.U(log2Ceil(p.intervalCycles).W))
    val age=RegInit(0.U(32.W)); val aged=age +& io.ageStep
    val ageNow=Mux(aged(32),"hffffffff".U,aged(31,0))
    val occupied=RegInit(0.U(32.W)); val csLevels=Reg(UInt(32.W)); val clockLevels=Reg(UInt(32.W))
    val divider=RegInit(0.U(log2Ceil(p.halfPeriodCycles).max(1).W))
    val cs=RegInit(true.B); val clockLevel=RegInit(false.B)
    val samples=RegInit(0.U(32.W)); val sampled=RegInit(false.B); val complete=RegInit(false.B)
    val drained=returned && waveReturned && command.in.ready && capture.in.ready && !occupied.orR && !sampled
    val launch= !active && drained && (if(autonomous) interval === 0.U else io.start)
    command.in.valid:=pending; command.in.bits:=active
    when(launch) { active:=true.B; pending:=true.B; interval:=(p.intervalCycles-1).U; age:=0.U }
      .elsewhen(!active && drained) { when(interval =/= 0.U) { interval:=interval-1.U } }
    when(active) { age:=ageNow }
    when(command.in.fire) { pending:=false.B }
    wave.out.ready:=active && !occupied.orR && !sampled && !localReset.asBool
    when(wave.out.fire) {
      occupied:=recipe.occupied; csLevels:=recipe.csN; clockLevels:=recipe.sclk
      cs:=recipe.initialCsN; clockLevel:=recipe.initialSclk
      divider:=0.U; samples:=0.U; complete:=false.B
    }
    when(occupied.orR) {
      when(divider === (p.halfPeriodCycles-1).U) {
        divider:=0.U; cs:=csLevels(0); clockLevel:=clockLevels(0)
        csLevels:=csLevels >> 1; clockLevels:=clockLevels >> 1
        samples:=Cat(miso,samples(31,1)); occupied:=occupied >> 1
        when(occupied === 1.U) { sampled:=true.B; complete:=true.B }
      }.otherwise { divider:=divider+1.U }
    }
    capture.in.valid:=sampled; capture.in.bits.samples:=samples; capture.in.bits.complete:=complete
    when(capture.in.fire) { sampled:=false.B }
    reply.out.ready:=active
    when(reply.out.fire) { active:=false.B }
    io.done:=reply.out.fire; io.result.valid:=io.done && reply.out.bits.publish
    io.result.bits.value:=reply.out.bits.value; io.result.bits.valid:=reply.out.bits.publish
    io.result.bits.calibrated:=p.calibrated.B; io.age:=ageNow
    io.busy:=active || pending || !drained || localReset.asBool
    csN:=cs; sclk:=clockLevel
    dontTouch(occupied); dontTouch(samples)
  }
  contract.endpoint("reset",reset)
}
