// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel

/** POR transport with a synchronous capture stop. close belongs to this clock
  * domain (or its timed related service clock), never the raw watchdog signal.
  * closed proves a complete edge without a payload capture. The caller keeps
  * native producers intact until every receiver has closed. Only after that
  * may it reset the native island and assert rebase while keeping close high.
  * Neither close nor rebase clears payload storage. These are explicit clocked
  * endpoint bridges, not native logic or a physical timing qualification.
  */
abstract class FourPhaseQuiescingBridge(domain: ResetDomain) extends ClockedBridge(domain,2) {
  val close=IO(Input(Bool())); val rebase=IO(Input(Bool())); val closed=IO(Output(Bool()))
  val rebased=IO(Output(Bool()))
  withClockAndReset(clock,localReset) {
    val stopped=RegNext(close,false.B)
    closed:=stopped; rebased:=RegNext(rebase,false.B)
    when(!localReset.asBool) { assert(!rebase || (close && stopped),"BD_BRIDGE_REBASE_BEFORE_CLOSE") }
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

class FourPhaseQuiescingToDecoupled[T <: Data](gen: T,domain: ResetDomain)
    extends FourPhaseQuiescingBridge(domain) {
  val channel=new Channel(gen,resetDomain)
  val in=IO(Flipped(channel.bundled)); val out=IO(channel.decoupled)
  private val request=phase(in.req)
  withClockAndReset(clock,localReset) {
    val state=RegInit(0.U(2.W)); val acknowledge=RegInit(false.B)
    val data=RegInit(0.U.asTypeOf(gen))
    in.ack:=acknowledge; out.bits:=data
    out.valid:=state === 2.U && !close && !localReset.asBool
    when(rebase) { state:=0.U; acknowledge:=false.B }
      .elsewhen(!close) {
        switch(state) {
          is(0.U) { when(request) { state:=1.U } }
          is(1.U) { data:=in.bits; state:=2.U }
          is(2.U) { when(out.fire) { acknowledge:=true.B; state:=3.U } }
          is(3.U) { when(!request) { acknowledge:=false.B; state:=0.U } }
        }
      }
  }
  contract.capacity(1); contract.channel("in",in,"input")
  contract.clockedChannel("out",out,clock,channel,"output")
}

class DecoupledToFourPhaseQuiescing[T <: Data](gen: T,domain: ResetDomain)
    extends FourPhaseQuiescingBridge(domain) {
  val channel=new Channel(gen,resetDomain)
  val in=IO(Flipped(channel.decoupled)); val out=IO(channel.bundled)
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
          is(1.U) { request:=true.B; state:=2.U }
          is(2.U) { when(acknowledge) { request:=false.B; state:=3.U } }
          is(3.U) { when(!acknowledge) { state:=0.U } }
        }
      }
  }
  contract.capacity(1); contract.clockedChannel("in",in,clock,channel,"input")
  contract.channel("out",out,"output")
}
