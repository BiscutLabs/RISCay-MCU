// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.bd.FourPhaseSoc
import riscay.click.ClickSoc
import riscay.profiles._
import java.util.zip.CRC32

class SleepSpec extends AnyFunSuite {
  import Assembly._
  private val config = McuConfiguration(256, 32, 3,
    Vector(MeasurementChannel(0,"battery",MeasurementUnit.Volt,-3)),
    ApplicationProfile(0x54455354L,1,"sleep-test",
      Vector(HostRegister(0,"WAKE"),HostRegister(1,"RETAINED")),Vector.empty))
  private val p = SocParameters(config, watchdogCycles=4000,
    adc=Some(AdcParameters(halfPeriodCycles=2)), lowPower=Some(LowPowerParameters(maximumSleepMs=1000)))
  private def top(click: Boolean, params: SocParameters = p,
      board: SocParameters => BoardProfile = x => new GenericBoard(x)): SocTop =
    if(click) new ClickSoc(params,board) else new FourPhaseSoc(params,board)
  private def upload(program: Seq[Long]): String = {
    val crc = new CRC32
    program.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b)) & 255).toInt)))
    s"""begin_image(${program.size*4},0,32'h${crc.getValue.toHexString},32'h00010000);
      ${program.zipWithIndex.map { case(w,n) => s"put_word(${n*4},32'h${w.toHexString});" }.mkString("\n")}
      command(3); command(6);"""
  }
  private val monitor = """
reg [11:0] adcCode=2200;
reg [15:0] adcShift;
integer asleepCycles=0, awakeCycles=0, conversions=0, beforeUpdates=0;
real previousStart=0, measuredPeriod=0;
always @(posedge serviceClock) if(!systemReset) begin
  if(sleeping) asleepCycles=asleepCycles+1; else awakeCycles=awakeCycles+1;
end
always @(sleeping) if(!systemReset && serviceClock !== 0) $fatal(1,"CLOCK_GATE_CHANGED_HIGH");
always @(negedge adcCsN) begin
  adcShift={4'b0,adcCode}; adcMiso=adcShift[15]; conversions=conversions+1;
  measuredPeriod=$realtime-previousStart; previousStart=$realtime;
  if(sleeping) $fatal(1,"ADC_STARTED_WITH_GATE_CLOSED");
end
always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1; adcMiso=adcShift[15]; end
always @(posedge sleeping) if(!adcCsN) $fatal(1,"SLEEP_INTERRUPTED_ADC");
task set_period(input [31:0] ms); begin
  start_bus(); write_byte(8'h6a); write_byte(7); write_word(ms); stop_bus();
end endtask
"""
  for(click <- Seq(false,true)) {
    val name = if(click) "click" else "four-phase"
    test(s"$name retained sleep: masked tick, deadline, memory/lock retention and live host/ADC") {
      val program = Seq(0x200000b7L,0x30000137L,
        i(0x13,3,0,0,0x123),store(1,3,0,2),
        i(0x13,3,0,0,2),store(2,3,56,2), // only deadline wakes CPU
        i(0x13,3,0,0,-1),store(2,3,12,2),
        i(0x13,3,0,0,500),store(2,3,60,2),
        i(0x03,4,2,2,4),i(0x13,4,0,4,200),store(2,4,8,2),
        i(0x03,5,2,2,16),store(2,5,52,2),
        i(0x13,3,0,0,1),store(2,3,48,2),i(0x03,6,2,1,0),store(2,6,52,2),breakpoint)
      ClockedSimulation.run(top(click,p.copy(watchdogCycles=10000)),name+"-sleep",s"""
        #300000;
        if(sleepEntries < 5 || asleepCycles < awakeCycles || conversions < 3) $$fatal(1,"BOOT_NOT_SLEEPING");
        ${upload(program)}
        wait(sleeping); #100000;
        if(mode !== 3 || !locked || !programmed) $$fatal(1,"TICK_WOKE_CPU_OR_LOST_FLAGS");
        read_words(2,0,0);
        if(!snapshot[32] || snapshot[0+:32] !== 13592) $$fatal(1,"SLEEP_TELEMETRY");
        #2000000;
        if(mode !== 4 || !locked || !programmed || resetReason) $$fatal(1,"DEADLINE_OR_RETENTION");
        read_words(128,0,0);
        if(!snapshot[1] || snapshot[32+:32] !== 32'h123) $$fatal(1,"WRONG_WAKE_OR_RAM_LOST %h",snapshot);
        set_period(20); expect_error(0); #500000;
        if(measuredPeriod < 199000 || measuredPeriod > 201000) $$fatal(1,"PERIOD_DRIFT %f",measuredPeriod);
        read_words(3,0,0);
        if(supported !== 255 || snapshot[0+:32] !== 7 || snapshot[64+:32] !== 20) $$fatal(1,"TIMING_DISCOVERY");
        set_period(0); expect_error(4); set_period(100); expect_error(4);
        set_period(98); #20000;
        beforeUpdates=conversions;
        repeat(8) begin set_period(98); #20000; end
        if(conversions < beforeUpdates+8) $$fatal(1,"INTERVAL_WRITES_STARVED_SENSING");
        // Reset the halted image, then repeat while a programmed CPU is asleep.
        reset=1; #2000;
        if(locked || programmed || sleeping) $$fatal(1,"SLEEP_RESET_STATE");
        reset=0; #100000; wait(sleeping);
        ${upload(program)}
        wait(sleeping);
        if(!locked || !programmed) $$fatal(1,"SLEEP_RESET_PRECONDITION");
        reset=1; #2000;
        if(locked || programmed || sleeping) $$fatal(1,"CLOSED_GATE_RESET_STATE");
        reset=0; #100000; wait(sleeping);
      """,monitor,referenceHalfPeriodNs=1250,onChipOscillator=true)
    }
    test(s"$name retained sleep: host wake, finite lease and stopped service clock watchdog") {
      val program = Seq(0x300000b7L,
        store(1,0,56,2),i(0x13,2,0,0,-1),store(1,2,12,2),
        i(0x13,2,0,0,500),store(1,2,60,2),i(0x03,3,2,1,16),store(1,3,52,2),breakpoint)
      ClockedSimulation.run(top(click),name+"-sleep-wake",s"""
        ${upload(program)}
        wait(sleeping); command(8); #100000;
        if(mode !== 4 || resetReason) $$fatal(1,"HOST_WAKE_LOST");
        read_words(128,0,0); if(!snapshot[5]) $$fatal(1,"HOST_WAKE_CAUSE");
        reset=1; #2000; reset=0; #5000;
        ${upload(program)}
        #6000000;
        if(mode !== 4 || resetReason) $$fatal(1,"LEASE_DID_NOT_WAKE");
        read_words(128,0,0); if(!snapshot[4]) $$fatal(1,"LEASE_WAKE_CAUSE");
        wait(resetReason); // A halted app cannot keep petting the watchdog.
        reset=1; #2000; reset=0; #5000;
        wait(sleeping); clockEnabled=0;
        wait(resetReason); #5000;
        if(!systemReset || programmed || locked) $$fatal(1,"SLEEP_MASKED_CLOCK_FAILURE");
        clockEnabled=1; #30000;
        if(systemReset) $$fatal(1,"WATCHDOG_RECOVERY");
      """,monitor,referenceHalfPeriodNs=1250)
    }
    test(s"$name Groundlark keeps supervising while unprogrammed service logic sleeps") {
      // Storage capacity is irrelevant to this permanent-controller test; the
      // production-capacity exports are checked separately.
      val params = p.copy(config=Groundlark.configuration.copy(programBytes=16,workingRamBytes=16), watchdogCycles=20000)
      ClockedSimulation.run(top(click,params,x => new GroundlarkBoard(x,PowerPolicy(enabled=true))),
        name+"-sleep-groundlark","""
        // 1 nominal ms = 2 us here; conversion latency is still real service cycles.
        #61000000;
        if(!gpioOut[0] || programmed || sleepEntries < 100) $fatal(1,"SLEEP_CIRCULAR_BOOT");
        adcCode=1500; wait(gpioOut[1]);
        if(!gpioOut[0]) $fatal(1,"SLEEP_EARLY_POWER_CUT");
        gpioIn=0; #60000;
        if(gpioOut[0] || gpioOut[1]) $fatal(1,"SLEEP_MISSED_ACK");
        reset=1; #2000;
        if(gpioOut[0] || sleeping) $fatal(1,"SLEEP_RESET_POWER");
      """,monitor,referenceHalfPeriodNs=250)
    }
  }
  test("low-power parameters reject impossible cadence and unsafe leases") {
    intercept[IllegalArgumentException](LowPowerParameters(referenceHz=0))
    intercept[IllegalArgumentException](LowPowerParameters(referenceHz=7.7,minimumHz=8))
    intercept[IllegalArgumentException](LowPowerParameters(maximumSleepMs=0))
    intercept[IllegalArgumentException](p.copy(staleMs=10))
    intercept[IllegalArgumentException](p.copy(adc=Some(AdcParameters(intervalCycles=1000))))
  }
  test("sleep entry/GPIO race, response stalls, and elapsed time after a short service interruption") {
    val params = p.copy(adc=None,watchdogCycles=10000)
    val tasks = """
task transaction(input [1:0] op, input [31:0] addr, input [31:0] data);
begin
  @(negedge serviceClock); request_bits_operation=op; request_bits_address=addr;
  request_bits_data=data; request_bits_mask=15; request_valid=1; response_ready=0;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0; wait(response_valid);
  if(response_bits_error) $fatal(1,"SLEEP_BUS_ERROR");
  @(negedge serviceClock); response_ready=1; @(posedge serviceClock); #1; response_ready=0;
end endtask
integer commits=0;
always @(posedge serviceClock) if(!systemReset && commit_valid) commits=commits+1;
reg [31:0] savedResponse, beforeTime;
integer beforeCommits;
"""
    ClockedSimulation.run(new FabricFixture(params),"sleep-races","""
      transaction(2,32'h30000038,4); // GPIO wake only; millisecond ticks masked.
      transaction(2,32'h3000003c,1000);
      transaction(2,32'h3000000c,32'hffffffff);
      @(negedge serviceClock);
      request_bits_operation=1; request_bits_address=32'h30000010; request_bits_mask=15; request_valid=1;
      beforeCommits=commits;
      wait(sleeping);
      // Event at the closed gate, then leave the reply stalled across many ticks.
      gpioIn=5;
      @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
      #1; request_valid=0; wait(response_valid); savedResponse=response_bits_data;
      if(!savedResponse[2]) $fatal(1,"SLEEP_GPIO_LOST");
      #100000;
      if(!response_valid || response_bits_data !== savedResponse || sleeping || commits !== beforeCommits+1)
        $fatal(1,"SLEEP_RESPONSE_REPLAY_OR_STALL");
      @(negedge serviceClock); response_ready=1; @(posedge serviceClock); #1; response_ready=0;
      transaction(2,32'h30000028,123); transaction(2,32'h3000002c,1);
      // Use immediate MMIO observations so I2C transfer time cannot disguise
      // a stopped timebase; 1 nominal ms is exactly 10 us in this fixture.
      transaction(1,32'h30000004,0); beforeTime=response_bits_data;
      clockEnabled=0; #1200000; clockEnabled=1; #5000;
      transaction(1,32'h30000004,0);
      if(response_bits_data < beforeTime+120 || response_bits_data > beforeTime+122 || resetReason)
        $fatal(1,"SLEEP_LOST_WALL_TIME");
      read_words(2,0,0);
      if(!snapshot[33] || snapshot[32] || snapshot[64+:32] < 120) $fatal(1,"PAUSE_HID_STALE_SAMPLE");
      // A pending event prevents entry even when clear/request happen close together.
      transaction(2,32'h3000003c,1000);
      transaction(2,32'h3000000c,32'hffffffff);
      gpioIn=4; #1000;
      transaction(1,32'h30000010,0);
      if(!response_bits_data[2]) $fatal(1,"PENDING_EVENT_LOST_AT_ENTRY");
    """,tasks,referenceHalfPeriodNs=1250)
  }
}
