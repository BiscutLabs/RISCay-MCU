// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance

/** Service-clock POR coordinator. All inputs are synchronous or timed related-
  * clock acknowledgments. Raw watchdog reset belongs upstream of its two-flop
  * observer and the independent immediate output-isolation/debt paths.
  * Accepted effects are deliberately absent from the close acknowledgment.
  */
class FourPhaseResetBoundary(holdEdges: Int, releaseEdges: Int, preserveHierarchy: Boolean = false) extends Module {
  riscay.soc.EmissionHierarchy.inlineUnless(this, preserveHierarchy)
  require(holdEdges >= 2 && releaseEdges >= 2)
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
  private val count=RegInit(0.U(log2Ceil(math.max(holdEdges,releaseEdges)).W))
  // Dedicated registered controls avoid multi-bit state-decode glitches on
  // native reset and bridge phase controls. Only POR asserts reset directly.
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
          // Withdrawal is necessary, but does not prove that native reset
          // removal has traversed every guard. Retain isolation/core reset for
          // a separate interval and saturate while a receipt remains asserted.
          when(count === (releaseEdges-1).U && io.rebaseIdle) {
            stopped:=false.B; coreHeld:=false.B; state:=running
          }.elsewhen(count =/= (releaseEdges-1).U) { count:=count+1.U }
        }
    }
  }
  when(rebasing) { assert(stopped && nativeHeld,"BD_RESET_REBASE_WITHOUT_ISOLATION") }
  when(state === running) { assert(!nativeHeld && !rebasing,"BD_RESET_OPEN_WITH_HELD_PEER") }
}
