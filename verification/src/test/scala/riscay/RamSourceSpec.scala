// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdRamSourceFixture(p: SocParameters) extends SramCrossingFixture(p) {
  val holdGrant=IO(Input(Bool())); val holdDecision=IO(Input(Bool()))
  val holdPublication=IO(Input(Bool()))
  fabric.io.ramSource.grant.valid:=ramGrant.out.valid && !holdGrant
  ramGrant.out.ready:=fabric.io.ramSource.grant.ready && !holdGrant
  ramDecision.in.valid:=fabric.io.ramSource.decision.valid && !holdDecision
  fabric.io.ramSource.decision.ready:=ramDecision.in.ready && !holdDecision
  ramPublication.in.valid:=fabric.io.ramSource.publication.valid && !holdPublication
  fabric.io.ramSource.publication.ready:=ramPublication.in.ready && !holdPublication
  val reserved=IO(Output(Bool())); reserved:=ramReserve.in.fire
  val grantWaiting=IO(Output(Bool())); grantWaiting:=ramGrant.out.valid
  val sourceDebt=IO(Output(Bool())); sourceDebt:=ramResetDebt
  val sourceEmpty=IO(Output(Bool())); sourceEmpty:=ramSourceEmpty
  val sourceDraining=IO(Output(Bool())); sourceDraining:=fabric.io.ramSource.draining
  val wordAccepted=IO(Output(Bool())); wordAccepted:=ramAccess.io.request.fire
  val publicationAccepted=IO(Output(Bool())); publicationAccepted:=ramPublication.in.fire
  val cancelled=IO(Output(Bool())); cancelled:=ramDecision.in.fire && !ramDecision.in.bits
}

class ClickRamSourceFixture(p: SocParameters) extends ClickSramCrossingFixture(p) {
  val holdGrant=IO(Input(Bool())); val holdDecision=IO(Input(Bool()))
  val holdPublication=IO(Input(Bool()))
  fabric.io.ramSource.grant.valid:=ramGrant.out.valid && !holdGrant
  ramGrant.out.ready:=fabric.io.ramSource.grant.ready && !holdGrant
  ramDecision.in.valid:=fabric.io.ramSource.decision.valid && !holdDecision
  fabric.io.ramSource.decision.ready:=ramDecision.in.ready && !holdDecision
  ramPublication.in.valid:=fabric.io.ramSource.publication.valid && !holdPublication
  fabric.io.ramSource.publication.ready:=ramPublication.in.ready && !holdPublication
  val reserved=IO(Output(Bool())); reserved:=ramReserve.in.fire
  val grantWaiting=IO(Output(Bool())); grantWaiting:=ramGrant.out.valid
  val sourceDebt=IO(Output(Bool())); sourceDebt:=ramResetDebt
  val sourceEmpty=IO(Output(Bool())); sourceEmpty:=ramSourceEmpty
  val sourceDraining=IO(Output(Bool())); sourceDraining:=fabric.io.ramSource.draining
  val wordAccepted=IO(Output(Bool())); wordAccepted:=ramAccess.io.request.fire
  val publicationAccepted=IO(Output(Bool())); publicationAccepted:=ramPublication.in.fire
  val cancelled=IO(Output(Bool())); cancelled:=ramDecision.in.fire && !ramDecision.in.bits
}

