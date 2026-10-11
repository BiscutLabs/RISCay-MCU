// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Independent command/publication counts through raw reset and every client stall. */
class RecoveryOwnershipSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"recovery-ownership",Vector.empty,Vector.empty)),watchdogCycles=10000000)
  private val tasks="""
integer accepted=0,answers=0,maintenance=0,kicks=0,i,n;
integer reserves[0:1],decisions[0:1],commits[0:1],publications[0:1],drains[0:1],commands[0:1],published[0:1],fresh[0:1];
integer baseCommands[0:1],basePublications[0:1],baseDecisions[0:1],baseCommits[0:1],baseFresh[0:1];
integer oldTime,oldBoard,oldMaintenance,oldKicks;
initial for(i=0;i<2;i=i+1) begin
  reserves[i]=0;decisions[i]=0;commits[i]=0;publications[i]=0;drains[i]=0;commands[i]=0;published[i]=0;fresh[i]=0;
end
always @(posedge serviceClock) if(!reset) begin
  if(request_valid && request_ready) accepted=accepted+1;
  if(response_valid && response_ready) answers=answers+1;
  if(maintenanceReply) maintenance=maintenance+1;
  if(maintenanceKick) kicks=kicks+1;
  if(recoveryCommand !== recoveryCommit) $fatal(1,"RECOVERY_COMMAND_COMMIT_NOT_ATOMIC");
  for(i=0;i<2;i=i+1) begin
    if(recoveryReserve[i]) reserves[i]=reserves[i]+1;
    if(recoveryDecision[i]) decisions[i]=decisions[i]+1;
    if(recoveryCommit[i]) commits[i]=commits[i]+1;
    if(recoveryPublication[i]) publications[i]=publications[i]+1;
    if(recoveryDrain[i]) drains[i]=drains[i]+1;
    if(recoveryCommand[i]) commands[i]=commands[i]+1;
    if(recoveryReply[i]) published[i]=published[i]+1;
    if(freshRecoveryReply[i]) fresh[i]=fresh[i]+1;
  end
end
task checkpoint; begin
  for(n=0;n<2;n=n+1) begin
    baseCommands[n]=commands[n];basePublications[n]=publications[n];baseDecisions[n]=decisions[n];
    baseCommits[n]=commits[n];baseFresh[n]=fresh[n];
  end
end endtask
task raw_reset; begin
  @(negedge serviceClock); #7; applicationReset=1; request_valid=0;
  #1; if(sourceDebt !== 3 || !qualifiedReset) $fatal(1,"RECOVERY_RAW_RESET_FORGOTTEN");
  #6; applicationReset=0;
end endtask
task burst_reset; begin
  raw_reset;
  #41; applicationReset=1; #7; applicationReset=0;
  #41; applicationReset=1; #7; applicationReset=0;
  #41; if(!qualifiedReset || nativeDebt !== 3) $fatal(1,"RECOVERY_BURST_QUALIFIER");
end endtask
task settled; begin
  #100000;
  if(nativeDebt !== 0 || returnFence !== 0 || sourceBusy !== 0 || qualifiedReset)
    $fatal(1,"RECOVERY_SETTLEMENT_BOUND debt=%b fence=%b busy=%b",nativeDebt,returnFence,sourceBusy);
end endtask
task write_bus(input [31:0] address,input [31:0] value); begin
  @(negedge serviceClock); request_valid=1; request_bits_operation=2;
  request_bits_address=address; request_bits_data=value; request_bits_mask=15;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
  wait(response_valid); if(response_bits_error || response_bits_data !== 0) $fatal(1,"RECOVERY_BUS_RESPONSE");
  @(negedge serviceClock); response_ready=1;
  @(posedge serviceClock); #1; response_ready=0;
end endtask
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(parameters: SocParameters=p): SocTop=if(click)
      new ClickRecoveryOwnershipFixture(parameters) else new BdRecoveryOwnershipFixture(parameters)
    for(first <- Seq(0,1)) {
      test(s"$name recovery ownership: repeated raw resets reject stale replies, fresh publication preserves events, return order $first") {
        ClockedSimulation.run(fixture(),name+s"-recovery-stale-$first",s"""
          #10000; settled; checkpoint;
          @(negedge serviceClock); holdCommand=3; holdReply=3;
          raw_reset; #2000; @(negedge serviceClock); gpioIn=1; #1000;
          if(!visibleEvents[2]) $$fatal(1,"RECOVERY_OLD_EVENT_NOT_QUEUED");
          @(negedge serviceClock); holdCommand=0; #20000;
          if(recoveryReplyWaiting !== 3 || commands[0] != baseCommands[0]+1 || commands[1] != baseCommands[1]+1)
            $$fatal(1,"RECOVERY_OLD_REPLY_BOUND");
          burst_reset; #2000;
          @(negedge serviceClock); holdGrant=3; holdReply=0; #20000;
          if(recoveryGrantWaiting !== 3 || nativeDebt !== 3 || returnFence !== 3 ||
              projectedEvents !== 0 || visibleMask !== 15 || visibleDeadline !== 0 || response_valid)
            $$fatal(1,"RECOVERY_STALE_PUBLICATION_RESTORED_APPLICATION");
          for(n=0;n<2;n=n+1) if(publications[n] != basePublications[n]+1 ||
              commands[n] != baseCommands[n]+1 || fresh[n] != baseFresh[n])
            $$fatal(1,"RECOVERY_STALE_IDENTITY_COUNTS");
          @(negedge serviceClock); gpioIn=0; holdDecision=3; holdGrant=0; holdPublication=3; holdDrain=3;
          #3000;
          if(commands[0] != baseCommands[0]+1 || commands[1] != baseCommands[1]+1 || nativeDebt !== 3)
            $$fatal(1,"RECOVERY_COMMAND_BEFORE_DECISION");
          @(negedge serviceClock); holdDecision=${3 ^ (1<<first)}; #20000;
          if(commands[$first] != baseCommands[$first]+2 || commands[${1-first}] != baseCommands[${1-first}]+1)
            $$fatal(1,"RECOVERY_DECISION_SELECTION");
          @(negedge serviceClock); holdDecision=0; #20000;
          if(recoveryReplyWaiting !== 3 || nativeDebt !== 3 || projectedEvents !== 0)
            $$fatal(1,"RECOVERY_BEFORE_ACTUAL_PUBLICATION");
          @(negedge serviceClock); request_valid=1; request_bits_operation=2;
          request_bits_address=32'h30000018; request_bits_data=1; request_bits_mask=15;
          holdPublication=0; #20000;
          if(!projectedEvents[2] || nativeDebt !== 3 || returnFence !== 3 || response_valid || request_ready || accepted)
            $$fatal(1,"RECOVERY_FRESH_EVENT_OR_EARLY_CLEAR");
          for(n=0;n<2;n=n+1) if(publications[n] != basePublications[n]+2 || fresh[n] != baseFresh[n]+1)
            $$fatal(1,"RECOVERY_FRESH_PUBLICATION_COUNTS");
          @(negedge serviceClock); holdDrain=${3 ^ (1<<first)}; #20000;
          if(nativeDebt !== ${3 ^ (1<<first)} || returnFence !== ${3 ^ (1<<first)} || request_ready || accepted || response_valid)
            $$fatal(1,"RECOVERY_INDEPENDENT_RETURN");
          @(negedge serviceClock); holdDrain=0;
          @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
          #1; request_valid=0;
          wait(response_valid); if(response_bits_error || response_bits_data !== 0) $$fatal(1,"RECOVERY_BUS_RESPONSE");
          @(negedge serviceClock); response_ready=1;
          @(posedge serviceClock); #1; response_ready=0; settled;
          if(accepted != 1 || answers != 1 || gpioOut !== 1 || !projectedEvents[2])
            $$fatal(1,"RECOVERY_REUSE_OR_POSTRESET_EVENT_LOST");
        """,tasks,deadlineNs=2000000)
      }
    }
    test(s"$name recovery ownership: revoked queued recovery grants cancel before reacquisition") {
      ClockedSimulation.run(fixture(),name+"-recovery-grant-reset","""
        #10000; settled; checkpoint;
        @(negedge serviceClock); holdGrant=3; raw_reset; #20000;
        if(recoveryGrantWaiting !== 3) $fatal(1,"RECOVERY_QUEUED_GRANT_BOUND");
        burst_reset; #2000;
        @(negedge serviceClock); holdDecision=3; holdGrant=0; #3000;
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n] || decisions[n] != baseDecisions[n])
          $fatal(1,"RECOVERY_CANCEL_BEFORE_DECISION_READY");
        @(negedge serviceClock); holdCommand=3; holdDecision=0; #20000;
        if(recoveryGrantWaiting !== 3 || eligible !== 3 || nativeDebt !== 3)
          $fatal(1,"RECOVERY_REACQUIRE_BOUND");
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n] || commits[n] != baseCommits[n] ||
            decisions[n] != baseDecisions[n]+1 || publications[n] != basePublications[n])
          $fatal(1,"RECOVERY_REVOKED_GRANT_ISSUED_COMMAND");
        @(negedge serviceClock); holdCommand=0; settled;
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n]+1 || commits[n] != baseCommits[n]+1 ||
            decisions[n] != baseDecisions[n]+2 || publications[n] != basePublications[n]+1)
          $fatal(1,"RECOVERY_GRANT_REUSE_COUNTS");
        write_bus(32'h30000038,1); settled;
        if(answers != 1 || visibleMask !== 1) $fatal(1,"RECOVERY_GRANT_REUSE_RESPONSE");
      """,tasks,deadlineNs=2000000)
    }
    test(s"$name recovery ownership: a reset after native debt clear revokes the still-returning recovery") {
      ClockedSimulation.run(fixture(),name+"-recovery-return-reset","""
        #10000; settled; checkpoint;
        @(negedge serviceClock); holdReserve=3; holdDrain=3; raw_reset; #20000;
        if(qualifiedReset || nativeDebt !== 3 || sourceBusy !== 0)
          $fatal(1,"RECOVERY_PRE_RESERVE_QUIET_SETUP");
        if(returnFence !== 3) $fatal(1,"RECOVERY_MISSING_FULL_RETURN_FENCE");
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n] || decisions[n] != baseDecisions[n])
          $fatal(1,"RECOVERY_COMMAND_BEFORE_RESERVATION");
        @(negedge serviceClock); holdReserve=0; #20000;
        if(nativeDebt !== 3 || sourceBusy !== 3) $fatal(1,"RECOVERY_RETURN_SETUP");
        @(negedge serviceClock); holdDrain=0;
        wait(nativeDebt==0); #1;
        if(returnFence !== 3) $fatal(1,"RECOVERY_MISSING_FULL_RETURN_FENCE");
        applicationReset=1; holdGrant=3; #7; applicationReset=0; #20000;
        if(nativeDebt !== 3 || returnFence !== 3 || recoveryGrantWaiting !== 3 || response_valid)
          $fatal(1,"RECOVERY_OLD_RETURN_CLEARED_NEW_DEBT");
        @(negedge serviceClock); holdGrant=0; settled;
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n]+2 || publications[n] != basePublications[n]+2)
          $fatal(1,"RECOVERY_RETURN_RESET_COUNTS");
      """,tasks,deadlineNs=2000000)
    }
    test(s"$name recovery ownership: prolonged application reset preserves independent housekeeping and continuous observations") {
      ClockedSimulation.run(fixture(p.copy(serviceHz=1000)),name+"-recovery-maintenance","""
        #10000; settled; checkpoint;
        @(negedge serviceClock); applicationReset=1;
        #2000; oldTime=timeNow;oldBoard=boardTime;oldMaintenance=maintenance;oldKicks=kicks;
        #50000;
        if(!qualifiedReset || nativeDebt !== 3 || returnFence !== 3 || timeNow <= oldTime || boardTime <= oldBoard ||
            maintenance <= oldMaintenance+3 || kicks <= oldKicks+3 || gpioOut !== 0 || projectedEvents !== 0 || visibleMask !== 15)
          $fatal(1,"RECOVERY_PROLONGED_RESET_STOPPED_MAINTENANCE");
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n])
          $fatal(1,"RECOVERY_ADMITTED_WHILE_RESET_ACTIVE");
        @(negedge serviceClock); applicationReset=0; settled;
        write_bus(32'h30000018,1); write_bus(32'h30000038,1); settled;
        if(accepted != 2 || answers != 2 || gpioOut !== 1 || visibleMask !== 1)
          $fatal(1,"RECOVERY_CONTINUOUS_OBSERVATIONS_STARVED_CPU");
      """,tasks,deadlineNs=2000000)
    }
  }
}
