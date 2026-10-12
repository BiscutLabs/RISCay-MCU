// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.clocked.ClockedBridge
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel
import riscay.soc.I2cFrame

/** Control-only receipt of the native I2C publisher's retained frame.
  * ACK means actual downstream acceptance; the producer holds every payload
  * bit through that capture and the native return. Two request synchronizers
  * add at least two front-clock periods before acceptance. There is no clocked
  * frame copy. All history is POR-owned, including while the application resets.
  * The caller must qualify ready with the destination work-clock enable.
  * The complete producer-to-mailbox data path still needs physical timing closure.
  */
class FourPhaseFrameReceipt(domain: ResetDomain) extends ClockedBridge(domain,2) {
  dontTouch(localReset) // Preserve the independently checked reset endpoint source.
  val channel=new Channel(new I2cFrame,resetDomain)
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
