// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.AsyncModule
import org.scalatest.funsuite.AnyFunSuite

/** Independent held-bus source and actual receiving storage. The old receiver
  * is a control-cadence comparison only; expected payload/effect counts come
  * from the testbench, independently of either implementation's output.
  */
class ServiceReplyReceiptFixture(click: Boolean, width: Int) extends AsyncModule {
  val serviceClock=IO(Input(Clock())); val watchdogClock=IO(Input(Clock()))
  val scl=IO(Input(Bool())); val sda=IO(Input(Bool())); val sdaLow=IO(Output(Bool()))
  val gpioIn=IO(Input(UInt(32.W))); val adcMiso=IO(Input(Bool())); sdaLow:=false.B
  val programmed=IO(Output(Bool())); val locked=IO(Output(Bool())); val mode=IO(Output(UInt(3.W)))
  programmed:=false.B; locked:=false.B; mode:=0.U
  val applicationReset=IO(Input(Bool()))
  val request=IO(Input(Bool())); val data=IO(Input(UInt(width.W))); val ready=IO(Input(Bool()))
  val acknowledge=IO(Output(Bool())); val valid=IO(Output(Bool())); val bits=IO(Output(UInt(width.W)))
  val referenceAck=IO(Output(Bool())); val referenceValid=IO(Output(Bool()))
  val referenceBits=IO(Output(UInt(width.W)))
  if(click) {
    val receipt=asyncChild("receipt")(d => new riscay.click.ClickServiceReplyReceipt(UInt(width.W),d))
    val reference=asyncChild("reference")(d => new riscay.click.ClickToDecoupled(UInt(width.W),d))
    receipt.clock:=serviceClock; reference.clock:=serviceClock
    receipt.in.req:=request; receipt.in.bits:=data; receipt.out.ready:=ready
    reference.in.req:=request; reference.in.bits:=data; reference.out.ready:=ready
    acknowledge:=receipt.in.ack; valid:=receipt.out.valid; bits:=receipt.out.bits
    referenceAck:=reference.in.ack; referenceValid:=reference.out.valid; referenceBits:=reference.out.bits
  } else {
    val receipt=asyncChild("receipt")(d => new riscay.bd.FourPhaseServiceReplyReceipt(UInt(width.W),d))
    val reference=asyncChild("reference")(d => new chiselasync.clocked.FourPhaseToDecoupled(UInt(width.W),2,d))
    receipt.clock:=serviceClock; reference.clock:=serviceClock
    receipt.in.req:=request; receipt.in.bits:=data; receipt.out.ready:=ready
    reference.in.req:=request; reference.in.bits:=data; reference.out.ready:=ready
    acknowledge:=receipt.in.ack; valid:=receipt.out.valid; bits:=receipt.out.bits
    referenceAck:=reference.in.ack; referenceValid:=reference.out.valid; referenceBits:=reference.out.bits
  }
  val captured=IO(Output(UInt(width.W))); val accepted=IO(Output(UInt(32.W)))
  withClockAndReset(serviceClock,reset) {
    val value=RegInit(0.U(width.W)); val count=RegInit(0.U(32.W))
    when(valid && ready) { value:=bits; count:=count+1.U }
    captured:=value; accepted:=count
  }
}

