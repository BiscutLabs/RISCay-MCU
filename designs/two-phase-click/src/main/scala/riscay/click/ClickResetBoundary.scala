// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance

/** POR service-clock reset coordinator for the native Click application island.
  * observed is already synchronized; close/rebase receipts come from actual
  * service/work edges. Independent raw isolation/debt never enters this logic.
  * The handshake resets both toggle peers together, without an RTZ adapter or
  * a wait for POR-owned effects to finish.
  */
class ClickResetBoundary(holdEdges: Int) extends Module with InlineInstance {
  require(holdEdges >= 2)
  val io=IO(new Bundle {
    val observed=Input(Bool())
    val closed=Input(Bool()); val rebased=Input(Bool()); val rebaseIdle=Input(Bool())
    val close=Output(Bool()); val rebase=Output(Bool()); val nativeReset=Output(Bool())
    val coreReset=Output(Bool())
    val forceRun=Output(Bool())
  })
  private val running :: closing :: holding :: reopening :: Nil=Enum(4)
  private val state=RegInit(closing)
  private val stopped=RegInit(true.B)
  private val nativeHeld=RegInit(true.B)
  private val coreHeld=RegInit(true.B)
  private val rebasing=RegInit(false.B)
  private val count=RegInit(0.U(log2Ceil(holdEdges).W))
  // Clocked state decoders must not glitch a native reset or history rebase.
  io.close:=stopped || io.observed
  io.nativeReset:=nativeHeld || reset.asBool
  io.coreReset:=coreHeld || reset.asBool
  io.rebase:=rebasing
  io.forceRun:=io.close
  switch(state) {
    is(running) {
      when(io.observed) { stopped:=true.B; state:=closing }
    }
    is(closing) {
      when(io.closed) {
        nativeHeld:=true.B; coreHeld:=true.B; rebasing:=true.B; count:=0.U; state:=holding
      }
    }
    is(holding) {
      when(io.observed || !io.rebased) { count:=0.U }
        .elsewhen(count === (holdEdges-1).U) {
          nativeHeld:=false.B; rebasing:=false.B; count:=0.U; state:=reopening
        }.otherwise { count:=count+1.U }
    }
    is(reopening) {
      when(io.observed) { state:=closing; count:=0.U }
        .otherwise {
          when(count === 1.U && io.rebaseIdle) { stopped:=false.B; coreHeld:=false.B; state:=running }
            .elsewhen(count === 0.U) { count:=1.U }
        }
    }
  }
  when(rebasing) { assert(stopped && nativeHeld,"CLICK_RESET_REBASE_WITHOUT_ISOLATION") }
  when(state === running) { assert(!nativeHeld && !rebasing,"CLICK_RESET_OPEN_WITH_HELD_PEER") }
}
