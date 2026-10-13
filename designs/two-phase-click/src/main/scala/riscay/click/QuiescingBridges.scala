// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel

/** POR toggle transport with synchronous close/rebase. close is a timed local
  * or related-service control, never raw watchdog reset. closed acknowledges
  * an edge with no payload capture; all native producers remain intact until
  * every receiver closes. Rebase is permitted only during that closed interval
  * after coordinated native reset, and never clears the payload. The independent
  * native toggle histories below have no four-phase conversion. These remain
  * clocked endpoint bridges with outstanding physical timing obligations.
  */
abstract class ClickQuiescingBridge(domain: ResetDomain) extends ClockedBridge(domain,2) {
  val close=IO(Input(Bool())); val rebase=IO(Input(Bool())); val closed=IO(Output(Bool()))
  val rebased=IO(Output(Bool()))
  withClockAndReset(clock,localReset) {
    val stopped=RegNext(close,false.B)
    closed:=stopped; rebased:=RegNext(rebase,false.B)
    when(!localReset.asBool) { assert(!rebase || (close && stopped),"CLICK_BRIDGE_REBASE_BEFORE_CLOSE") }
  }
  protected def phase(input: Bool): Bool = withClockAndReset(clock,localReset) {
    val first=RegInit(false.B); val second=RegInit(false.B)
    when(rebase) { first:=false.B; second:=false.B }
      .elsewhen(!close) { first:=input; second:=first }
    Seq(first,second).foreach(dontTouch(_)); second
  }
  contract.endpoint("close",close); contract.endpoint("closed",closed)
  contract.endpoint("rebase",rebase); contract.endpoint("rebased",rebased); contract.endpoint("reset",reset)
}

class ClickQuiescingToDecoupled[T <: Data](gen: T,domain: ResetDomain)
    extends ClickQuiescingBridge(domain) {
  val channel=new Channel(gen,resetDomain)
  val in=IO(Flipped(channel.twoPhase)); val out=IO(channel.decoupled)
  private val request=phase(in.req)
  withClockAndReset(clock,localReset) {
    val state=RegInit(0.U(2.W)); val acknowledge=RegInit(false.B)
    val data=RegInit(0.U.asTypeOf(gen))
    in.ack:=acknowledge; out.bits:=data
    out.valid:=state === 2.U && !close && !localReset.asBool
    when(rebase) { state:=0.U; acknowledge:=false.B }
      .elsewhen(!close) {
        switch(state) {
          is(0.U) { when(request =/= acknowledge) { state:=1.U } }
          is(1.U) { data:=in.bits; state:=2.U }
          is(2.U) { when(out.fire) { acknowledge:=request; state:=0.U } }
        }
      }
  }
  contract.capacity(1); contract.twoPhaseChannel("in",in,"input")
  contract.clockedChannel("out",out,clock,channel,"output")
}

class DecoupledToClickQuiescing[T <: Data](gen: T,domain: ResetDomain)
    extends ClickQuiescingBridge(domain) {
  val channel=new Channel(gen,resetDomain)
  val in=IO(Flipped(channel.decoupled)); val out=IO(channel.twoPhase)
  private val acknowledge=phase(out.ack)
  withClockAndReset(clock,localReset) {
    val state=RegInit(0.U(2.W)); val request=RegInit(false.B)
    val data=RegInit(0.U.asTypeOf(gen))
    in.ready:=state === 0.U && !close && !localReset.asBool
    out.bits:=data; out.req:=request
    when(rebase) { state:=0.U; request:=false.B }
      .elsewhen(!close) {
        switch(state) {
          is(0.U) { when(in.fire) { data:=in.bits; state:=1.U } }
          is(1.U) { request:= !request; state:=2.U }
          is(2.U) { when(acknowledge === request) { state:=0.U } }
        }
      }
  }
  contract.capacity(1); contract.clockedChannel("in",in,clock,channel,"input")
  contract.twoPhaseChannel("out",out,"output")
}