class ServiceReplyReceiptSpec extends AnyFunSuite {
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    for(width <- Seq(1,8,32,34,42,159,376,397)) {
      test(s"$name $width-bit service reply: every data bit, unchanged control cadence, stalls and stopped clocks") {
        val body=(0 until width*2).map { n =>
          val one=BigInt(1) << (n/2)
          val value=if(n%2==0) one else ((BigInt(1)<<width)-1)^one
          val phase=if(click) (n+1)%2 else 1
          s"""
            @(negedge serviceClock); #${1+n%23}; data=${width}'h${value.toString(16)};
            #1; request=$phase;
            wait(valid); #1;
            if(acknowledge == $phase || accepted != $n || bits !== ${width}'h${value.toString(16)})
              $$fatal(1,"SERVICE_REPLY_OFFER_OR_PAYLOAD");
            applicationReset=1;
            ${if(n%37==0) "@(negedge serviceClock); clockEnabled=0; #503;" else "#3;"}
            if(!valid || acknowledge == $phase || accepted != $n || bits !== ${width}'h${value.toString(16)})
              $$fatal(1,"SERVICE_REPLY_STALL_OR_APPLICATION_RESET");
            applicationReset=0; clockEnabled=1;
            repeat(${n%5+1}) @(negedge serviceClock);
            ready=1; @(posedge serviceClock); #1;
            if(valid || acknowledge !== $phase || accepted != ${n+1} || captured !== ${width}'h${value.toString(16)})
              $$fatal(1,"SERVICE_REPLY_ACTUAL_CAPTURE");
            @(negedge serviceClock); ready=0;
            ${if(click) "" else "request=0; wait(!acknowledge);"}
          """
        }.mkString("\n")
        ClockedSimulation.run(new ServiceReplyReceiptFixture(click,width),s"$name-service-reply-$width",body,"""
          always @(negedge serviceClock) if(!reset) begin
            if(valid !== referenceValid || acknowledge !== referenceAck)
              $fatal(1,"SERVICE_REPLY_CONTROL_CADENCE_CHANGED");
            if(valid && bits !== referenceBits) $fatal(1,"SERVICE_REPLY_REFERENCE_PAYLOAD");
          end
        """,serviceHalfPeriodNs=25)
      }
    }
    test(s"$name service reply: POR aborts a pending reply and fresh phase resumes") {
      ClockedSimulation.run(new ServiceReplyReceiptFixture(click,308),s"$name-service-reply-por","""
        @(negedge serviceClock); data=308'habcdef123; #1; request=1;
        wait(valid); @(negedge serviceClock); clockEnabled=0;
        reset=1; request=0; #2;
        if(valid || acknowledge || accepted) $fatal(1,"SERVICE_REPLY_POR_ASSERTION");
        #200; reset=0; #201;
        if(valid || acknowledge || accepted) $fatal(1,"SERVICE_REPLY_POR_STOPPED_RELEASE");
        clockEnabled=1; repeat(8) @(negedge serviceClock);
        data=308'h80000000000000000000000000000000000000000000000000000000000000000000000000001;
        #1; request=1; wait(valid);
        @(negedge serviceClock); ready=1; @(posedge serviceClock); #1;
        if(valid || !acknowledge || accepted !== 1 || captured !== data)
          $fatal(1,"SERVICE_REPLY_POR_FRESH_CAPTURE");
        repeat(5) @(negedge serviceClock);
        if(accepted !== 1) $fatal(1,"SERVICE_REPLY_REPLAY");
      """,serviceHalfPeriodNs=25)
    }
    test(s"$name service reply: ready precedes offer, immediate legal reuse, and clock stop at return") {
      val body=(0 until 16).map { n =>
        val value=(BigInt(1)<<307) | (BigInt(n+1)<<144) | (BigInt(1)<<n)
        val phase=if(click) (n+1)%2 else 1
        s"""
          data=308'h${value.toString(16)}; #1; request=$phase;
          wait(acknowledge == $phase); #0.001;
          if(accepted != ${n+1} || captured !== 308'h${value.toString(16)} || valid)
            $$fatal(1,"SERVICE_REPLY_EARLIEST_ACCEPTANCE");
          ${if(click) "" else "request=0;"}
          ${if(n%2==0) s"""
            @(negedge serviceClock); clockEnabled=0; #153;
            if(accepted != ${n+1} || captured !== 308'h${value.toString(16)} || valid || acknowledge !== $phase)
              $$fatal(1,"SERVICE_REPLY_STOPPED_RETURN");
            clockEnabled=1;
          """ else ""}
          ${if(click) "" else "wait(!acknowledge); #0.001;"}
        """
      }.mkString("\n")
      ClockedSimulation.run(new ServiceReplyReceiptFixture(click,308),s"$name-service-reply-reuse",
        "@(negedge serviceClock); ready=1;\n"+body+"#1000; if(accepted !== 16) $fatal(1,\"SERVICE_REPLY_DUPLICATE_AFTER_REUSE\");",
        """
          always @(negedge serviceClock) if(!reset) begin
            if(valid !== referenceValid || acknowledge !== referenceAck)
              $fatal(1,"SERVICE_REPLY_REUSE_CONTROL_CADENCE");
            if(valid && bits !== referenceBits) $fatal(1,"SERVICE_REPLY_REUSE_PAYLOAD");
          end
        """,serviceHalfPeriodNs=25)
    }
  }
}
