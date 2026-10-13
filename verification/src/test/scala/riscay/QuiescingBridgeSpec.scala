// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.AsyncModule
import org.scalatest.funsuite.AnyFunSuite

/** Independent source/destination pins and counters; raw reset is deliberately
  * distinct from the caller's synchronous close and coordinated rebase.
  */
class QuiescingBridgeFixture(click: Boolean,managed: Boolean=false) extends AsyncModule {
  val serviceClock=IO(Input(Clock())); val watchdogClock=IO(Input(Clock()))
  val scl=IO(Input(Bool())); val sda=IO(Input(Bool())); val sdaLow=IO(Output(Bool())); sdaLow:=false.B
  val gpioIn=IO(Input(UInt(32.W))); val adcMiso=IO(Input(Bool()))
  val programmed=IO(Output(Bool())); val locked=IO(Output(Bool())); val mode=IO(Output(UInt(3.W)))
  programmed:=false.B; locked:=false.B; mode:=0.U
  val applicationReset=IO(Input(Bool()))
  val close=IO(if(managed) Output(Bool()) else Input(Bool()))
  val rebase=IO(if(managed) Output(Bool()) else Input(Bool()))
  val observed=IO(Input(Bool())); val workRun=IO(Input(Bool()))
  val nativeReset=IO(Output(Bool())); val forceRun=IO(Output(Bool())); val workRunning=IO(Output(Bool()))
  val workEnable=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(workRun,false.B) }
  workRunning:=workEnable
  val transmitClock=if(managed) (serviceClock.asBool && workEnable).asClock else serviceClock
  val rxRequest=IO(Input(Bool())); val rxData=IO(Input(UInt(70.W))); val rxReady=IO(Input(Bool()))
  val rxAcknowledge=IO(Output(Bool())); val rxBits=IO(Output(UInt(70.W))); val rxValid=IO(Output(Bool()))
  val rxClosed=IO(Output(Bool())); val rxRebased=IO(Output(Bool()))
  val txValid=IO(Input(Bool())); val txData=IO(Input(UInt(70.W))); val txAcknowledge=IO(Input(Bool()))
  val txReady=IO(Output(Bool())); val txRequest=IO(Output(Bool())); val txBits=IO(Output(UInt(70.W)))
  val txClosed=IO(Output(Bool())); val txRebased=IO(Output(Bool()))
  val rxSamples=IO(Output(UInt(16.W))); val txSamples=IO(Output(UInt(16.W)))
  val rxSample=IO(Output(UInt(70.W))); val txSample=IO(Output(UInt(70.W)))
  if(click) {
    val rx=asyncChild("rx")(d => new riscay.click.ClickQuiescingToDecoupled(UInt(70.W),d))
    val tx=asyncChild("tx")(d => new riscay.click.DecoupledToClickQuiescing(UInt(70.W),d))
    rx.clock:=serviceClock; rx.close:=close; rx.rebase:=rebase
    rx.in.req:=rxRequest; rx.in.bits:=rxData; rx.out.ready:=rxReady
    rxAcknowledge:=rx.in.ack; rxValid:=rx.out.valid; rxBits:=rx.out.bits
    rxClosed:=rx.closed; rxRebased:=rx.rebased
    tx.clock:=transmitClock; tx.close:=close; tx.rebase:=rebase
    tx.in.valid:=txValid; tx.in.bits:=txData; tx.out.ack:=txAcknowledge
    txReady:=tx.in.ready; txRequest:=tx.out.req; txBits:=tx.out.bits
    txClosed:=tx.closed; txRebased:=tx.rebased
  } else {
    val rx=asyncChild("rx")(d => new riscay.bd.FourPhaseQuiescingToDecoupled(UInt(70.W),d))
    val tx=asyncChild("tx")(d => new riscay.bd.DecoupledToFourPhaseQuiescing(UInt(70.W),d))
    rx.clock:=serviceClock; rx.close:=close; rx.rebase:=rebase
    rx.in.req:=rxRequest; rx.in.bits:=rxData; rx.out.ready:=rxReady
    rxAcknowledge:=rx.in.ack; rxValid:=rx.out.valid; rxBits:=rx.out.bits
    rxClosed:=rx.closed; rxRebased:=rx.rebased
    tx.clock:=transmitClock; tx.close:=close; tx.rebase:=rebase
    tx.in.valid:=txValid; tx.in.bits:=txData; tx.out.ack:=txAcknowledge
    txReady:=tx.in.ready; txRequest:=tx.out.req; txBits:=tx.out.bits
    txClosed:=tx.closed; txRebased:=tx.rebased
  }
  if(managed) {
    if(click) {
      val coordinator=withClockAndReset(serviceClock,reset) { Module(new riscay.click.ClickResetBoundary(8)) }
      coordinator.io.observed:=observed; coordinator.io.closed:=rxClosed && txClosed
      coordinator.io.rebased:=rxRebased && txRebased; coordinator.io.rebaseIdle:= !rxRebased && !txRebased
      close:=coordinator.io.close; rebase:=coordinator.io.rebase
      nativeReset:=coordinator.io.nativeReset; forceRun:=coordinator.io.forceRun
    } else {
      val coordinator=withClockAndReset(serviceClock,reset) { Module(new riscay.bd.FourPhaseResetBoundary(8)) }
      coordinator.io.observed:=observed; coordinator.io.closed:=rxClosed && txClosed
      coordinator.io.rebased:=rxRebased && txRebased; coordinator.io.rebaseIdle:= !rxRebased && !txRebased
      close:=coordinator.io.close; rebase:=coordinator.io.rebase
      nativeReset:=coordinator.io.nativeReset; forceRun:=coordinator.io.forceRun
    }
  } else { nativeReset:=false.B; forceRun:=false.B }
  withClockAndReset(serviceClock,reset) {
    val rn=RegInit(0.U(16.W)); val rd=RegInit(0.U(70.W))
    when(rxValid && rxReady) { rn:=rn+1.U; rd:=rxBits }
    rxSamples:=rn; rxSample:=rd
  }
  withClockAndReset(transmitClock,reset) {
    val tn=RegInit(0.U(16.W)); val td=RegInit(0.U(70.W))
    when(txValid && txReady) { tn:=tn+1.U; td:=txData }
    txSamples:=tn; txSample:=td
  }
}

