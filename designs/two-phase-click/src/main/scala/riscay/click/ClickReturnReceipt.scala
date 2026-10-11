// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain

/** Temporary native-phase receipt for an actual remaining clocked client.
  * Two request synchronizers, one POR ACK and two reset-release synchronizers.
  * There is no payload capture or RTZ conversion; remove with that client.
  */
class ClickReturnReceipt(domain: ResetDomain) extends ClockedBridge(domain,2) {
  val request=IO(Input(Bool()));val acknowledge=IO(Output(Bool()))
  val quiet=IO(Input(Bool()))
  dontTouch(localReset)
  withClockAndReset(clock,localReset) {
    val requestMeta=RegNext(request,false.B);val requestSync=RegNext(requestMeta,false.B)
    val ack=RegInit(false.B)
    Seq(requestMeta,requestSync,ack).foreach(dontTouch(_))
    when(requestSync =/= ack && quiet) { ack:=requestSync }
    acknowledge:=ack
    contract.endpoint("request_meta",requestMeta);contract.endpoint("request_sync",requestSync)
    contract.endpoint("ack_state",ack)
  }
  Seq("request"->request,"acknowledge"->acknowledge,"quiet"->quiet).foreach {
    case(id,value) => contract.endpoint(id,value)
  }
  contract.endpoint("clock",clock);contract.endpoint("local_reset",localReset)
  contract.endpoint("reset",reset);contract.capacity(1)
}
