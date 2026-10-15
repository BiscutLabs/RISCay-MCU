// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.AsyncModule
import org.scalatest.funsuite.AnyFunSuite

/** Independent actual consumer edge; the old stored receiver is a cadence
  * oracle only. Its invalid payload retention contract remains untouched.
  */
class QuiescingReceiptFixture(click: Boolean, managed: Boolean=false) extends AsyncModule {
  val serviceClock=IO(Input(Clock())); val watchdogClock=IO(Input(Clock()))
  val scl=IO(Input(Bool())); val sda=IO(Input(Bool())); val sdaLow=IO(Output(Bool())); sdaLow:=false.B
  val gpioIn=IO(Input(UInt(32.W))); val adcMiso=IO(Input(Bool()))
  val programmed=IO(Output(Bool())); val locked=IO(Output(Bool())); val mode=IO(Output(UInt(3.W)))
  programmed:=false.B; locked:=false.B; mode:=0.U
  val applicationReset=IO(Input(Bool())); val observed=IO(Input(Bool()))
  val close=IO(if(managed) Output(Bool()) else Input(Bool()))
  val rebase=IO(if(managed) Output(Bool()) else Input(Bool()))
  val workRun=IO(Input(Bool())); val workRunning=IO(Output(Bool()))
  val nativeReset=IO(Output(Bool())); val forceRun=IO(Output(Bool()))
  val request=IO(Input(Bool())); val data=IO(Input(UInt(70.W))); val allow=IO(Input(Bool()))
  val acknowledge=IO(Output(Bool())); val valid=IO(Output(Bool())); val bits=IO(Output(UInt(70.W)))
  val closed=IO(Output(Bool())); val rebased=IO(Output(Bool())); val consumerClosed=IO(Output(Bool()))
  val goldenAcknowledge=Wire(Bool()); val goldenValid=Wire(Bool()); val goldenBits=Wire(UInt(70.W))
  private val enabled=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(workRun,false.B) }
  private val workClock=(serviceClock.asBool && enabled).asClock
  workRunning:=enabled
  private val ready=allow && enabled
  if(click) {
    val rx=asyncChild("rx")(d => new riscay.click.ClickQuiescingReceipt(UInt(70.W),d))
    val golden=asyncChild("golden")(d => new riscay.click.ClickQuiescingToDecoupled(UInt(70.W),d))
    rx.clock:=serviceClock; rx.close:=close; rx.rebase:=rebase
    rx.in.req:=request; rx.in.bits:=data; rx.out.ready:=ready
    acknowledge:=rx.in.ack; valid:=rx.out.valid; bits:=rx.out.bits; closed:=rx.closed; rebased:=rx.rebased
    golden.clock:=serviceClock; golden.close:=close; golden.rebase:=rebase
    golden.in.req:=request; golden.in.bits:=data; golden.out.ready:=ready
    goldenAcknowledge:=golden.in.ack; goldenValid:=golden.out.valid; goldenBits:=golden.out.bits
  } else {
    val rx=asyncChild("rx")(d => new riscay.bd.FourPhaseQuiescingReceipt(UInt(70.W),d))
    val golden=asyncChild("golden")(d => new riscay.bd.FourPhaseQuiescingToDecoupled(UInt(70.W),d))
    rx.clock:=serviceClock; rx.close:=close; rx.rebase:=rebase
    rx.in.req:=request; rx.in.bits:=data; rx.out.ready:=ready
    acknowledge:=rx.in.ack; valid:=rx.out.valid; bits:=rx.out.bits; closed:=rx.closed; rebased:=rx.rebased
    golden.clock:=serviceClock; golden.close:=close; golden.rebase:=rebase
    golden.in.req:=request; golden.in.bits:=data; golden.out.ready:=ready
    goldenAcknowledge:=golden.in.ack; goldenValid:=golden.out.valid; goldenBits:=golden.out.bits
  }
  withClockAndReset(serviceClock,reset) {
    assert(acknowledge === goldenAcknowledge && valid === goldenValid,"RECEIPT_CONTROL_CADENCE")
    when(valid) { assert(bits === goldenBits,"RECEIPT_HELD_PAYLOAD") }
      .otherwise { assert(bits === 0.U,"RECEIPT_INVALID_BUS_NOT_MASKED") }
  }
  val samples=IO(Output(UInt(16.W))); val sample=IO(Output(UInt(70.W)))
  // Deliberately unqualified use models unrelated Control command capture.
  // A structural mask proof must make this safe even when native data changes.
  val background=IO(Output(UInt(70.W)))
  withClockAndReset(workClock,reset) {
    val count=RegInit(0.U(16.W)); val held=RegInit(0.U(70.W))
    when(valid && allow) { count:=count+1.U; held:=bits }
    samples:=count; sample:=held
    background:=RegNext(bits,0.U)
    consumerClosed:=RegNext(close,false.B)
  }
  if(managed) {
    if(click) {
      val boundary=withClockAndReset(serviceClock,reset) { Module(new riscay.click.ClickResetBoundary(64,64)) }
      boundary.io.observed:=observed; boundary.io.closed:=closed && consumerClosed
      boundary.io.rebased:=rebased; boundary.io.rebaseIdle:= !rebased
      close:=boundary.io.close; rebase:=boundary.io.rebase
      nativeReset:=boundary.io.nativeReset; forceRun:=boundary.io.forceRun
    } else {
      val boundary=withClockAndReset(serviceClock,reset) { Module(new riscay.bd.FourPhaseResetBoundary(64,64)) }
      boundary.io.observed:=observed; boundary.io.closed:=closed && consumerClosed
      boundary.io.rebased:=rebased; boundary.io.rebaseIdle:= !rebased
      close:=boundary.io.close; rebase:=boundary.io.rebase
      nativeReset:=boundary.io.nativeReset; forceRun:=boundary.io.forceRun
    }
  } else { nativeReset:=false.B; forceRun:=false.B }
}

