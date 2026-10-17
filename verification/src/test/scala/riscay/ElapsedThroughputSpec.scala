// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Guard-only sensitivity at the measured adapter envelope. Other native cells
  * retain their digital models: these are throughput tests, not SS signoff.
  */
class ElapsedThroughputSpec extends AnyFunSuite {
  // Ceil(644.726257 ns), SS/125 C/3 V, 2 ns input slew, 0.05 pF load.
  private val requestFs = 645000000L
  private val p = SocParameters(McuConfiguration(8,8,0,Vector.empty,
    ApplicationProfile(1,1,"elapsed-throughput",Vector.empty,Vector.empty)),
    lowPower=Some(LowPowerParameters.gf180Slow),watchdogCycles=100000)

  for(click <- Seq(false,true); half <- Seq(62.5,25.0)) {
    val protocol = if(click) "click" else "bd"
    test(s"$protocol: 645 ns request guard drains full-width batches at service half-period $half ns") {
      ClockedSimulation.run(new ScalingFixture(click),s"elapsed-batch-$protocol",s"""
        advance(1); advance(17); advance(32'hffffffff); advance(32'h80000000); advance(1);
        // Ticks arriving after admission coalesce into one subsequent batch.
        wait(!tickBusy); @(negedge serviceClock); oldOffer=tickOffer;
        startBound(); target=target+100;
        wait(tickOffer != oldOffer); target=target+11;
        check_elapsed(100,0); check_elapsed(11,0); wait(!tickBusy); endBound(64000);
        // Stop the receipt clock: the native owner finishes and holds the old
        // reply. It cannot publish consumed or award stale single-tick credit.
        @(negedge serviceClock); oldOffer=tickOffer; oldReply=nativeTickReply;
        oldConsumed=consumed; target=target+1;
        wait(tickOffer != oldOffer); @(negedge serviceClock); clockEnabled=0;
        target=target+4; #32000;
        if(nativeTickReply == oldReply || consumed !== oldConsumed || valid || !tickBusy)
          $$fatal(1,"SLOW_GUARD_CLOCKLESS_OR_RETAINED_REPLY");
        startBound(); clockEnabled=1;
        check_elapsed(1,0); check_elapsed(4,0); wait(!tickBusy); endBound(64000);
        if(consumed !== target || publications != 9)
          $$fatal(1,"SLOW_GUARD_LOST_OR_DUPLICATE_BATCH count=%d",publications);
      """, """
wire tickOffer = dut.ticks_ca_child_tested_ticks.ca_child_native.command_req;
wire nativeTickReply = dut.ticks_ca_child_tested_ticks.ca_child_native.reply_req;
reg oldOffer,oldReply; reg [31:0] oldConsumed;
integer lane, publications=0;
always @(posedge serviceClock) if(!reset && valid) publications=publications+1;
reg [63:0] remainder[0:2]; reg [63:0] total;
realtime started, elapsedNs; reg bounded=0;
initial begin remainder[0]=0; remainder[1]=0; remainder[2]=0; end
always #100 if(bounded && $realtime-started > 64000)
  $fatal(1,"ELAPSED_BATCH_DEADLINE");
task startBound; begin started=$realtime; bounded=1; end endtask
task endBound(input integer budgetNs); begin
  elapsedNs=$realtime-started; bounded=0;
  if(elapsedNs > budgetNs) $fatal(1,"ELAPSED_BATCH_BUDGET ns=%f budget=%d",elapsedNs,budgetNs);
  $display("ELAPSED_BATCH_NS:%0.3f:BUDGET:%0d",elapsedNs,budgetNs);
end endtask
task check_elapsed(input [31:0] delta,input expectSingle);
reg [31:0] wanted[0:2]; begin
  wait(valid); #1;
  for(lane=0;lane<3;lane=lane+1) begin
    total={32'b0,delta}*(lane==0 ? 129354 : lane==1 ? 83333 : 200000)+remainder[lane];
    wanted[lane]=total/1000; remainder[lane]=total%1000;
  end
  if(elapsed_0 !== wanted[0] || elapsed_1 !== wanted[1] || elapsed_2 !== wanted[2] || single !== expectSingle)
    $fatal(1,"SLOW_GUARD_ELAPSED_ORACLE delta=%h",delta);
  @(posedge serviceClock); #1;
  if(valid) $fatal(1,"SLOW_GUARD_DUPLICATE_PUBLICATION");
end endtask
task advance(input [31:0] delta); begin
  wait(!tickBusy); @(negedge serviceClock); startBound(); target=target+delta;
  check_elapsed(delta,delta==1); wait(!tickBusy); endBound(32000);
  if(consumed !== target) $fatal(1,"SLOW_GUARD_CONSUMED_TARGET");
end endtask
""",serviceHalfPeriodNs=half,deadlineNs=1000000,
        primitiveDelayOverrides=Map(("ca_child_native.ca_child_step","request_delay") -> requestFs))
    }
    test(s"$protocol: 645 ns request guard drains maintenance to retained sleep at service half-period $half ns") {
      ClockedSimulation.run(if(click) new ClickScalingSleepFixture(p) else new BdScalingSleepFixture(p),
        s"elapsed-maintenance-$protocol","""
        referenceEnabled=0;
        request_valid=1; request_bits_operation=1; request_bits_address=32'h30000000;
        request_bits_mask=15; response_ready=1;
        wait(!scalingBusy); wait(sleeping);
        repeat(4) begin
          oldTarget=scalingTarget; oldConsumed=consumedGray;
          // One source tick per trial. Start at LF restart, before coherent
          // target admission, and finish after final architectural publication.
          started=$realtime; bounded=1; referenceEnabled=1;
          wait(scalingTarget != oldTarget); #1; referenceEnabled=0; expectedTarget=scalingTarget;
          if(expectedTarget !== oldTarget+1)
            $fatal(1,"MAINTENANCE_TICK_NOT_ISOLATED old=%h target=%h",oldTarget,expectedTarget);
          wait(consumedGray == (expectedTarget ^ (expectedTarget >> 1)));
          wait(!scalingBusy); wait(sleepEligible); wait(sleeping);
          elapsedNs=$realtime-started; bounded=0;
          if(consumedGray === oldConsumed || elapsedNs > 64000)
            $fatal(1,"MAINTENANCE_DRAIN_BUDGET ns=%f",elapsedNs);
          expectedTime=({32'b0,expectedTarget}*64'd129354)/1000;
          if(timeNow !== expectedTime[31:0])
            $fatal(1,"MAINTENANCE_TIME_EFFECT target=%h now=%h expected=%h",expectedTarget,timeNow,expectedTime);
          $display("ELAPSED_MAINTENANCE_NS:%0.3f:BUDGET:64000",elapsedNs);
        end
      ""","""
reg [31:0] oldTarget, oldConsumed, expectedTarget;
reg [63:0] expectedTime;
realtime started, elapsedNs; reg bounded=0;
always #100 if(bounded && $realtime-started > 64000) $fatal(1,"MAINTENANCE_DRAIN_DEADLINE");
always @(posedge serviceClock) if(!reset && scalingBusy && sleepEligible)
  $fatal(1,"SLOW_GUARD_SLEEP_WITH_PENDING_SCALING");
// Sleeping may still be high while a newly observed tick opens the synchronized
// gate. Only a new entry, not wake propagation, may require all work drained.
always @(posedge sleeping) if(!reset && scalingBusy)
  $fatal(1,"SLOW_GUARD_ENTERED_SLEEP_WITH_PENDING_SCALING");
""",referenceHalfPeriodNs=1000,serviceHalfPeriodNs=half,deadlineNs=1000000,
        primitiveDelayOverrides=Map(("ca_child_elapsed_scaler.ca_child_native.ca_child_step","request_delay") -> requestFs))
    }
  }
}
