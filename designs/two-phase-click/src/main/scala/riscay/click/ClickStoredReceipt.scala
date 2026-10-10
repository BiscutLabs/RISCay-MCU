// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel

/** Native-phase receipt for the ProgramSource's already-buffered Stored token.
  * Its producer establishes the bundled payload before each phase and holds it
  * until acceptance. Two request synchronizers plus the acceptance edge add
  * >=2 service periods of settling (>=100 ns at 20 MHz). ACK retains the accepted
  * phase; there is no RTZ conversion, second payload copy or capture FSM.
  * Physical bundled-data, synchronizer and reset timing remain to be qualified.
  */
class ClickStoredReceipt(domain: ResetDomain) extends ClockedBridge(domain,2) {
  dontTouch(localReset) // Preserve the independently checked reset endpoint source.
  val channel=new Channel(Bool(),resetDomain)
  val in=IO(Flipped(channel.twoPhase)); val out=IO(channel.decoupled)
  dontTouch(in); dontTouch(out)
  withClockAndReset(clock,localReset) {
    val requestMeta=RegNext(in.req,false.B)
    val requestSync=RegNext(requestMeta,false.B)
    val acknowledge=RegInit(false.B)
    Seq(requestMeta,requestSync,acknowledge).foreach(dontTouch(_))
    out.valid:=(requestSync =/= acknowledge) && !localReset.asBool
    out.bits:=in.bits; in.ack:=acknowledge
    when(out.fire) { acknowledge:=requestSync }
    contract.endpoint("request_meta",requestMeta)
    contract.endpoint("request_sync",requestSync)
    contract.endpoint("acknowledge",acknowledge)
  }
  contract.capacity(1)
  contract.twoPhaseChannel("in",in,"input")
  contract.clockedChannel("out",out,clock,channel,"output")
  contract.endpoint("local_reset",localReset)
  contract.endpoint("reset",reset)
}
