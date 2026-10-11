// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain

/** Temporary control-only receipt for an actual remaining clocked client.
  * Two request synchronizers, one POR ACK and two reset-release synchronizers.
  * Quiet excludes this receipt and native owner idle. Remove with that client.
  */
class FourPhaseReturnReceipt(domain: ResetDomain) extends ClockedBridge(domain,2) {
  val request=IO(Input(Bool()));val acknowledge=IO(Output(Bool()))
  val quiet=IO(Input(Bool()))
  dontTouch(localReset)
  withClockAndReset(clock,localReset) {
    val requestMeta=RegNext(request,false.B);val requestSync=RegNext(requestMeta,false.B)
    val ack=RegInit(false.B)
    Seq(requestMeta,requestSync,ack).foreach(dontTouch(_))
    when(!requestSync) { ack:=false.B }
      .elsewhen(quiet) { ack:=true.B }
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
