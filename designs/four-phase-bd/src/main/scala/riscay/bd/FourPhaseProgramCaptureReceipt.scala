// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain

/** Temporary POR control receipt for the clocked access-active owner. It has
  * no payload and no data copy. ACK means active was cleared on this same edge;
  * neither owner idle nor publication return is a prerequisite. Five clocked
  * bits include the two POR release stages. Remove with clocked admission.
  */
class FourPhaseProgramCaptureReceipt(domain: ResetDomain) extends ClockedBridge(domain,2) {
  val request=IO(Input(Bool())); val acknowledge=IO(Output(Bool()))
  val accept=IO(Input(Bool())); val accepted=IO(Output(Bool())); val idle=IO(Output(Bool()))
  dontTouch(localReset)
  withClockAndReset(clock,localReset) {
    val requestMeta=RegNext(request,false.B)
    val requestSync=RegNext(requestMeta,false.B)
    val phase=RegInit(false.B)
    Seq(requestMeta,requestSync,phase).foreach(dontTouch(_))
    accepted:=accept && requestSync && !phase && !localReset.asBool
    acknowledge:=phase
    when(accepted) { phase:=true.B }
    .elsewhen(!requestSync) { phase:=false.B }
    idle:= !requestSync && !phase
    contract.endpoint("request_meta",requestMeta); contract.endpoint("request_sync",requestSync)
    contract.endpoint("acknowledge_phase",phase)
  }
  Seq("request"->request,"acknowledge"->acknowledge,"accept"->accept,
    "accepted"->accepted,"idle"->idle,"local_reset"->localReset,"reset"->reset).foreach {
    case(id,value) => dontTouch(value);contract.endpoint(id,value)
  }
}
