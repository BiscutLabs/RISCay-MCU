// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.AsyncModule
import org.scalatest.funsuite.AnyFunSuite

/** Clocked consumer of an independently held native token, including both data
  * polarities. Only POR belongs to the receipt bridge's reset domain.
  */
class StoredReceiptFixture(click: Boolean) extends AsyncModule {
  val serviceClock=IO(Input(Clock())); val watchdogClock=IO(Input(Clock()))
  val scl=IO(Input(Bool())); val sda=IO(Input(Bool())); val sdaLow=IO(Output(Bool()))
  val gpioIn=IO(Input(UInt(32.W))); val adcMiso=IO(Input(Bool())); sdaLow:=false.B
  // ClockedSimulation's shared serial tasks reference these unused status pins.
  val programmed=IO(Output(Bool())); val locked=IO(Output(Bool())); val mode=IO(Output(UInt(3.W)))
  programmed:=false.B; locked:=false.B; mode:=0.U
  val applicationReset=IO(Input(Bool()))
  val request=IO(Input(Bool())); val data=IO(Input(Bool())); val acknowledge=IO(Output(Bool()))
  val valid=IO(Output(Bool())); val ready=IO(Input(Bool())); val bits=IO(Output(Bool()))
  if(click) {
    val receipt=asyncChild("receipt")(d => new riscay.click.ClickStoredReceipt(d))
    receipt.clock:=serviceClock;receipt.in.req:=request;receipt.in.bits:=data
    acknowledge:=receipt.in.ack;valid:=receipt.out.valid;bits:=receipt.out.bits;receipt.out.ready:=ready
  } else {
    val receipt=asyncChild("receipt")(d => new riscay.bd.FourPhaseStoredReceipt(d))
    receipt.clock:=serviceClock;receipt.in.req:=request;receipt.in.bits:=data
    acknowledge:=receipt.in.ack;valid:=receipt.out.valid;bits:=receipt.out.bits;receipt.out.ready:=ready
  }
}

class StoredReceiptSpec extends AnyFunSuite {
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name Stored receipt: two-stage synchronization, held payload and acceptance-only acknowledgment") {
      val body=(0 until 32).map { n =>
        val phase=if(click) (n+1)%2 else 1
        s"""
          @(negedge serviceClock); #${1+n%23}; data=${n%2};
          // Payload precedes request, as required by the native buffer contract.
          #1; request=$phase;
          @(posedge serviceClock); #1;
          if(valid || acknowledge == $phase) $$fatal(1,"STORED_RECEIPT_FIRST_STAGE_BYPASS");
          @(posedge serviceClock); #1;
          if(!valid || bits !== ${n%2} || acknowledge == $phase)
            $$fatal(1,"STORED_RECEIPT_TWO_STAGE_LATENCY");
          applicationReset=1; #3; applicationReset=0;
          repeat(3) begin @(negedge serviceClock);
            if(!valid || bits !== ${n%2} || acknowledge == $phase || accepted != $n)
              $$fatal(1,"STORED_RECEIPT_BACKPRESSURE_OR_RESET");
          end
          ready=1; @(posedge serviceClock); #1;
          if(valid || acknowledge !== $phase || accepted != ${n+1})
            $$fatal(1,"STORED_RECEIPT_ACCEPTANCE");
          @(negedge serviceClock); ready=0;
          ${if(click) "" else """
            request=0;
            @(posedge serviceClock); #1;
            if(!acknowledge) $fatal(1,"STORED_RECEIPT_RETURN_FIRST_STAGE_BYPASS");
            @(posedge serviceClock); #1;
            if(!acknowledge) $fatal(1,"STORED_RECEIPT_RETURN_NOT_SYNCHRONIZED");
            @(posedge serviceClock); #1;
            if(acknowledge || valid) $fatal(1,"STORED_RECEIPT_RETURN");
          """}
        """
      }.mkString("\n")
      ClockedSimulation.run(new StoredReceiptFixture(click),name+"-stored-receipt",body,
        "integer accepted=0; always @(posedge serviceClock) if(!reset && valid && ready) accepted=accepted+1;",
        serviceHalfPeriodNs=25)
    }
    test(s"$name Stored receipt: POR cancels a held token and restores empty phase history") {
      ClockedSimulation.run(new StoredReceiptFixture(click),name+"-stored-receipt-por","""
        @(negedge serviceClock); data=1; #1; request=1;
        repeat(4) @(negedge serviceClock);
        if(!valid || acknowledge) $fatal(1,"STORED_RECEIPT_POR_PRECONDITION");
        reset=1; request=0; #2;
        if(valid || acknowledge) $fatal(1,"STORED_RECEIPT_POR_ASSERTION");
        #200; reset=0;
        repeat(8) @(negedge serviceClock);
        if(valid || acknowledge) $fatal(1,"STORED_RECEIPT_POR_REPLAY");
        data=0; #1; request=1;
        repeat(4) @(negedge serviceClock);
        if(!valid || bits || acknowledge) $fatal(1,"STORED_RECEIPT_POR_FRESH_PAYLOAD");
        ready=1; @(posedge serviceClock); #1;
        if(valid || !acknowledge) $fatal(1,"STORED_RECEIPT_POR_FRESH_ACCEPTANCE");
      """,serviceHalfPeriodNs=25)
    }
  }
}
