// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.AsyncModule
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc.I2cFrame

/** A held native frame and a destination clock gated on the falling edge.
  * The sampled word/count are independent destination observations, not ACK copies.
  */
class FrameReceiptFixture(click: Boolean) extends AsyncModule {
  val serviceClock=IO(Input(Clock())); val watchdogClock=IO(Input(Clock()))
  val scl=IO(Input(Bool())); val sda=IO(Input(Bool())); val sdaLow=IO(Output(Bool())); sdaLow:=false.B
  val gpioIn=IO(Input(UInt(32.W))); val adcMiso=IO(Input(Bool()))
  val programmed=IO(Output(Bool())); val locked=IO(Output(Bool())); val mode=IO(Output(UInt(3.W)))
  programmed:=false.B; locked:=false.B; mode:=0.U
  val applicationReset=IO(Input(Bool())); val workRun=IO(Input(Bool()))
  val request=IO(Input(Bool())); val data=IO(Input(UInt(337.W)))
  val acknowledge=IO(Output(Bool())); val valid=IO(Output(Bool())); val accept=IO(Input(Bool()))
  val bits=IO(Output(UInt(337.W))); val workRunning=IO(Output(Bool()))
  val sampled=IO(Output(UInt(337.W))); val samples=IO(Output(UInt(16.W)))
  val running=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(workRun,false.B) }
  workRunning:=running
  val workClock=(serviceClock.asBool && running).asClock
  if(click) {
    val receipt=asyncChild("receipt")(d => new riscay.click.ClickFrameReceipt(d))
    receipt.clock:=serviceClock;receipt.in.req:=request;receipt.in.bits:=data.asTypeOf(new I2cFrame)
    acknowledge:=receipt.in.ack;valid:=receipt.out.valid;bits:=receipt.out.bits.asUInt
    receipt.out.ready:=accept && running
  } else {
    val receipt=asyncChild("receipt")(d => new riscay.bd.FourPhaseFrameReceipt(d))
    receipt.clock:=serviceClock;receipt.in.req:=request;receipt.in.bits:=data.asTypeOf(new I2cFrame)
    acknowledge:=receipt.in.ack;valid:=receipt.out.valid;bits:=receipt.out.bits.asUInt
    receipt.out.ready:=accept && running
  }
  withClockAndReset(workClock,reset) {
    val held=RegInit(0.U(337.W)); val count=RegInit(0.U(16.W))
    when(valid && accept) { held:=bits; count:=count+1.U }
    sampled:=held;samples:=count
  }
}