class QuiescingReceiptSpec extends AnyFunSuite {
  private def tasks(click: Boolean, managed: Boolean)=s"""
integer expected=0,bitNumber=0,stage=0,prior=0,returnEdges=0;
reg phase=0; reg heldAck; reg [69:0] value;
task open_consumer; begin
  @(negedge serviceClock); workRun=1;
  repeat(3) @(negedge serviceClock);
end endtask
task offer(input [69:0] nextValue); begin
  @(negedge serviceClock); allow=0; data=nextValue;
  #1; phase=${if(click) "!phase" else "1"}; request=phase;
  wait(valid); #1;
  if(bits !== nextValue || acknowledge === phase) $$fatal(1,"RECEIPT_OFFER");
end endtask
task accept; begin
  @(negedge serviceClock); allow=1;
  @(posedge serviceClock); #1; expected=expected+1;
  if(samples != expected || sample !== data || acknowledge !== phase || valid || bits !== 0)
    $$fatal(1,"RECEIPT_ACTUAL_CONSUMER_EDGE");
  @(negedge serviceClock); allow=0;
end endtask
task returned; begin
  ${if(click) "" else "request=0; wait(!acknowledge);"}
  repeat(5) @(negedge serviceClock);
end endtask
task send(input [69:0] nextValue); begin
  offer(nextValue);
  repeat(3) begin @(negedge serviceClock);
    if(!valid || bits !== nextValue || acknowledge === phase || samples != expected)
      $$fatal(1,"RECEIPT_BACKPRESSURE");
  end
  accept; returned;
end endtask
""" + (if(managed) "" else s"""
task rebase_closed; begin
  if(!closed || !consumerClosed || !close || valid || bits !== 0) $$fatal(1,"RECEIPT_CLOSE_PRECONDITION");
  // Destruction is legal only after BOTH real closure edges have happened.
  @(negedge serviceClock); request=0; data=~data; rebase=1;
  @(posedge serviceClock); #1;
  if(!rebased || acknowledge || valid || bits !== 0) $$fatal(1,"RECEIPT_REBASE");
  repeat(6) begin @(negedge serviceClock); data=~data; request=~request;
    @(posedge serviceClock); #1;
    if(valid || bits !== 0 || acknowledge || samples != expected) $$fatal(1,"RECEIPT_CLOSED_BUS_LEAK");
  end
  @(negedge serviceClock); request=0; data=0; rebase=0;
  repeat(3) @(negedge serviceClock);
  if(rebased) $$fatal(1,"RECEIPT_REBASE_WITHDRAWAL");
  close=0; applicationReset=0; phase=0;
  repeat(5) @(negedge serviceClock);
  if(valid || acknowledge || samples != expected) $$fatal(1,"RECEIPT_CANCEL_REPLAY");
end endtask
""")
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def run(suffix:String,body:String,extra:String="",managed:Boolean=false):Unit = {
      ClockedSimulation.run(new QuiescingReceiptFixture(click,managed),name+"-retained-quiescing-"+suffix,
        body,tasks(click,managed)+extra,serviceHalfPeriodNs=25)
    }
    test(s"$name retained quiescing receipt preserves all 70 bits and stored-receiver cadence") {
      run("walk","""
        open_consumer;
        for(bitNumber=0;bitNumber<70;bitNumber=bitNumber+1) begin
          send(70'b1 << bitNumber); send(~(70'b1 << bitNumber));
        end
        if(samples != 140) $fatal(1,"RECEIPT_WALK_COVERAGE");
      """)
    }
    test(s"$name retained quiescing receipt masks every invalid native lane from unrelated clocked use") {
      run("invalid","""
        open_consumer;
        for(bitNumber=0;bitNumber<70;bitNumber=bitNumber+1) begin
          @(negedge serviceClock); #1; data=70'b1 << bitNumber;
          #7; if(bits !== 0 || valid) $fatal(1,"RECEIPT_IDLE_ASYNC_LEAK");
          @(posedge serviceClock); #1;
          if(background !== 0 || samples) $fatal(1,"RECEIPT_IDLE_BACKGROUND_CAPTURE");
          @(negedge serviceClock); data=~data;
          @(posedge serviceClock); #1;
          if(background !== 0 || bits !== 0) $fatal(1,"RECEIPT_IDLE_COMPLEMENT_LEAK");
        end
        send(70'h3123456789abcdef01);
      """)
    }
    test(s"$name retained quiescing receipt does not ACK a stopped gated consumer") {
      run("work-stop","""
        open_consumer; offer(70'h3abcdef01234567890);
        @(negedge serviceClock); #1; workRun=0;
        repeat(3) @(negedge serviceClock);
        allow=1; heldAck=acknowledge;
        repeat(12) begin @(negedge serviceClock);
          if(workRunning || !valid || acknowledge !== heldAck || samples != expected || bits !== data)
            $fatal(1,"RECEIPT_ACK_WITHOUT_CONSUMER_CLOCK");
        end
        #1; workRun=1; wait(workRunning);
        @(posedge serviceClock); #1; expected=expected+1;
        if(samples != expected || sample !== data || acknowledge !== phase || valid)
          $fatal(1,"RECEIPT_WORK_RESTART");
        @(negedge serviceClock); allow=0; returned;
        send(70'h155555555aaaaaaaaa);
      """)
    }
    test(s"$name retained quiescing receipt requires real closure and rebase edges at every input phase") {
      run("close-phases",s"""
        open_consumer;
        for(prior=0;prior<${if(click) 2 else 1};prior=prior+1) begin
          for(stage=0;stage<6;stage=stage+1) begin
            if(prior) send(70'h1234567890abcdef0);
            @(negedge serviceClock); allow=0; data=70'h3fedcba98765432101;
            #1; phase=${if(click) "!phase" else "1"}; request=phase;
            repeat(stage) @(posedge serviceClock);
            @(negedge serviceClock); #1; close=1; clockEnabled=0; applicationReset=1;
            heldAck=acknowledge;
            #1000;
            if(closed || consumerClosed || rebased || acknowledge !== heldAck || bits !== 0 || valid)
              $$fatal(1,"RECEIPT_CLOSE_WITHOUT_EDGE");
            clockEnabled=1; @(posedge serviceClock); #1;
            if(!closed || !consumerClosed || samples != expected) $$fatal(1,"RECEIPT_LAST_CAPTURE");
            // Rebase also needs an actual edge, independently of closure.
            @(negedge serviceClock); #1; clockEnabled=0; rebase=1;
            #1000; if(rebased) $$fatal(1,"RECEIPT_REBASE_WITHOUT_EDGE");
            rebase=0; clockEnabled=1;
            rebase_closed;
            send(70'h2123456789abcdef0); returned;
            // Rebase to phase zero for the next explicit prior-phase case.
            @(negedge serviceClock); close=1;
            repeat(3) @(negedge serviceClock); rebase_closed;
          end
        end
      """)
    }
    test(s"$name retained quiescing receipt closes in every accepted return interval") {
      run("return-close",s"""
        open_consumer;
        for(returnEdges=0;returnEdges<5;returnEdges=returnEdges+1) begin
          offer(70'h30000000000001234); accept;
          ${if(click) "" else "request=0;"}
          repeat(returnEdges) @(posedge serviceClock);
          @(negedge serviceClock); close=1;
          repeat(3) @(negedge serviceClock); rebase_closed;
          send(70'h20000000000000007);
          @(negedge serviceClock); close=1;
          repeat(3) @(negedge serviceClock); rebase_closed;
        end
      """)
    }
    test(s"$name retained quiescing receipt ignores raw application reset until coherent cutoff") {
      run("raw-reset","""
        open_consumer; offer(70'h312345678abcdef01);
        @(negedge serviceClock); #3; applicationReset=1;
        repeat(4) begin @(negedge serviceClock);
          if(!valid || bits !== data || acknowledge === phase) $fatal(1,"RECEIPT_RAW_RESET_DESTROYED");
        end
        accept; returned;
        applicationReset=0; send(70'h3fffffffffffffffe);
      """)
    }
    test(s"$name retained quiescing receipt cannot destroy the source before a stopped consumer closes") {
      run("managed","""
        open_consumer; wait(!close); offer(70'h312345678abcdef01);
        @(negedge serviceClock); #1; workRun=0;
        repeat(3) @(negedge serviceClock);
        #1; observed=1; applicationReset=1;
        repeat(12) begin @(negedge serviceClock);
          if(!closed || consumerClosed || nativeReset || !close || !forceRun || rebased || samples)
            $fatal(1,"RECEIPT_SOURCE_DESTROYED_BEFORE_CONSUMER_CLOSE");
          if(bits !== 0) $fatal(1,"RECEIPT_COORDINATED_INVALID_MASK");
        end
        #1; workRun=1; wait(nativeReset);
        if(!closed || !consumerClosed) $fatal(1,"RECEIPT_NATIVE_RESET_WITHOUT_CLOSURE");
        #1; request=0; data=0; phase=0;
        wait(rebased); @(negedge serviceClock); observed=0;
        wait(!close); @(negedge serviceClock);
        if(rebased || nativeReset || valid || acknowledge || samples) $fatal(1,"RECEIPT_MANAGED_OLD_REPLAY");
        send(70'h2000000abcdef0123);
      """,managed=true)
    }
    test(s"$name retained quiescing receipt POR aborts every pending stage and accepts a fresh token") {
      run("por","""
        open_consumer;
        for(stage=0;stage<6;stage=stage+1) begin
          @(negedge serviceClock); allow=0; data=70'h3fffffffffffffffff;
          #1; phase=1; request=1;
          repeat(stage) @(posedge serviceClock);
          #3; reset=1; request=0; data=0;
          #500; reset=0; phase=0; expected=0; workRun=1;
          repeat(8) @(negedge serviceClock);
          if(valid || acknowledge || samples || bits !== 0) $fatal(1,"RECEIPT_POR_REPLAY");
          send(70'h20000000000000001);
          // Reset again so the next case starts with the specified zero phase.
          #3; reset=1; request=0; data=0; #500; reset=0;
          phase=0; expected=0; workRun=1; repeat(8) @(negedge serviceClock);
        end
      """)
    }
    for(simultaneousClose <- Seq(false,true)) {
      test(s"$name retained quiescing receipt rejects premature rebase close=$simultaneousClose") {
        val failure=intercept[IllegalArgumentException] {
          run("illegal-rebase-"+simultaneousClose,s"""
            open_consumer; @(negedge serviceClock); #1;
            close=${if(simultaneousClose) 1 else 0}; rebase=1;
            repeat(3) @(negedge serviceClock);
            $$fatal(1,"RECEIPT_ILLEGAL_REBASE_SURVIVED");
          """)
        }
        val fatal=(if(click) "CLICK" else "BD")+"_BRIDGE_REBASE_BEFORE_CLOSE"
        assert(failure.getMessage.contains("Assertion failed: "+fatal))
        assert(failure.getMessage.contains("FATAL:") && !failure.getMessage.contains("RECEIPT_ILLEGAL_REBASE_SURVIVED"))
      }
    }
  }
}
