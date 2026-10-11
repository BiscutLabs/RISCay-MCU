// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Count accepted commands/publications independently of native owner state. */
class PublicationSourceSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"publication-source",Vector.empty,Vector.empty)),watchdogCycles=10000000)
  private val tasks="""
integer accepted=0,answers=0,i,n;
integer reserves[0:1],decisions[0:1],commits[0:1],publications[0:1],drains[0:1],commands[0:1],published[0:1];
initial for(i=0;i<2;i=i+1) begin
  reserves[i]=0;decisions[i]=0;commits[i]=0;publications[i]=0;drains[i]=0;commands[i]=0;published[i]=0;
end
always @(posedge serviceClock) if(!reset) begin
  if(request_valid && request_ready) accepted=accepted+1;
  if(response_valid && response_ready) answers=answers+1;
  for(i=0;i<2;i=i+1) begin
    if(reserveAccepted[i]) reserves[i]=reserves[i]+1;
    if(decisionAccepted[i]) decisions[i]=decisions[i]+1;
    if(committedDecision[i]) commits[i]=commits[i]+1;
    if(publicationAccepted[i]) publications[i]=publications[i]+1;
    if(drainAccepted[i]) drains[i]=drains[i]+1;
    if(commandAccepted[i]) commands[i]=commands[i]+1;
    if(replyAccepted[i]) published[i]=published[i]+1;
  end
end
task offer(input [31:0] address,input [31:0] value); begin
  @(negedge serviceClock); request_valid=1; request_bits_operation=2;
  request_bits_address=address; request_bits_data=value; request_bits_mask=15;
end endtask
task accepted_offer; begin
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
end endtask
task answer; begin
  wait(response_valid); if(response_bits_error || response_bits_data !== 0)
    $fatal(1,"PUBLICATION_BUS_RESPONSE");
  @(negedge serviceClock); response_ready=1;
  @(posedge serviceClock); #1; response_ready=0;
end endtask
task write_bus(input [31:0] address,input [31:0] value); begin
  offer(address,value); accepted_offer; answer;
end endtask
task raw_reset; begin
  @(negedge serviceClock); #7; applicationReset=1; request_valid=0;
  #1; if(sourceDebt !== 3) $fatal(1,"PUBLICATION_RAW_RESET_DEBT");
  #6; applicationReset=0;
end endtask
task settled; begin
  // Scoped bounded progress: 1000 service edges exceed the qualified native
  // return, bridge synchronization and recovery paths when all holds are clear.
  // Keep fast source reuse directed separately in the drain and native tests.
  #100000;
  if(sourceDebt !== 0 || sourceBusy !== 0) $fatal(1,"PUBLICATION_SOURCE_DRAIN_BOUND");
  wait(sourceDebt==0 && sourceBusy==0); repeat(5) @(negedge serviceClock);
end endtask
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture: SocTop=if(click) new ClickPublicationSourceFixture(p) else new BdPublicationSourceFixture(p)
    test(s"$name publication sources: deadline validation waits for both grants and decision ingresses") {
      ClockedSimulation.run(fixture,name+"-publication-atomic","""
        #10000; settled;
        for(n=0;n<2;n=n+1) begin
          @(negedge serviceClock); holdGrant=1<<n;
          offer(32'h30000008,100+n); wait(grantWaiting==3); #3000;
          if(accepted != n || commits[0] != n || commits[1] != n || !validatedReply)
            $fatal(1,"PUBLICATION_PARTIAL_GRANT_COMMIT");
          @(negedge serviceClock); holdDecision=1<<(1-n); holdGrant=0; #3000;
          if(accepted != n || decisions[0] != n || decisions[1] != n || !validatedReply)
            $fatal(1,"PUBLICATION_PARTIAL_DECISION_COMMIT");
          @(negedge serviceClock); holdDecision=0; accepted_offer; answer; settled;
          if(accepted != n+1 || answers != n+1 || commits[0] != n+1 || commits[1] != n+1 ||
             commands[0] != n+1 || commands[1] != n+1 || publications[0] != n+1 || publications[1] != n+1)
            $fatal(1,"PUBLICATION_ATOMIC_COUNTS");
        end
      """,tasks)
    }
    test(s"$name publication sources: queued uncommitted grants cancel across repeated raw resets") {
      ClockedSimulation.run(fixture,name+"-publication-cancel","""
        #10000; settled; @(negedge serviceClock); holdGrant=3;
        offer(32'h30000008,100); wait(grantWaiting==3); #2;
        raw_reset; #1000; raw_reset;
        @(negedge serviceClock); holdGrant=0; settled;
        if(accepted || answers || response_valid || commits[0] || commits[1] ||
           commands[0] || commands[1] || publications[0] || publications[1] ||
           decisions[0] != 1 || decisions[1] != 1)
          $fatal(1,"PUBLICATION_CANCELLED_GRANT_EFFECT");
        write_bus(32'h30000018,1); settled;
        if(accepted != 1 || answers != 1 || commands[0] != 1 || commands[1] || gpioOut !== 1)
          $fatal(1,"PUBLICATION_CANCELLED_GRANT_REUSE");
      """,tasks)
    }
    test(s"$name publication sources: reset cancels staged telemetry but retains ordered housekeeping effects") {
      ClockedSimulation.run(fixture,name+"-publication-staged-reset","""
        #10000; settled; @(negedge serviceClock); holdCommand=3;
        offer(32'h30000008,100); accepted_offer; #1000;
        if(commits[0] != 1 || commits[1] != 1 || commands[0] || commands[1] || response_valid)
          $fatal(1,"PUBLICATION_STAGED_COMMIT");
        raw_reset; #1000; @(negedge serviceClock); holdCommand=0; settled; #10000;
        if(accepted != 1 || answers || response_valid || commands[0] || commands[1] != 1 ||
           publications[0] || publications[1] != 1 || drains[0] != 1 || drains[1] != 1)
          $fatal(1,"PUBLICATION_STAGED_RESET_EFFECTS");
        write_bus(32'h30000018,1); settled;
        if(answers != 1 || gpioOut !== 1) $fatal(1,"PUBLICATION_STAGED_RESET_REUSE");
      """,tasks)
    }
    test(s"$name publication sources: reset during stalled actual publication cannot return an old CPU reply") {
      ClockedSimulation.run(fixture,name+"-publication-held-reset","""
        #10000; settled; @(negedge serviceClock); holdPublication=1;
        offer(32'h30000018,1); accepted_offer; wait(replyWaiting[0]); #3000;
        if(response_valid || commands[0] != 1 || publications[0] || published[0])
          $fatal(1,"PUBLICATION_BEFORE_RECEIPT_ACCEPTANCE");
        raw_reset; #1000; raw_reset;
        @(negedge serviceClock); holdPublication=0; settled; #10000;
        if(response_valid || answers || publications[0] != 1 || published[0] != 1 || gpioOut !== 0)
          $fatal(1,"PUBLICATION_RESET_REPLAYED_REPLY");
        write_bus(32'h30000018,1); settled;
        if(answers != 1 || publications[0] != 2 || commands[0] != 2 || gpioOut !== 1)
          $fatal(1,"PUBLICATION_RESET_REUSE_COUNTS");
      """,tasks)
    }
    test(s"$name publication sources: a stalled drain receipt prevents source reuse after CPU response") {
      ClockedSimulation.run(fixture,name+"-publication-drain","""
        #10000; settled; @(negedge serviceClock); holdDrain=1;
        write_bus(32'h30000018,1);
        offer(32'h30000018,0); wait(validatedReply); #5000;
        if(accepted != 1 || answers != 1 || commands[0] != 1 || publications[0] != 1 || drains[0])
          $fatal(1,"PUBLICATION_REUSED_BEFORE_DRAIN");
        @(negedge serviceClock); holdDrain=0; accepted_offer; answer; settled;
        if(accepted != 2 || answers != 2 || publications[0] != 2 || commands[0] != 2 || drains[0] != 2 || gpioOut !== 0)
          $fatal(1,"PUBLICATION_DRAIN_REUSE_COUNTS");
      """,tasks)
    }
    test(s"$name publication sources: housekeeping publication held across resets cannot restore old projection or reply") {
      ClockedSimulation.run(fixture,name+"-publication-housekeeping-held-reset","""
        #10000; settled; @(negedge serviceClock); holdPublication=2;
        offer(32'h30000038,1); accepted_offer; wait(replyWaiting[1]); #3000;
        if(response_valid || commands[1] != 1 || publications[1] || published[1])
          $fatal(1,"PUBLICATION_BEFORE_RECEIPT_ACCEPTANCE");
        raw_reset; #1000; raw_reset;
        @(negedge serviceClock); holdPublication=0; settled; #10000;
        if(response_valid || answers || publications[1] != 1 || published[1] != 1 || visibleMask !== 15)
          $fatal(1,"PUBLICATION_RESET_REPLAYED_REPLY");
        write_bus(32'h30000038,1); settled;
        if(answers != 1 || publications[1] != 2 || commands[1] != 2 || visibleMask !== 1)
          $fatal(1,"PUBLICATION_RESET_REUSE_COUNTS");
      """,tasks)
    }
    test(s"$name publication sources: housekeeping drain held after response prevents immediate reuse") {
      ClockedSimulation.run(fixture,name+"-publication-housekeeping-drain","""
        #10000; settled; @(negedge serviceClock); holdDrain=2;
        write_bus(32'h30000038,1);
        offer(32'h30000038,0); wait(validatedReply); #5000;
        if(accepted != 1 || answers != 1 || commands[1] != 1 || publications[1] != 1 || drains[1])
          $fatal(1,"PUBLICATION_REUSED_BEFORE_DRAIN");
        @(negedge serviceClock); holdDrain=0; accepted_offer; answer; settled;
        if(accepted != 2 || answers != 2 || publications[1] != 2 || commands[1] != 2 || drains[1] != 2 || visibleMask !== 0)
          $fatal(1,"PUBLICATION_DRAIN_REUSE_COUNTS");
      """,tasks)
    }
  }
}