class FrameReceiptSpec extends AnyFunSuite {
  private def returnPhase(click: Boolean): String = if(click) "" else """
    @(negedge serviceClock); request=0;
    @(posedge serviceClock); #1;
    if(!acknowledge) $fatal(1,"FRAME_RECEIPT_UNSYNCHRONIZED_RETURN");
    @(posedge serviceClock); #1;
    if(!acknowledge) $fatal(1,"FRAME_RECEIPT_EARLY_RETURN");
    @(posedge serviceClock); #1;
    if(acknowledge || valid) $fatal(1,"FRAME_RECEIPT_RETURN");
  """
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    for(hz <- Seq(3200000,20000000)) {
      test(s"$name frame receipt: all337 payload bits, independent backpressure and native phases at $hz Hz") {
        val all=(BigInt(1)<<337)-1
        val values=Seq(BigInt(0),all) ++ (0 until 337).flatMap(i => Seq(BigInt(1)<<i,all^(BigInt(1)<<i)))
        val body=values.zipWithIndex.map { case(value,n) =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            @(negedge serviceClock); #1; data=337'h${value.toString(16)}; #1; request=$phase;
            @(posedge serviceClock); #1;
            if(valid || acknowledge === $phase) $$fatal(1,"FRAME_RECEIPT_SYNC_BYPASS");
            @(posedge serviceClock); #1;
            if(!valid || bits !== data || acknowledge === $phase) $$fatal(1,"FRAME_RECEIPT_OFFER");
            applicationReset=1; #2; applicationReset=0;
            repeat(${1+n%4}) begin @(negedge serviceClock);
              if(!valid || bits !== data || samples != $n || acknowledge === $phase)
                $$fatal(1,"FRAME_RECEIPT_STALL_OR_APPLICATION_RESET");
            end
            accept=1; @(posedge serviceClock); #1;
            if(valid || acknowledge !== $phase || samples != ${n+1} || sampled !== data)
              $$fatal(1,"FRAME_RECEIPT_DESTINATION_CAPTURE");
            @(negedge serviceClock); accept=0;
            ${returnPhase(click)}
          """
        }.mkString("\n")
        ClockedSimulation.run(new FrameReceiptFixture(click),name+"-frame-receipt-bits",
          "workRun=1; repeat(4) @(negedge serviceClock);\n"+body,serviceHalfPeriodNs=5.0e8/hz)
      }
      test(s"$name frame receipt: ungated offer waits for actual work-clock capture at $hz Hz") {
        val body=(0 until 12).map { n =>
          val phase=if(click) (n+1)%2 else 1
          val value=((BigInt(1)<<337)-1) ^ (BigInt(1)<<(n*29%337))
          s"""
            @(negedge serviceClock); #1; workRun=0; accept=1;
            repeat(2) @(negedge serviceClock);
            if(workRunning) $$fatal(1,"FRAME_RECEIPT_GATE_PRECONDITION");
            #1; data=337'h${value.toString(16)}; #1; request=$phase;
            repeat(8) begin
              @(negedge serviceClock); #1; applicationReset=1; #3; applicationReset=0;
              if(acknowledge === $phase || samples != $n) $$fatal(1,"FRAME_RECEIPT_ACK_WITHOUT_WORK_EDGE");
            end
            if(!valid || bits !== data) $$fatal(1,"FRAME_RECEIPT_STOPPED_WORK_OFFER");
            // Stop the front clock too; neither reset lifetime may fabricate acceptance.
            @(negedge serviceClock); #1; clockEnabled=0; #2000;
            applicationReset=1; #7; applicationReset=0; #2000;
            if(!valid || acknowledge === $phase || samples != $n || bits !== data)
              $$fatal(1,"FRAME_RECEIPT_STOPPED_FRONT");
            clockEnabled=1; @(negedge serviceClock); #1; workRun=1;
            @(posedge serviceClock); #1;
            if(samples != $n || acknowledge === $phase) $$fatal(1,"FRAME_RECEIPT_GATE_RISE_TOO_EARLY");
            @(negedge serviceClock); @(posedge serviceClock); #1;
            if(samples != ${n+1} || sampled !== data || acknowledge !== $phase || valid)
              $$fatal(1,"FRAME_RECEIPT_WAKE_CAPTURE");
            @(negedge serviceClock); accept=0;
            ${returnPhase(click)}
          """
        }.mkString("\n")
        ClockedSimulation.run(new FrameReceiptFixture(click),name+"-frame-receipt-gate",body,
          serviceHalfPeriodNs=5.0e8/hz)
      }
    }
    test(s"$name frame receipt: POR cancels held delivery and resets only POR phase history") {
      ClockedSimulation.run(new FrameReceiptFixture(click),name+"-frame-receipt-por","""
        workRun=0; accept=1; data=337'h1; request=1;
        repeat(5) @(negedge serviceClock);
        if(!valid || acknowledge || samples != 0) $fatal(1,"FRAME_RECEIPT_POR_PRECONDITION");
        reset=1; request=0; #2;
        if(valid || acknowledge) $fatal(1,"FRAME_RECEIPT_POR_ASSERTION");
        #200; reset=0; workRun=1;
        repeat(8) @(negedge serviceClock);
        if(valid || acknowledge || samples != 0) $fatal(1,"FRAME_RECEIPT_POR_REPLAY");
        #1; data=337'h10000000000000001; #1; request=1;
        repeat(5) @(negedge serviceClock);
        if(!acknowledge || valid || samples != 1 || sampled !== data) $fatal(1,"FRAME_RECEIPT_POR_FRESH");
      """,serviceHalfPeriodNs=25)
    }
  }
}
