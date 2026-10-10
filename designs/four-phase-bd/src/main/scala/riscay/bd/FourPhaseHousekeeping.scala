// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ModelTime}
import chiselasync.protocol.FourPhase
import riscay.soc._

/** Native time, application timer/lease, kick and acquisition coordination.
  * Commands carry ordered observations, never a clocked copy of policy state.
  * State credit is retired only when the publication consumer accepts the reply.
  */
class FourPhaseHousekeeping(p: SocParameters,domain: ResetDomain) extends AsyncModule(domain) {
  val command=fourPhaseInput("command",new HousekeepingCommand)
  val reply=fourPhaseOutput("reply",new HousekeepingReply)

  private val timing=BundledTiming.Simulation
  private val cell=ModelTime.ps(1000)
  private val state=asyncChild("state")(d => new FourPhaseFifo(new HousekeepingState,1,timing,Seq(HousekeepingState.initial(p)),cell,d))
  private val join=asyncChild("join")(d => new FourPhaseJoin(new HousekeepingState,new HousekeepingCommand,timing,cell,d))
  private val update=asyncChild("update")(d => new FourPhaseStage(
    new Joined(new HousekeepingState,new HousekeepingCommand),new HousekeepingReply,
    (x: Joined[HousekeepingState,HousekeepingCommand]) => transition(x.left,x.right),timing,d))
  FourPhase.connect(join.left,state.out); FourPhase.connect(join.right,command)
  FourPhase.connect(update.in,join.out)
  state.in.bits:=update.out.bits.state; state.in.req:=reply.ack
  update.out.ack:=state.in.ack; reply.req:=update.out.req; reply.bits:=update.out.bits
  dontTouch(state.in); dontTouch(update.out)

  contract.endpoint("reset",reset)

  private def transition(s: HousekeepingState, c: HousekeepingCommand): HousekeepingReply = {
    val r=WireDefault(0.U.asTypeOf(new HousekeepingReply)); r.state:=s
    val n=r.state; val elapsed=c.elapsed(0); val tick=elapsed =/= 0.U || c.elapsedOverflow
    r.timeValid:=c.timeValid; r.tick:=tick; r.single:=c.single; r.elapsed:=c.elapsed
    r.resetApplication:=c.resetApplication; r.cpuCompletion:=c.cpuCompletion
    n.now:=s.now+elapsed; n.boardNow:=s.boardNow+c.elapsed(1)
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
    r.kick:=(c.write && c.offset === 32.U) || (tick && (!c.started || (c.parked && s.lease =/= 0.U)))
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
