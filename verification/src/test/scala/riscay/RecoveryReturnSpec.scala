// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Independent final-client stalls and counts, below the raw reset qualifier. */
class RecoveryReturnSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"recovery-return",Vector.empty,Vector.empty)),watchdogCycles=10000000)
  private val tasks="""
integer accepted=0,answers=0,i,n;
integer commands[0:1],publications[0:1],baseCommands[0:1],basePublications[0:1];
integer minimumFresh=1;
initial for(i=0;i<2;i=i+1) begin commands[i]=0;publications[i]=0;end
always @(posedge serviceClock) if(!reset) begin
  if(request_valid && request_ready) begin
    accepted=accepted+1;
    for(i=0;i<2;i=i+1) if(commands[i]<baseCommands[i]+minimumFresh ||
        publications[i]<basePublications[i]+minimumFresh)
      $fatal(1,"FINAL_CLIENT_CPU_BEFORE_FRESH_PROOF");
  end
  if(response_valid && response_ready) answers=answers+1;
  if(recoveryCommand !== recoveryCommit) $fatal(1,"FINAL_CLIENT_COMMAND_ATOMICITY");
  for(i=0;i<2;i=i+1) begin
    if(recoveryCommand[i]) commands[i]=commands[i]+1;
    if(recoveryPublication[i]) publications[i]=publications[i]+1;
  end
end
task checkpoint; begin
  #100000;
  if(nativeDebt || returnFence || sourceBusy || qualifiedReset) $fatal(1,"FINAL_CLIENT_INITIAL_SETTLEMENT");
  for(n=0;n<2;n=n+1) begin baseCommands[n]=commands[n];basePublications[n]=publications[n];end
end endtask
task raw_reset; begin
  @(negedge serviceClock); #7; applicationReset=1;
  #1; if(sourceDebt !== 3 || !qualifiedReset) $fatal(1,"FINAL_CLIENT_RAW_RESET");
  #6; applicationReset=0;
end endtask
task offer_cpu; begin
  @(negedge serviceClock); request_valid=1; request_bits_operation=2;
  request_bits_address=32'h30000038;request_bits_data=1;request_bits_mask=15;
end endtask
task stalled; begin
  if(nativeDebt !== 3 || returnFence !== 3 || sourceBusy !== 3 || request_ready || accepted || response_valid)
    $fatal(1,"FINAL_CLIENT_RELEASED_EARLY debt=%b fence=%b busy=%b",nativeDebt,returnFence,sourceBusy);
end endtask
task complete_cpu; begin
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
  wait(response_valid);
  if(response_bits_error || response_bits_data !== 0) $fatal(1,"FINAL_CLIENT_RESPONSE");
  @(negedge serviceClock);response_ready=1;
  @(posedge serviceClock);#1;response_ready=0;
  #100000;
  if(accepted != 1 || answers != 1 || visibleMask !== 1 || nativeDebt || returnFence || sourceBusy)
    $fatal(1,"FINAL_CLIENT_COMPLETION_COUNTS");
end endtask
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(): SocTop=if(click) new ClickRecoveryOwnershipFixture(p) else new BdRecoveryOwnershipFixture(p)
    for(first <- Seq(0,1)) {
      test(s"$name final recovery receipt: independent clocked client stall, release order $first") {
        ClockedSimulation.run(fixture(),name+s"-final-client-$first",s"""
          #10000;checkpoint;
          @(negedge serviceClock);holdFinal=3;
          raw_reset;#20000;
          if(finalPending !== 3 || nativeDebt !== 3 || sourceBusy !== 3)
            $$fatal(1,"FINAL_CLIENT_OFFER_BOUND");
          for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n]+1 || publications[n] != basePublications[n]+1)
            $$fatal(1,"FINAL_CLIENT_PROOF_COUNTS");
          offer_cpu;#20000;stalled;
          @(negedge serviceClock);holdFinal=${3 ^ (1<<first)};#20000;
          if(nativeDebt !== ${3 ^ (1<<first)} || returnFence !== ${3 ^ (1<<first)} ||
              request_ready || accepted || response_valid)
            $$fatal(1,"FINAL_CLIENT_INDEPENDENT_RETURN");
          @(negedge serviceClock);holdFinal=0;complete_cpu;
        """,tasks,deadlineNs=2000000)
      }
    }
    test(s"$name final recovery receipt: repeated reset invalidates held old proof before CPU reuse") {
      ClockedSimulation.run(fixture(),name+"-final-client-reset","""
        #10000;checkpoint;
        @(negedge serviceClock);holdFinal=3;
        raw_reset;#20000;
        if(finalPending !== 3) $fatal(1,"FINAL_CLIENT_OLD_PROOF_BOUND");
        minimumFresh=2;
        raw_reset;#20000;
        offer_cpu;#20000;stalled;
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n]+1 || publications[n] != basePublications[n]+1)
          $fatal(1,"FINAL_CLIENT_OLD_PROOF_IDENTITY");
        @(negedge serviceClock);holdFinal=0;complete_cpu;
        for(n=0;n<2;n=n+1) if(commands[n] != baseCommands[n]+2 || publications[n] != basePublications[n]+2)
          $fatal(1,"FINAL_CLIENT_FRESH_PROOF_COUNTS");
      """,tasks,deadlineNs=2000000)
    }
    if(!click) test("bd final recovery receipt: actual high ACK must return before debt release") {
      ClockedSimulation.run(fixture(),"bd-final-client-ack-return","""
        #10000;checkpoint;
        @(negedge serviceClock);holdFinal=3;
        raw_reset;#20000;
        if(finalRequest !== 3 || finalAcknowledge !== 0) $fatal(1,"FINAL_CLIENT_ACK_SETUP");
        @(negedge serviceClock);holdFinalReturn=3;holdFinal=0;
        #20000;
        if(finalRequest !== 0 || finalAcknowledge !== 3) $fatal(1,"FINAL_CLIENT_ACK_RETURN_BOUND");
        offer_cpu;#20000;stalled;
        @(negedge serviceClock);holdFinalReturn=0;complete_cpu;
      """,tasks,deadlineNs=2000000)
    }
  }
}