/** Counts are taken at the CPU, word crossing and actual macro pins independently. */
class RamSourceSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"ram-source",Vector.empty,Vector.empty)),watchdogCycles=10000000)
  test("application reset envelope rejects an overclock and oversized custom BD/Click timing") {
    import chiselasync.metadata.{BundledTiming,ClickTiming,ModelTime,ExportDesign}
    import java.nio.file.{Files,Paths}
    intercept[IllegalArgumentException](p.copy(serviceHz=21000000))
    val root=Paths.get("build/async-ram-reset-policy"); Files.createDirectories(root)
    for(execute <- Seq(false,true)) {
      val oversized=BundledTiming.Simulation.copy(outputDelay=ModelTime.ps(300000))
      val error=intercept[IllegalArgumentException] {
        ExportDesign.emit(new riscay.bd.FourPhaseSoc(p,
          timing=if(execute) BundledTiming.Simulation else oversized,
          executeTiming=if(execute) oversized else BundledTiming.Simulation),
          Files.createTempDirectory(root,"bd-oversized"))
      }
      assert(error.getMessage.contains("reset-settlement budget"),error.getMessage)
    }
    val error=intercept[IllegalArgumentException] {
      ExportDesign.emit(new riscay.click.ClickSoc(p,executeData=ModelTime.ps(300000)),
        Files.createTempDirectory(root,"click-oversized"))
    }
    assert(error.getMessage.contains("reset-settlement budget"),error.getMessage)
  }
  private val tasks="""
    integer accepted=0,words=0,writes=0,published=0,cancelledCount=0;
    integer n,beforeAccepted,beforeWords,beforeWrites,beforePublished,beforeCancel;
    reg [31:0] expected;
    always @(posedge serviceClock) if(!reset) begin
      if(request_valid && request_ready) accepted=accepted+1;
      if(wordAccepted) words=words+1;
      if(publicationAccepted) published=published+1;
      if(cancelled) cancelledCount=cancelledCount+1;
      if(!dut.fabric_ram_macros_0.CEN && !dut.fabric_ram_macros_0.GWEN) writes=writes+1;
      if(sourceDebt && wordAccepted) $fatal(1,"RAM_SOURCE_RESET_DEBT_ADMITTED");
      if(sourceDraining && sleepEligible) $fatal(1,"RAM_SOURCE_DRAIN_SLEPT");
    end
    task offer(input [1:0] op,input [31:0] data); begin
      @(negedge serviceClock); request_valid=1; request_bits_operation=op;
      request_bits_address=32'h20000000; request_bits_data=data; request_bits_mask=15;
    end endtask
    task admitted; begin
      @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
      #1; request_valid=0;
    end endtask
    task answer(input [31:0] expected); begin
      wait(response_valid);
      if(response_bits_error || response_bits_data !== expected) $fatal(1,"RAM_SOURCE_RESULT");
      repeat(4) begin @(negedge serviceClock);
        if(!response_valid || response_bits_error || response_bits_data !== expected)
          $fatal(1,"RAM_SOURCE_HELD_RESULT");
      end
      response_ready=1; @(posedge serviceClock); #1; response_ready=0;
    end endtask
    task two_short_resets; begin
      // Called just after an edge, or at its falling edge: both pulses fit
      // between rising edges of the 50 ns service clock.
      applicationReset=1; #2; applicationReset=0; #2;
      applicationReset=1; #2; applicationReset=0; #2;
      if(!sourceDebt) $fatal(1,"RAM_SOURCE_MISSED_SHORT_RESET");
    end endtask
    task idle_check; begin
      wait(!sourceDebt && !sourceDraining && !memoryBusy);
      repeat(8) @(negedge serviceClock);
      if(response_valid) $fatal(1,"RAM_SOURCE_STALE_CPU_REPLY");
    end endtask
  """
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture=if(click) new ClickRamSourceFixture(p) else new BdRamSourceFixture(p)
    test(s"$name RAM source: queued reservation, held grant and blocked decision cancel without accepting a word") {
      ClockedSimulation.run(fixture,name+"-ram-reservation-cancel","""
        for(n=0;n<9;n=n+1) begin
          idle_check(); beforeAccepted=accepted; beforeWords=words; beforeWrites=writes; beforeCancel=cancelledCount;
          holdGrant=(n%3!=2); holdDecision=(n%3==2);
          offer(2,32'hbad00000+n);
          if(n%3==0) begin
            wait(reserved); @(posedge serviceClock); #1;
          end else begin wait(grantWaiting); @(negedge serviceClock); end
          if(accepted != beforeAccepted || words != beforeWords || writes != beforeWrites)
            $fatal(1,"RAM_SOURCE_PRECOMMIT_STALL_IGNORED");
          request_valid=0; two_short_resets();
          repeat(8) begin @(negedge serviceClock);
            if(!sourceDebt || words != beforeWords || writes != beforeWrites || response_valid)
              $fatal(1,"RAM_SOURCE_CANCEL_DEBT_LOST");
          end
          holdGrant=0; holdDecision=0; idle_check();
          if(cancelledCount-beforeCancel != 1 || words != beforeWords || writes != beforeWrites || accepted != beforeAccepted)
            $fatal(1,"RAM_SOURCE_CANCEL_EFFECT_COUNT");
          offer(2,32'h12340000+n); admitted(); answer(0);
          offer(1,0); admitted(); answer(32'h12340000+n);
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_ram_source"))
    }
    test(s"$name RAM source: short resets after CPU acceptance and at every held lane preserve exactly one accepted store") {
      ClockedSimulation.run(fixture,name+"-ram-accepted-reset","""
        for(n=0;n<6;n=n+1) begin
          idle_check(); beforeWords=words; beforeWrites=writes; beforePublished=published;
          heldLane=n-1; holdByte=(n>=1 && n<=4); holdPublication=(n==5);
          offer(2,32'h89abc000+n); admitted();
          if(n>=1 && n<=4) begin wait(byteWaiting); @(negedge serviceClock); end
          if(n==5) begin wait(wordWaiting); @(negedge serviceClock); end
          two_short_resets();
          @(negedge serviceClock); holdByte=0; holdPublication=0;
          idle_check();
          if(words-beforeWords != 1 || writes-beforeWrites != 4 || published-beforePublished != 1)
            $fatal(1,"RAM_SOURCE_ACCEPTED_EFFECT_COUNT");
          offer(1,0); admitted(); answer(32'h89abc000+n);
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_ram_source"))
    }
    test(s"$name RAM source: sub-cycle reset restarts the complete application island after its full settling hold") {
      ClockedSimulation.run(fixture,name+"-ram-reset-settlement","""
        offer(2,32'hfedcba98); admitted(); answer(0);
        for(n=0;n<8;n=n+1) begin
          idle_check(); offer(1,0); admitted(); answer(32'hfedcba98); idle_check();
          @(negedge serviceClock); two_short_resets();
          // Shift part of the release history, then pulse again while the
          // qualified reset is still high. Both native parities are exercised.
          repeat(3) @(negedge serviceClock); two_short_resets();
          beforeResetRelease=$realtime;
          repeat(6) begin @(negedge serviceClock);
            if(!systemReset || response_valid) $fatal(1,"APPLICATION_RESET_EARLY_RELEASE");
          end
          wait(!systemReset);
          if($realtime-beforeResetRelease < 350) $fatal(1,"APPLICATION_RESET_SETTLEMENT_HOLD");
          idle_check();
        end
      """,tasks+"real beforeResetRelease;",serviceHalfPeriodNs=25,deadlineNs=2000000,
        maximumDelaySubtree=Some("ca_child_completion"))
    }
    test(s"$name RAM source: old publication fences a fresh request and every recovery pulse restarts safe history") {
      ClockedSimulation.run(fixture,name+"-ram-publication-fence","""
        for(n=0;n<6;n=n+1) begin
          idle_check(); holdPublication=1; beforeWords=words; beforeWrites=writes;
          offer(2,32'h76540000+n); admitted(); wait(wordWaiting); @(negedge serviceClock);
          two_short_resets();
          offer(1,0);
          repeat(12) begin @(negedge serviceClock);
            if(!sourceDebt || request_ready || response_valid || words-beforeWords != 1)
              $fatal(1,"RAM_SOURCE_PUBLICATION_FENCE_BYPASS");
          end
          holdPublication=0; admitted(); answer(32'h76540000+n);
          idle_check();
          if(words-beforeWords != 2 || writes-beforeWrites != 4) $fatal(1,"RAM_SOURCE_PUBLICATION_EFFECT_COUNT");
          @(negedge serviceClock); two_short_resets();
          @(posedge serviceClock); #1;
          if(!sourceDebt) $fatal(1,"RAM_SOURCE_EARLY_FIRST_RECOVERY");
          // Reset the already partially accumulated safe history.
          @(negedge serviceClock); two_short_resets();
          @(posedge serviceClock); #1;
          if(!sourceDebt) $fatal(1,"RAM_SOURCE_SECOND_PULSE_IGNORED");
          idle_check();
        end
      """,tasks,serviceHalfPeriodNs=25,deadlineNs=2000000,maximumDelaySubtree=Some("ca_child_ram_source"))
    }
  }
}
