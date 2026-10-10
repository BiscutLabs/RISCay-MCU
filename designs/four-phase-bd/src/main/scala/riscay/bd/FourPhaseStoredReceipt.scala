// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel

/** Narrow crossing for the ProgramSource's already-buffered Stored token.
  * The native producer must establish its bundled payload before REQ and hold
  * it through complete RTZ. Two request synchronizers plus the acceptance edge
  * provide >=2 service periods of additional settling (>=100 ns at 20 MHz).
  * ACK denotes only downstream fire. No second payload copy or capture FSM.
  * Physical bundled-data, synchronizer and reset timing remain to be qualified.
  */
class FourPhaseStoredReceipt(domain: ResetDomain) extends ClockedBridge(domain,2) {
  dontTouch(localReset) // Preserve the independently checked reset endpoint source.
  val channel=new Channel(Bool(),resetDomain)
  val in=IO(Flipped(channel.bundled)); val out=IO(channel.decoupled)
  dontTouch(in); dontTouch(out)
  withClockAndReset(clock,localReset) {
    val requestMeta=RegNext(in.req,false.B)
    val requestSync=RegNext(requestMeta,false.B)
    val acknowledge=RegInit(false.B)
    Seq(requestMeta,requestSync,acknowledge).foreach(dontTouch(_))
    out.valid:=requestSync && !acknowledge && !localReset.asBool
    out.bits:=in.bits; in.ack:=acknowledge
    when(out.fire) { acknowledge:=true.B }
      .elsewhen(!requestSync) { acknowledge:=false.B }
    contract.endpoint("request_meta",requestMeta)
    contract.endpoint("request_sync",requestSync)
    contract.endpoint("acknowledge",acknowledge)
  }
  contract.capacity(1)
  contract.channel("in",in,"input")
  contract.clockedChannel("out",out,clock,channel,"output")
  contract.endpoint("local_reset",localReset)
  contract.endpoint("reset",reset)
}
