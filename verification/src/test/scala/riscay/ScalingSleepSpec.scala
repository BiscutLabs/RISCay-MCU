// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdScalingSleepFixture(p: SocParameters) extends FabricFixture(p) {
  val scalingBusy = IO(Output(Bool())); scalingBusy := fabric.io.elapsedScaling.busy
  val sleepEligible = IO(Output(Bool())); sleepEligible := fabric.io.canSleep
  val consumedGray = IO(Output(UInt(32.W))); consumedGray := fabric.io.consumedGray
  val scalingTarget = IO(Output(UInt(32.W))); scalingTarget := fabric.io.elapsedScaling.target
}
class ClickScalingSleepFixture(p: SocParameters) extends ClickFabricFixture(p) {
  val scalingBusy = IO(Output(Bool())); scalingBusy := fabric.io.elapsedScaling.busy
  val sleepEligible = IO(Output(Bool())); sleepEligible := fabric.io.canSleep
  val consumedGray = IO(Output(UInt(32.W))); consumedGray := fabric.io.consumedGray
  val scalingTarget = IO(Output(UInt(32.W))); scalingTarget := fabric.io.elapsedScaling.target
}
class ScalingGateFixture(click: Boolean, p: SocParameters) extends FabricFixture(p.copy(lowPower=None)) {
  val gateCanSleep = IO(Input(Bool())); val gateActivity = IO(Input(Bool()))
  val gateDrainDemand = IO(Input(Bool())); val gateForceRun = IO(Input(Bool()))
  val gateRunning = IO(Output(Bool())); val gateClock = IO(Output(Clock()))
  if(click) {
    val g=withClockAndReset(serviceClock,reset) { Module(new riscay.click.RetainedClock) }
    g.io.gray := 0.U; g.io.consumedGray := 0.U; g.io.canSleep := gateCanSleep
    g.io.activity := gateActivity; g.io.drainDemand := gateDrainDemand; g.io.forceRun := gateForceRun
    gateRunning := g.io.running; gateClock := g.io.clockOut
  } else {
    val g=withClockAndReset(serviceClock,reset) { Module(new riscay.bd.RetainedClock) }
    g.io.gray := 0.U; g.io.consumedGray := 0.U; g.io.canSleep := gateCanSleep
    g.io.activity := gateActivity; g.io.drainDemand := gateDrainDemand; g.io.forceRun := gateForceRun
    gateRunning := g.io.running; gateClock := g.io.clockOut
  }
}
class ScalingSleepSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(8,8,0,Vector.empty,
    ApplicationProfile(1,1,"scaling-sleep",Vector.empty,Vector.empty)),
    lowPower=Some(LowPowerParameters()),watchdogCycles=100000)
  for(click <- Seq(false,true)) test(s"${if(click) "click" else "bd"}: pending scaling blocks sleep until publication and return drainage") {
    ClockedSimulation.run(if(click) new ClickScalingSleepFixture(p) else new BdScalingSleepFixture(p),
      "scaling-sleep",s"""
        request_valid=1; request_bits_operation=1; request_bits_address=32'h30000000;
        request_bits_mask=15; response_ready=1;
        // A high Click level can be an idle completed phase. Select an actual
        // new offer and repeat so both phase directions must retain the work.
        phaseSeen=0;
        repeat(2) begin
          wait(sleeping); referenceEnabled=1;
          wait(${if(click) "dut.ca_child_elapsed_scaler.ca_child_native.command_req != dut.ca_child_elapsed_scaler.ca_child_native.command_ack" else "dut.ca_child_elapsed_scaler.ca_child_native.command_req && !dut.ca_child_elapsed_scaler.ca_child_native.command_ack"});
          phaseSeen=phaseSeen | (2'b01 << dut.ca_child_elapsed_scaler.ca_child_native.command_req);
          referenceEnabled=0;
          @(negedge serviceClock); clockEnabled=0; oldConsumed=consumedGray;
          if(!scalingBusy) $$fatal(1,"SCALING_STOP_WITHOUT_PENDING_WORK");
          #5000;
          if(!(${if(click) "dut.ca_child_elapsed_scaler.ca_child_native.reply_req != dut.ca_child_elapsed_scaler.ca_child_native.reply_ack" else "dut.ca_child_elapsed_scaler.ca_child_native.reply_req && !dut.ca_child_elapsed_scaler.ca_child_native.reply_ack"}) ||
            consumedGray !== oldConsumed || !scalingBusy || sleepEligible || sleeping)
            $$fatal(1,"PENDING_SCALING_SLEEP_OR_EARLY_CONSUMPTION");
          clockEnabled=1;
          wait(consumedGray != oldConsumed); wait(!scalingBusy); wait(sleeping);
          if(!sleepEligible) $$fatal(1,"SCALING_DRAIN_NEVER_ALLOWED_SLEEP");
        end
        if(phaseSeen !== ${if(click) "2'b11" else "2'b10"})
          $$fatal(1,"SCALING_OFFER_PHASE_COVERAGE phases=%b",phaseSeen);
      ""","""
reg [31:0] oldConsumed;
reg [1:0] phaseSeen;
always @(posedge serviceClock) if(!reset && scalingBusy && sleepEligible)
  $fatal(1,"SCALING_BUSY_SLEEP_ELIGIBLE");
""",referenceHalfPeriodNs=1000)
  }
  for(click <- Seq(false,true)) test(s"${if(click) "click" else "bd"}: accelerated time maintenance still leaves retained-sleep windows") {
    // Optional diagnostic sensitivity run. The oracle and the tick rate remain
    // unchanged; a failing physical-delay experiment must remain a failed test.
    val stress = sys.env.get("RISCAY_ELAPSED_STRESS_NS").map(_.toLong)
    require(stress.forall(_ > 0), "INVALID_ELAPSED_STRESS_DELAY")
    val overrides = stress.map(ns =>
      ("ca_child_elapsed_scaler.ca_child_native.ca_child_step", "request_delay") -> (ns * 1000000L)).toMap
    info(s"elapsed request guard diagnostic: ${stress.fold("production model")(ns => s"$ns ns")}")
    ClockedSimulation.run(if(click) new ClickScalingSleepFixture(p) else new BdScalingSleepFixture(p),
      "scaling-maintenance","""
        request_valid=1; request_bits_operation=1; request_bits_address=32'h30000000;
        request_bits_mask=15; response_ready=1;
        #100000;
        if(sleepEntries < 10) $fatal(1,"MAINTENANCE_STARVED_SLEEP entries=%d",sleepEntries);
      """,referenceHalfPeriodNs=250, primitiveDelayOverrides=overrides)
  }
  for(click <- Seq(false,true)) test(s"${if(click) "click" else "bd"}: ordinary activity and reset retain the full guard after maintenance") {
    ClockedSimulation.run(new ScalingGateFixture(click,p),"maintenance-guard","""
      gateCanSleep=0; gateActivity=1; gateDrainDemand=0;
      repeat(30) @(negedge serviceClock);
      if(!gateRunning) $fatal(1,"MAINTENANCE_IGNORED");
      // Ordinary work arrives on the final maintenance edge.
      gateCanSleep=1; gateDrainDemand=1;
      repeat(4) @(negedge serviceClock);
      gateActivity=0; gateDrainDemand=0;
      repeat(7) begin @(posedge serviceClock); #1;
        if(!gateRunning) $fatal(1,"ORDINARY_GUARD_SHORTENED");
      end
      wait(!gateRunning);
      // A watchdog demand with grace already zero still wakes and reloads it.
      @(negedge serviceClock); gateForceRun=1;
      repeat(4) @(negedge serviceClock);
      if(!gateRunning) $fatal(1,"RESET_DID_NOT_WAKE");
      gateForceRun=0;
      repeat(7) begin @(posedge serviceClock); #1;
        if(!gateRunning) $fatal(1,"RESET_GUARD_SHORTENED");
      end
      wait(!gateRunning);
    ""","""
always @(gateRunning) if(!reset && serviceClock !== 0) $fatal(1,"GATE_CHANGED_HIGH");
""")
  }
}
