// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives.{AsymmetricCElement, ControlGate, GateOperation}

/** A bank remains owned until both its clocked head receipt and native Control
  * have completed. Their returns overlap; neither waits to start the other.
  * Bank/kind are stable before command ACK rises and through its falling edge.
  * They may change only while command ACK is low, after complete command RTZ.
  */
class FourPhaseFrameCompletion(domain: ResetDomain) extends AsyncModule(domain) {
  val bank=IO(Input(UInt(2.W)))
  val host=IO(Input(Bool()))
  val commandAck=IO(Input(Bool()))
  val receiptAck=IO(Input(Vec(4,Bool())))
  val bankAck=IO(Output(Vec(4,Bool())))
  private val resetRef=contract.endpoint("reset",reset)
  private val cell=ModelTime.ps(1000)
  private def gate(id: String, op: GateOperation.Value, a: Bool, b: Bool=false.B,
      resetValue: Int=0): Bool = {
    val g=Module(new ControlGate(1,op,cell,resetValue))
    g.reset:=reset; g.a:=a.asUInt; g.b:=b.asUInt
    contract.primitive(id,g,Map("WIDTH"->BigInt(1),"OP"->BigInt(op.id),
      "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(resetValue)),resetRef,
      "native frame return qualification; selector changes only with command ACK low")
    g.q.asBool
  }
  private def and(id: String,a: Bool,b: Bool): Bool = {
    val na=gate(id+"_na",GateOperation.Invert,a,resetValue=1)
    val nb=gate(id+"_nb",GateOperation.Invert,b,resetValue=1)
    val either=gate(id+"_or",GateOperation.Or,na,nb,resetValue=1)
    gate(id,GateOperation.Invert,either)
  }
  private val active=and("host_ack",commandAck,host)
  for(i <- 0 until 4) {
    val selected=and(s"bank${i}_ack",active,bank===i.U)
    val joined=Module(new AsymmetricCElement(2,0,0,cell))
    joined.reset:=reset; joined.common:=Cat(receiptAck(i),selected)
    joined.rising:=1.U; joined.falling:=0.U; bankAck(i):=joined.q
    contract.primitive(s"completion$i",joined,Map("COMMON"->BigInt(2),"RISING"->BigInt(0),
      "FALLING"->BigInt(0),"DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),
      "COMMON_INVERT"->BigInt(0),"RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),
      resetRef,"join native command acceptance and head receipt; retain through both returns")
  }
  contract.endpoint("bank",bank); contract.endpoint("host",host)
  contract.endpoint("command_ack",commandAck)
  for(i <- 0 until 4) {
    contract.endpoint(s"receipt_ack_$i",receiptAck(i))
    contract.endpoint(s"bank_ack_$i",bankAck(i))
  }
}