class QuiescingBridgeSpec extends AnyFunSuite {
  private val tasks="""
integer expectedRx=0,expectedTx=0,i,j;
reg [69:0] heldRx,heldTx;
reg heldAck,heldRequest;
task close_now_and_rebase; begin
  #1;
  heldRx=rxBits; heldTx=txBits; heldAck=rxAcknowledge; heldRequest=txRequest;
  close=1; clockEnabled=0; applicationReset=1;
  #1000;
  if(rxClosed || txClosed || rxRebased || txRebased)
    $fatal(1,"QUIESCE_ACK_WITHOUT_EDGE");
  if(rxBits !== heldRx || txBits !== heldTx || rxAcknowledge !== heldAck || txRequest !== heldRequest)
    $fatal(1,"QUIESCE_ASYNC_PAYLOAD_OR_PHASE_CLEAR");
  clockEnabled=1; @(posedge serviceClock); #1;
  if(!rxClosed || !txClosed || rxValid || txReady)
    $fatal(1,"QUIESCE_CAPTURE_NOT_CLOSED");
  if(rxBits !== heldRx || txBits !== heldTx || rxSamples != expectedRx || txSamples != expectedTx)
    $fatal(1,"QUIESCE_LAST_EDGE_CAPTURE");
  // Peer reset is legal only now: the last capture was a full edge earlier.
  @(negedge serviceClock); rxRequest=0; txAcknowledge=0; rebase=1;
  @(posedge serviceClock); #1;
  if(!rxRebased || !txRebased || rxAcknowledge || txRequest)
    $fatal(1,"QUIESCE_HISTORY_NOT_REBASED");
  repeat(12) begin
    @(negedge serviceClock); rxRequest=~rxRequest; txAcknowledge=~txAcknowledge;
    rxData=~rxData; txData=~txData; rxReady=1; txValid=1;
    applicationReset=~applicationReset;
    @(posedge serviceClock); #1;
    if(rxValid || txReady || rxBits !== heldRx || txBits !== heldTx ||
        rxSamples != expectedRx || txSamples != expectedTx || rxAcknowledge || txRequest)
      $fatal(1,"QUIESCE_CAPTURE_DURING_REBASE");
  end
  @(negedge serviceClock); rxRequest=0; txAcknowledge=0; rxReady=0; txValid=0;
  rebase=0; applicationReset=0;
  repeat(3) @(negedge serviceClock);
  close=0;
  repeat(5) @(negedge serviceClock);
  if(rxValid || rxAcknowledge || txRequest || !txReady || rxClosed || txClosed ||
      rxSamples != expectedRx || txSamples != expectedTx)
    $fatal(1,"QUIESCE_REPLAY_AFTER_RESTART");
end endtask
task close_and_rebase; begin
  @(negedge serviceClock); close_now_and_rebase;
end endtask
task send_rx(input phase,input [69:0] value); begin
  @(negedge serviceClock); rxData=value; #1; rxRequest=phase;
  wait(rxValid);
  repeat(3) begin @(negedge serviceClock);
    if(!rxValid || rxBits !== value || rxAcknowledge === phase)
      $fatal(1,"QUIESCE_RX_BACKPRESSURE");
  end
  rxReady=1; @(posedge serviceClock); #1; expectedRx=expectedRx+1;
  if(rxSamples != expectedRx || rxSample !== value || rxAcknowledge !== phase || rxValid)
    $fatal(1,"QUIESCE_RX_TRANSFER_IDENTITY");
  @(negedge serviceClock); rxReady=0;
end endtask
task send_tx(input phase,input [69:0] value); begin
  @(negedge serviceClock); txData=value; txValid=1;
  @(posedge serviceClock); while(!txReady) @(posedge serviceClock);
  #1; expectedTx=expectedTx+1;
  if(txSamples != expectedTx || txSample !== value || txRequest === phase)
    $fatal(1,"QUIESCE_TX_EARLY_PUBLICATION");
  @(negedge serviceClock); txValid=0; txData=~value;
  @(posedge serviceClock); #1;
  if(txRequest !== phase || txBits !== value) $fatal(1,"QUIESCE_TX_PUBLICATION");
  repeat(4) begin @(negedge serviceClock);
    if(txRequest !== phase || txBits !== value || txReady)
      $fatal(1,"QUIESCE_TX_BACKPRESSURE");
  end
  txAcknowledge=phase;
  repeat(4) @(negedge serviceClock);
end endtask
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    val rxReturn=if(click) "" else "rxRequest=0; repeat(5) @(negedge serviceClock);"
    val txReturn=if(click) "" else "txAcknowledge=0; repeat(5) @(negedge serviceClock);"
    for(simultaneousClose <- Seq(false,true)) {
      test(s"$name quiescing bridges reject rebase before acknowledged closure (close=$simultaneousClose)") {
        val failure=intercept[IllegalArgumentException] {
          ClockedSimulation.run(new QuiescingBridgeFixture(click),name+s"-quiescing-illegal-rebase-$simultaneousClose",s"""
            @(negedge serviceClock); #1; close=${if(simultaneousClose) 1 else 0}; rebase=1;
            repeat(3) @(negedge serviceClock);
            $$fatal(1,"ILLEGAL_REBASE_WAS_NOT_REJECTED");
          """,serviceHalfPeriodNs=25)
        }
        val expected=(if(click) "CLICK" else "BD")+"_BRIDGE_REBASE_BEFORE_CLOSE"
        assert(failure.getMessage.contains("Assertion failed: "+expected))
        assert(failure.getMessage.contains("FATAL:") && !failure.getMessage.contains("ILLEGAL_REBASE_WAS_NOT_REJECTED"))
      }
    }
    test(s"$name quiescing bridges cannot acknowledge rebase without a receiving clock edge") {
      ClockedSimulation.run(new QuiescingBridgeFixture(click),name+"-quiescing-stopped-rebase","""
        @(negedge serviceClock); #1; close=1;
        repeat(3) @(negedge serviceClock);
        if(!rxClosed || !txClosed || rxRebased || txRebased) $fatal(1,"STOPPED_REBASE_PRECONDITION");
        #1; clockEnabled=0; rebase=1;
        #1000;
        if(rxRebased || txRebased) $fatal(1,"REBASE_RECEIPT_WITHOUT_EDGE");
        clockEnabled=1; @(posedge serviceClock); #1;
        if(!rxRebased || !txRebased || rxValid || txReady) $fatal(1,"REBASE_RECEIPT_MISSING_AFTER_EDGE");
      """,serviceHalfPeriodNs=25)
    }
    test(s"$name quiescing bridges retain payload and native history until explicit synchronous closure") {
      val traffic=(0 until 12).map { n =>
        val phase=if(click) (n+1)%2 else 1
        s"""
          send_rx($phase,70'h${((BigInt(1)<<69) | (BigInt(1)<<(n*5))).toString(16)});
          $rxReturn
          send_tx($phase,70'h${(((BigInt(1)<<70)-1) ^ (BigInt(1)<<(n*5))).toString(16)});
          $txReturn
        """
      }.mkString("\n")
      ClockedSimulation.run(new QuiescingBridgeFixture(click),name+"-quiescing-normal",
        traffic+"\nclose_and_rebase; send_rx(1,70'h1234); "+rxReturn+
          " send_tx(1,70'h5678); "+txReturn,tasks,serviceHalfPeriodNs=25)
    }
    for(stage <- 0 until 6; previousPhase <- (if(click) Seq(0,1) else Seq(0))) {
      test(s"$name quiescing bridges close at receive stage $stage after phase $previousPhase") {
        val prime=if(previousPhase==1) "send_rx(1,70'h101); send_tx(1,70'h202);" else ""
        val phase=1-previousPhase
        val body=s"""
          $prime
          @(negedge serviceClock); #1; rxData=70'h200000000000123456; rxRequest=$phase;
          txData=70'h100000000000fedcba; txValid=1;
          // Transmit capture is observed independently; receive remains stalled.
          @(posedge serviceClock); #1; expectedTx=expectedTx+1;
          @(negedge serviceClock); txValid=0;
          repeat($stage) @(posedge serviceClock);
          close_and_rebase;
          send_rx(1,70'h300000000000000007); $rxReturn
          send_tx(1,70'h3fffffffffffffffe1); $txReturn
        """
        ClockedSimulation.run(new QuiescingBridgeFixture(click),name+s"-quiescing-stage-$stage-$previousPhase",
          body,tasks,serviceHalfPeriodNs=25)
      }
    }
    test(s"$name quiescing bridges cancel before transmit publication without clearing captured data") {
      ClockedSimulation.run(new QuiescingBridgeFixture(click),name+"-quiescing-before-publish","""
        @(negedge serviceClock); txData=70'h3fffffff0011223344; txValid=1;
        @(posedge serviceClock); #1; expectedTx=expectedTx+1;
        if(txRequest || txBits !== txData) $fatal(1,"QUIESCE_PREPUBLICATION_PRECONDITION");
        @(negedge serviceClock); txValid=0; close_now_and_rebase;
        send_tx(1,70'h1abcdef);
      """+txReturn,tasks,serviceHalfPeriodNs=25)
    }
    for(returnEdges <- 0 until 4) {
      test(s"$name quiescing bridges close after receive acceptance at return edge $returnEdges") {
        val returnRequest=if(click) "" else "rxRequest=0;"
        ClockedSimulation.run(new QuiescingBridgeFixture(click),name+s"-quiescing-rx-return-$returnEdges",s"""
          send_rx(1,70'h123456789abcdef01);
          $returnRequest
          repeat($returnEdges) @(posedge serviceClock);
          ${if(returnEdges==0) "close_now_and_rebase;" else "close_and_rebase;"}
          send_rx(1,70'h200000000000000011); $rxReturn
        """,tasks,serviceHalfPeriodNs=25)
      }
      test(s"$name quiescing bridges close during transmit acknowledgment at return edge $returnEdges") {
        ClockedSimulation.run(new QuiescingBridgeFixture(click),name+s"-quiescing-tx-return-$returnEdges",s"""
          @(negedge serviceClock); txData=70'h102030405060708; txValid=1;
          @(posedge serviceClock); #1; expectedTx=expectedTx+1;
          @(negedge serviceClock); txValid=0;
          wait(txRequest); @(negedge serviceClock); txAcknowledge=1;
          repeat($returnEdges) @(posedge serviceClock);
          ${if(returnEdges==0) "close_now_and_rebase;" else "close_and_rebase;"}
          send_tx(1,70'h210000000000000011); $txReturn
        """,tasks,serviceHalfPeriodNs=25)
      }
    }
    test(s"$name quiescing bridges resume an intact native transaction without rebasing its phase") {
      val cases=(0 until 4).map { n =>
        val phase=if(click) (n+1)%2 else 1
        s"""
          @(negedge serviceClock); rxData=70'h10000000000000000${n+1}; rxRequest=$phase;
          txData=70'h30000000000000000${n+1}; txValid=1;
          @(posedge serviceClock); #1; expectedTx=expectedTx+1;
          @(negedge serviceClock); txValid=0;
          wait(rxValid && txRequest === $phase);
          @(negedge serviceClock); #1; close=1;
          repeat(4) @(negedge serviceClock);
          if(!rxClosed || !txClosed || rebase || rxAcknowledge === $phase)
            $$fatal(1,"QUIESCE_RESUME_PRECONDITION");
          txAcknowledge=$phase;
          repeat(4) @(negedge serviceClock);
          if(txReady || rxValid || txRequest !== $phase || txSamples != expectedTx || rxSamples != expectedRx)
            $$fatal(1,"QUIESCE_RESUME_CLOSED_TRANSFER");
          close=0; rxReady=1;
          @(posedge serviceClock); #1; expectedRx=expectedRx+1;
          if(rxSamples != expectedRx || rxSample !== rxData || rxAcknowledge !== $phase)
            $$fatal(1,"QUIESCE_RESUME_RX_IDENTITY");
          @(negedge serviceClock); rxReady=0;
          $rxReturn
          repeat(5) @(negedge serviceClock);
          $txReturn
          if(!txReady || txSamples != expectedTx) $$fatal(1,"QUIESCE_RESUME_TX_DUPLICATE");
        """
      }.mkString("\n")
      ClockedSimulation.run(new QuiescingBridgeFixture(click),name+"-quiescing-resume",cases,tasks,serviceHalfPeriodNs=25)
    }
  }
}

class ResetBoundarySpec extends AnyFunSuite {
  private val monitors="""
integer heldEdges=0,resets=0;
reg armed=0;
always @(posedge serviceClock) begin
  if(reset || observed || !rebase || !rxRebased || !txRebased) heldEdges=0;
  else if(nativeReset) heldEdges=heldEdges+1;
end
always @(posedge nativeReset) if(armed && !reset) begin
  if(!rxClosed || !txClosed || !close) $fatal(1,"RESET_BOUNDARY_DESTROYED_BEFORE_CLOSE");
  resets=resets+1;
end
always @(negedge nativeReset) if(!reset) begin
  if(heldEdges < 8 || !rxClosed || !txClosed || !close)
    $fatal(1,"RESET_BOUNDARY_SHORT_HOLD edges=%0d",heldEdges);
end
always @(negedge close) if(!reset) begin
  if(nativeReset || rebase || rxRebased || txRebased || observed)
    $fatal(1,"RESET_BOUNDARY_PREMATURE_OPEN");
end
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name reset boundary waits for stopped work capture and restart acknowledgments") {
      ClockedSimulation.run(new QuiescingBridgeFixture(click,managed=true),name+"-reset-boundary-stopped","""
        repeat(12) begin @(negedge serviceClock);
          if(!close || !nativeReset || !forceRun || txClosed)
            $fatal(1,"RESET_BOUNDARY_POR_CLOSURE");
        end
        #1; workRun=1; wait(!close); @(negedge serviceClock); armed=1;
        rxData=70'h3aaaa5555ffff0000; rxRequest=1;
        txData=70'h2000000123456789; txValid=1;
        @(posedge serviceClock); #1;
        @(negedge serviceClock); txValid=0;
        wait(rxValid && txRequest); @(negedge serviceClock); #1; workRun=0;
        repeat(3) @(negedge serviceClock);
        if(workRunning || nativeReset) $fatal(1,"RESET_BOUNDARY_STOP_PRECONDITION");
        #1; observed=1; applicationReset=1;
        repeat(12) begin @(negedge serviceClock);
          if(!rxClosed || txClosed || nativeReset || !close || !forceRun || rebase ||
              rxSamples != 0 || txSamples != 1)
            $fatal(1,"RESET_BOUNDARY_SKIPPED_WORK_CLOSE");
        end
        #1; workRun=1; wait(nativeReset);
        #1; rxRequest=0; txAcknowledge=0;
        wait(rxRebased && txRebased); @(negedge serviceClock); #1; observed=0;
        wait(!nativeReset);
        #1; workRun=0;
        // Rebase falls after the service edge. Its service receipt clears on
        // the next edge; the stopped work receipt must remain asserted.
        @(posedge serviceClock); #1;
        repeat(12) begin @(negedge serviceClock);
          if(!close || !forceRun || nativeReset || rebase || !txRebased || rxRebased)
            $fatal(1,"RESET_BOUNDARY_SKIPPED_WORK_RESTART");
        end
        // A new observed episode during reopening must keep the boundary shut.
        #1; observed=1; repeat(3) @(negedge serviceClock);
        if(!nativeReset || !close || !rebase) $fatal(1,"RESET_BOUNDARY_REOPEN_RETRIGGER");
        #1; workRun=1; repeat(4) @(negedge serviceClock); #1; observed=0;
        wait(!close); @(negedge serviceClock);
        if(resets != 2 || rxSamples != 0 || txSamples != 1 || rxValid || txRequest || !txReady)
          $fatal(1,"RESET_BOUNDARY_OLD_REQUEST_REPLAY");
        rxData=70'h3deadbeef00112233; rxRequest=1; rxReady=1;
        wait(rxSamples == 1); @(negedge serviceClock);
        if(rxSample !== rxData || !rxAcknowledge) $fatal(1,"RESET_BOUNDARY_FRESH_PAYLOAD");
      """,monitors,serviceHalfPeriodNs=25)
    }
    for(retriggerEdge <- Seq(0,3,7,8)) {
      test(s"$name reset boundary restarts its continuous hold at edge $retriggerEdge") {
        ClockedSimulation.run(new QuiescingBridgeFixture(click,managed=true),name+s"-reset-boundary-hold-$retriggerEdge",s"""
          workRun=1; wait(!close); @(negedge serviceClock); armed=1;
          #1; observed=1; wait(nativeReset && rxRebased && txRebased);
          @(negedge serviceClock); #1; observed=0;
          repeat($retriggerEdge) @(negedge serviceClock);
          #1; observed=1;
          repeat(4) @(negedge serviceClock);
          if(!close || !nativeReset || !forceRun) $$fatal(1,"RESET_BOUNDARY_HOLD_RETRIGGER");
          #1; observed=0; wait(!close); @(negedge serviceClock);
          if(rxValid || txRequest || !txReady) $$fatal(1,"RESET_BOUNDARY_HOLD_REPLAY");
        """,monitors,serviceHalfPeriodNs=25)
      }
    }
  }
}
