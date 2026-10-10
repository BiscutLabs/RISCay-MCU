// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.bundled.{FourPhaseFifo,LongHoldBuffer}
import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.metadata.{BundledTiming,ModelTime}
import chiselasync.primitives.AsymmetricCElement
import chiselasync.protocol.FourPhase

/** One initial admission credit, recycled by native completion retirement.
  * The empty return slot decouples response return from a clocked grant client.
  */
class FourPhaseAdmission(domain: ResetDomain) extends AsyncModule(domain) {
  val returned=fourPhaseInput("returned",Bool())
  val grant=fourPhaseOutput("grant",Bool())
  val responseIdle=IO(Input(Bool()))
  private val timing=BundledTiming.Simulation
  private val cell=ModelTime.ps(1000)
  private val resetRef=contract.endpoint("reset",reset)
  private val pending=asyncChild("pending")(d => new LongHoldBuffer(Bool(),timing,d))
  private val credit=asyncChild("credit")(d => new FourPhaseFifo(Bool(),1,timing,Seq(false.B),cell,d))
  FourPhase.connect(pending.in,returned)
  // Once offered, retain the recycle request even if the next transaction starts.
  // Only the buffered request's return clears this barrier.
  private val barrier=Module(new AsymmetricCElement(1,1,0,cell)); barrier.reset:=reset
  barrier.common:=pending.out.req.asUInt; barrier.rising:=responseIdle.asUInt; barrier.falling:=0.U
  credit.in.req:=barrier.q; credit.in.bits:=pending.out.bits; pending.out.ack:=credit.in.ack
  FourPhase.connect(grant,credit.out)
  contract.primitive("return_barrier",barrier,Map("COMMON"->BigInt(1),"RISING"->BigInt(1),"FALLING"->BigInt(0),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,
    "recycle only after response RTZ; retain offer through downstream acceptance and return")
  contract.endpoint("response_idle",responseIdle)
  contract.capacity(2)
}
