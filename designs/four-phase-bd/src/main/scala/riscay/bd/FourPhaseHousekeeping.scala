// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ModelTime}
import chiselasync.protocol.FourPhase
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation, PassiveDataAllowance}
import riscay.soc._

/** Effects only; consumed is captured at the actual clocked receiving edge. */
class HousekeepingEffects extends Bundle {
  val recovery=Bool();val consumed=UInt(32.W)
  val timeValid=Bool();val tick=Bool();val due=Bool();val leaseExpired=Bool()
  val startAdc=Bool();val kick=Bool();val resetApplication=Bool();val cpuCompletion=Bool()
}

/** Native time, application timer/lease, kick and acquisition coordination.
  * Commands carry ordered observations, never a clocked copy of policy state.
  * State credit is retired only when the publication consumer accepts the reply.
  */
class FourPhaseHousekeeping(p: SocParameters,domain: ResetDomain) extends AsyncModule(domain) {
  val command=fourPhaseInput("command",new HousekeepingCommand)
  val reply=fourPhaseOutput("reply",new HousekeepingEffects)

  private val timing=OwnerTiming.base
  private val cell=ModelTime.ps(1000)
  val view=IO(Output(new HousekeepingState))
  private val resetRef=contract.endpoint("reset",reset)
  contract.endpoint("state_view",view)
  private val initial=HousekeepingState.initial(p).litValue
  private val bank=Module(new EventRegister(view.getWidth,cell,initial))
  bank.reset:=reset
  contract.primitive("state_bank",bank,Map("WIDTH"->BigInt(view.getWidth),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->initial),resetRef,
    "sole retained Housekeeping state; capture only on accepted reply ACK")
  view:=bank.q.asTypeOf(view)
  private val state=asyncChild("state")(d => new FourPhaseFifo(Bool(),1,timing,Seq(false.B),cell,d))
  private val join=asyncChild("join")(d => new FourPhaseJoin(Bool(),new HousekeepingCommand,timing,cell,d))
  private val update=asyncChild("update")(d => new FourPhaseStage(
    new HousekeepingEffects,new HousekeepingEffects,(x: HousekeepingEffects) => x,timing,d))
  FourPhase.connect(join.left,state.out); FourPhase.connect(join.right,command)
  update.in.req:=join.out.req
  private val commandReturn=Module(new AsymmetricCElement(2,0,0,cell))
  commandReturn.reset:=reset;commandReturn.common:=Cat(update.in.ack,reply.ack)
  commandReturn.rising:=0.U;commandReturn.falling:=0.U
  contract.primitive("command_return",commandReturn,Map("COMMON"->BigInt(2),"RISING"->BigInt(0),"FALLING"->BigInt(0),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,"held command through bank capture and complete reply return")
  join.out.ack:=commandReturn.q
  // Keep one transform in this owner: preserving the identity-stage hierarchy
  // must not duplicate arithmetic shared by the state and publication effects.
  private val next=transition(view,join.out.bits.right)
  update.in.bits:=effects(next)
  private val operands=WireDefault(UInt((view.getWidth+join.out.bits.right.getWidth).W),
    Cat(view.asUInt,join.out.bits.right.asUInt))
  contract.endpoint("effect_source",operands);contract.endpoint("effect_input",update.in.bits)
  contract.dataPathTiming("effect_transform_path","effect_source","effect_input",timing,
    "full held-command/closed-state effect transform; compose with update payload capture, not identity-stage input only",
    delayOwner=Seq("update"),delayCell="data_delay")
  bank.trigger:=reply.ack
  bank.d:=PassiveDataAllowance(this,"state_data_delay",next.state.asUInt,timing.dataDelay.model,resetRef)
  contract.endpoint("state_data_source",operands);contract.endpoint("state_data",bank.d)
  contract.endpoint("command_capture",join.out.req);contract.endpoint("bank_capture",bank.trigger)
  contract.dataPathTiming("state_data_path","state_data_source","state_data",timing,
    "full held-command/closed-state transform, actual receiving ACK capture",delayCell="state_data_delay")
  contract.setupHold("state_aperture","command_capture","state_data_source","state_data","bank_capture",
    "state_view",ModelTime.ps(100),ModelTime.ps(100))
  // Relative bank capture-to-feedback ordering. This digital model is not a
  // physical target: size this owner's own path at each corner before adoption.
  private val settled=Module(new ControlGate(1,GateOperation.Buffer,ModelTime.ps(10000)))
  settled.reset:=reset;settled.a:=reply.ack.asUInt;settled.b:=0.U
  contract.primitive("bank_guard",settled,Map("WIDTH"->BigInt(1),"OP"->BigInt(0),
    "DELAY_FS"->BigInt(10000000),"RESET_VALUE"->BigInt(0)),resetRef,
    "relative state-bank capture precedes feedback credit; both return edges retained")
  state.in.bits:=false.B;state.in.req:=settled.q.asBool
  update.out.ack:=state.in.ack;reply.req:=update.out.req;reply.bits:=update.out.bits
  dontTouch(state.in);dontTouch(update.out)

  private def effects(r: HousekeepingReply): HousekeepingEffects = {
    val out=Wire(new HousekeepingEffects)
    out.recovery:=r.recovery;out.consumed:=r.state.consumed
    out.timeValid:=r.timeValid;out.tick:=r.tick;out.due:=r.due;out.leaseExpired:=r.leaseExpired
    out.startAdc:=r.startAdc;out.kick:=r.kick;out.resetApplication:=r.resetApplication
    out.cpuCompletion:=r.cpuCompletion;out
  }

  private def transition(s: HousekeepingState, c: HousekeepingCommand): HousekeepingReply = {
    val r=WireDefault(0.U.asTypeOf(new HousekeepingReply)); r.state:=s
    r.recovery := c.recovery
    val n=r.state; val elapsed=c.elapsed; val tick=elapsed =/= 0.U || c.elapsedOverflow
    r.timeValid:=c.timeValid; r.tick:=tick
    r.resetApplication:=c.resetApplication; r.cpuCompletion:=c.cpuCompletion
    n.now:=s.now+elapsed
    when(c.timeValid) { n.consumed:=c.target }
    val expired=s.lease =/= 0.U && (c.elapsedOverflow || elapsed >= s.lease)
    n.lease:=Mux(expired,0.U,Mux(elapsed >= s.lease,0.U,s.lease-elapsed))
    r.leaseExpired:=tick && expired
    val replace=c.write && c.offset === 8.U
    when(replace) { n.deadline:=c.data; n.armed:=true.B }
    // Test crossing from the old time as well as already-due state: an elapsed
    // batch can span the signed comparison range or a complete counter wrap.
    val oldDue=(s.now-s.deadline).asSInt >= 0.S || c.elapsedOverflow || elapsed >= (s.deadline-s.now)
    r.due:=Mux(replace,(n.now-c.data).asSInt >= 0.S,s.armed && oldDue)
    when(r.due) { n.armed:=false.B }
    when(c.waitAccepted) { n.lease:=0.U }
    when(c.write && c.offset === 60.U) { n.lease:=c.data }
    when(c.write && c.offset === 56.U) { n.wakeMask:=c.data }
    // Policy emits a retained kick effect. Phase/ACK handling belongs to the
    // independent LF crossing, so ACK retries cannot serialize timer updates.
    r.kick:=(c.write && c.offset === 32.U) || (tick && (c.resetApplication || (c.parked && (!c.started || s.lease =/= 0.U))))
    if(p.lowPower.nonEmpty && p.adc.nonEmpty) {
      r.startAdc:=s.requested && !c.adcBusy
      when(r.startAdc) { n.requested:=false.B }
      when(c.discard) { n.requested:=true.B }
      when(tick) {
        when(c.elapsedOverflow || elapsed > s.countdown) { n.countdown:=s.period-1.U; n.requested:=true.B }
          .otherwise { n.countdown:=s.countdown-elapsed }
      }
      // Apply the old pending value before recording a simultaneous new write.
      when(tick && s.periodPending && !c.adcBusy && !s.requested) {
        n.period:=s.nextPeriod; n.countdown:=s.nextPeriod-1.U
        n.periodPending:=false.B; n.requested:=true.B
      }
      when(c.periodUpdate) { n.nextPeriod:=c.period; n.periodPending:=true.B }
    }
    when(c.resetApplication) {
      n.deadline:=0.U; n.armed:=false.B; n.lease:=0.U; n.wakeMask:=15.U
      r.due:=false.B; r.leaseExpired:=false.B
    }
    r
  }
}
