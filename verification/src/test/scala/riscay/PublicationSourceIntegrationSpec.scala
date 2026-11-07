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
reg checkBorrowed=0;
integer reserves[0:1],decisions[0:1],commits[0:1],publications[0:1],drains[0:1],commands[0:1],published[0:1];
initial for(i=0;i<2;i=i+1) begin
  reserves[i]=0;decisions[i]=0;commits[i]=0;publications[i]=0;drains[i]=0;commands[i]=0;published[i]=0;
end
always @(posedge serviceClock) if(!reset) begin
  if(checkBorrowed && commandAccepted[0] && (commandOffset_0 !== 24 || commandData_0 !== 1))
    $fatal(1,"PUBLICATION_TELEMETRY_BORROW_CHANGED");
  if(checkBorrowed && commandAccepted[1] && (commandOffset_1 !== 56 || commandData_1 !== 1))
    $fatal(1,"PUBLICATION_HOUSEKEEPING_BORROW_CHANGED");
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
for((owner,address) <- Seq(0 -> "32'h30000018",1 -> "32'h30000038")) {
  val label=if(owner==0) "telemetry" else "housekeeping"
  val bit=1<<owner
  val other=1-owner
  val visible=if(owner==0) "gpioOut" else "visibleMask"
  val resetValue=if(owner==0) 0 else 15
  test(s"$name publication sources: $label validation waits for its grant and decision ingress") {
    ClockedSimulation.run(fixture,name+s"-publication-$label-atomic",s"""
      #10000; settled;
      @(negedge serviceClock); holdGrant=$bit;
      offer($address,1); wait(grantWaiting[$owner]); #3000;
      if(grantWaiting !== $bit || accepted || answers || commits[0] || commits[1] ||
          decisions[0] || decisions[1] || !validatedReply)
        $$fatal(1,"PUBLICATION_PARTIAL_GRANT_COMMIT");
      @(negedge serviceClock); holdDecision=$bit; holdGrant=0; #3000;
      if(accepted || answers || commits[0] || commits[1] || decisions[0] || decisions[1] || !validatedReply)
        $$fatal(1,"PUBLICATION_PARTIAL_DECISION_COMMIT");
      // An unrelated owner must not become a second reservation dependency.
      @(negedge serviceClock); holdDecision=${3^bit}; accepted_offer; answer; settled;
      if(accepted != 1 || answers != 1 || reserves[$owner] != 1 || decisions[$owner] != 1 || commits[$owner] != 1 ||
          commands[$owner] != 1 || publications[$owner] != 1 || published[$owner] != 1 || drains[$owner] != 1 ||
          reserves[$other] || decisions[$other] || commits[$other] || commands[$other] ||
          publications[$other] || published[$other] || drains[$other] || $visible !== 1)
        $$fatal(1,"PUBLICATION_ATOMIC_COUNTS");
      @(negedge serviceClock); holdDecision=0;
    """,tasks)
  }
  test(s"$name publication sources: $label uncommitted grant cancels across repeated raw resets") {
    ClockedSimulation.run(fixture,name+s"-publication-$label-cancel",s"""
      #10000; settled; @(negedge serviceClock); holdGrant=$bit;
      offer($address,1); wait(grantWaiting[$owner]); #2;
      raw_reset; #1000; raw_reset;
      @(negedge serviceClock); holdGrant=0; settled;
      if(accepted || answers || response_valid || commits[0] || commits[1] ||
          commands[0] || commands[1] || publications[0] || publications[1] ||
          published[0] || published[1] || drains[0] || drains[1] ||
          decisions[$owner] != 1 || decisions[$other] || $visible !== $resetValue)
        $$fatal(1,"PUBLICATION_CANCELLED_GRANT_EFFECT");
      write_bus($address,1); settled;
      if(accepted != 1 || answers != 1 || decisions[$owner] != 2 || commits[$owner] != 1 ||
          commands[$owner] != 1 || publications[$owner] != 1 || published[$owner] != 1 || drains[$owner] != 1 ||
          commands[$other] || publications[$other] || published[$other] || drains[$other] || $visible !== 1)
        $$fatal(1,"PUBLICATION_CANCELLED_GRANT_REUSE");
    """,tasks)
  }
  test(s"$name publication sources: $label accepted payload survives reset but cannot restore its old CPU view") {
    ClockedSimulation.run(fixture,name+s"-publication-$label-staged-reset",s"""
      #10000; settled; @(negedge serviceClock); holdCommand=$bit;
      offer($address,1); accepted_offer; #1000;
      if(commits[$owner] != 1 || commits[$other] || commands[0] || commands[1] || response_valid)
        $$fatal(1,"PUBLICATION_STAGED_COMMIT");
      // Mutate the unaccepted bus after the real acceptance. The eventual
      // native command must use the retained original payload, even after reset.
      @(negedge serviceClock); checkBorrowed=1;
      request_bits_address=32'h30000008;request_bits_data=32'hdeadbeef;
      raw_reset; #1000; @(negedge serviceClock); holdCommand=0; settled; #10000;
      if(accepted != 1 || answers || response_valid || commands[$owner] != 1 || publications[$owner] != 1 ||
          published[$owner] != 1 || drains[$owner] != 1 || commands[$other] || publications[$other] ||
          published[$other] || drains[$other] || $visible !== $resetValue)
        $$fatal(1,"PUBLICATION_STAGED_RESET_EFFECTS");
      write_bus($address,1); settled;
      if(accepted != 2 || answers != 1 || commands[$owner] != 2 || publications[$owner] != 2 ||
          published[$owner] != 2 || drains[$owner] != 2 || $visible !== 1)
        $$fatal(1,"PUBLICATION_STAGED_RESET_REUSE");
    """,tasks)
  }
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
