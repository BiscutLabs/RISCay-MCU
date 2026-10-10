// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.bd.FourPhaseSoc
import riscay.click.ClickSoc
import riscay.profiles._
import java.util.zip.CRC32

class DeepSleepSpec extends AnyFunSuite {
  import Assembly._
  private val lp = LowPowerParameters.gf180Slow
  private val config = McuConfiguration(256,32,3,
    Vector(MeasurementChannel(0,"battery",MeasurementUnit.Volt,-3)),
    ApplicationProfile(0x54455354L,1,"deep-sleep",Vector(HostRegister(0,"WAKE"),HostRegister(1,"RETAINED")),Vector.empty))
  private val p = SocParameters(config, staleMs=3000, watchdogCycles=32, watchdogHoldCycles=2,
    adc=Some(AdcParameters(halfPeriodCycles=2,intervalCycles=10000000)),lowPower=Some(lp))
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
reg [11:0] adcCode=2200; reg [15:0] adcShift;
integer fastEdges=0, savedEdges, conversions=0;
real lastRise=0, previousStart=0, period=0;
reg [31:0] previousGray=0, grayDifference;
always @(posedge watchdogClock or negedge dut.porReleased) begin
  #1;
  grayDifference=dut.soc.timebase_gray ^ previousGray;
  if(dut.porReleased && (grayDifference & (grayDifference-1)) !== 0) $fatal(1,"MULTIBIT_SOURCE_GRAY_TRANSITION");
  previousGray=dut.porReleased ? dut.soc.timebase_gray : 0;
end
always @(posedge serviceClock) begin fastEdges=fastEdges+1; lastRise=$realtime; end
always @(negedge serviceClock) if(lastRise>0 && $realtime-lastRise<49.999) $fatal(1,"RUNT_SOURCE_PULSE");
always @(posedge sleeping) if(!adcCsN) $fatal(1,"GATED_ACTIVE_ADC");
always @(negedge adcCsN) begin
  adcShift={4'b0,adcCode}; adcMiso=adcShift[15]; conversions=conversions+1;
  period=$realtime-previousStart; previousStart=$realtime;
end
always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1; adcMiso=adcShift[15]; end
task set_period(input [31:0] ms); begin
  start_bus(); write_byte(8'h6a); write_byte(7); write_word(ms); stop_bus();
end endtask
"""
  for(click <- Seq(false,true)) {
    val name = if(click) "click" else "four-phase"
    test(s"$name on-die brownout resets sleeping, partial-upload and locked states") {
      val params=p.copy(config=config.copy(programBytes=32,workingRamBytes=32),adc=None)
      ClockedSimulation.run(top(click,params),name+"-supply-reset",s"""
        #3000000; wait(!serviceClockEnable);
        dut.supplyMonitor.supply_voltage=2.8; #1;
        if(!systemReset || dut.porReleased || programmed || locked) $$fatal(1,"SLEEP_BROWNOUT");
        #100000; dut.supplyMonitor.supply_voltage=3.15; #100000;
        if(!systemReset || dut.powerGood) $$fatal(1,"BROWNOUT_HYSTERESIS");
        dut.supplyMonitor.supply_voltage=3.3; #3000000;
        read_words(1,0,0); if(programmed || locked) $$fatal(1,"UNPROGRAMMED_RECOVERY");
        begin_image(8,0,0,32'h00010000); put_word(0,32'h00100073);
        dut.supplyMonitor.supply_voltage=0; #10000;
        if(!systemReset) $$fatal(1,"UPLOAD_POWER_LOSS");
        dut.supplyMonitor.supply_voltage=3.3; #3000000;
        read_words(1,0,0); if(snapshot[0+:32] !== 0 || programmed || locked) $$fatal(1,"PARTIAL_IMAGE_SURVIVED");
        ${upload(Seq(breakpoint))}
        await_locked();
        if(!programmed || !locked) $$fatal(1,"LOCK_SETUP");
        dut.supplyMonitor.supply_voltage=2.8; #1;
        if(!systemReset || programmed || locked) $$fatal(1,"LOCK_SURVIVED_BROWNOUT");
        dut.supplyMonitor.supply_voltage=3.3; #3000000;
        read_words(1,0,0); if(programmed || locked || systemReset) $$fatal(1,"LOCKED_RECOVERY");
      """,referenceHalfPeriodNs=1000000,onChipOscillator=true,chipParameters=lp)
    }
    test(s"$name I2C probe tolerates immediate and mid-probe startup at service frequency bounds") {
      val params=p.copy(config=config.copy(programBytes=16,workingRamBytes=16),adc=None)
      for((hz,startup) <- Seq((20000000.0,0),(8000000.0,15000))) {
        ClockedSimulation.run(top(click,params),name+"-probe-corners","""
          #3000000;
          repeat(3) begin
            wait(!serviceClockEnable);
            read_words(0,0,0);
            if(snapshot[0+:32] !== 32'h00010000 || supported !== 255) $fatal(1,"PROBE_CORNER_READ");
            read_words(1,0,0);
            if(snapshot[0+:32] !== 0 || snapshot[160+:32] !== 0 || programmed || locked)
              $fatal(1,"PROBE_CORNER_SIDE_EFFECT");
          end
        """,referenceHalfPeriodNs=1000000,onChipOscillator=true,chipParameters=lp,
          serviceStartupNs=startup,serviceModelHz=hz)
      }
    }
    test(s"$name stuck and abandoned I2C transactions release the fast source and foreign traffic is ignored") {
      val params=p.copy(config=config.copy(programBytes=16,workingRamBytes=32),adc=None)
      ClockedSimulation.run(top(click,params),name+"-host-timeout","""
        #3000000;
        // Abandoned valid write: its opcode must never commit on later recovery.
        start_bus(); write_byte(8'h6a); write_byte(1); write_byte(4);
        scl=0; hostLow=0; assert_off();
        // Simultaneous line release need not form an observable STOP.
        scl=1; hostLow=0; #1000; transactionActive=0;
        read_words(1,0,0);
        if(mode !== 0 || programmed || snapshot[160+:32] !== 0) $fatal(1,"TIMED_OUT_FRAME_COMMITTED");
        // START followed by SDA stuck low cannot act as a level wake.
        start_bus(); scl=1; hostLow=1; assert_off();
        scl=0; hostLow=0; #1000; scl=1; transactionActive=0;
        read_words(0,0,0); if(snapshot[0+:32] !== 32'h00010000) $fatal(1,"HOST_TIMEOUT_RECOVERY");
        // MCU may be driving the first read data bit when its host disappears.
        start_bus(); write_byte(8'h6b); scl=0; assert_off();
        if(sdaLow) $fatal(1,"TIMEOUT_KEPT_SDA_DRIVEN");
        stop_bus();
        // Decode another target, then continue its data clocks. Those edges
        // are not STARTs and must not keep this MCU's oscillator enabled.
        start_bus(); foreign_address();
        #1000000;
        savedEdges=fastEdges;
        repeat(200) begin scl=0; #1000; scl=1; #1000; end
        if(serviceClockEnable || fastEdges != savedEdges) $fatal(1,"FOREIGN_PAYLOAD_HELD_CLOCK");
        stop_bus(); transactionActive=0;
        read_words(1,0,0);
        if(mode !== 0 || programmed) $fatal(1,"FOREIGN_TRAFFIC_CHANGED_LOADER");
      ""","""
integer fastEdges=0,savedEdges;
always @(posedge serviceClock) fastEdges=fastEdges+1;
task assert_off; begin
  // Production timeout at the fixture's 10 MHz plus bounded retry hold.
  #28000000;
  if(serviceClockEnable || serviceClock || !sleeping) $fatal(1,"STUCK_HOST_KEPT_FAST_SOURCE");
  savedEdges=fastEdges; #100000;
  if(fastEdges != savedEdges) $fatal(1,"STUCK_HOST_RETRIGGERED");
end endtask
task foreign_address; integer b; reg [7:0] address; begin
  address=8'h42;
  for(b=7;b>=0;b=b-1) begin
    hostLow=!address[b]; #1000; scl=1; #1000; scl=0; #1000;
  end
  hostLow=0; #1000; scl=1; #1000;
  if(!busSda) $fatal(1,"FOREIGN_ADDRESS_ACKNOWLEDGED");
  scl=0; #1000;
end endtask
""",referenceHalfPeriodNs=50000000,onChipOscillator=true,chipParameters=lp,
        serviceStartupNs=100000,deadlineNs=200000000)
    }
    test(s"$name stops the fast source and wakes at worst-case startup without losing host or CPU state") {
      val program = Seq(0x200000b7L,0x30000137L,
        i(0x13,3,0,0,0x123),store(1,3,0,2),
        i(0x13,3,0,0,2),store(2,3,56,2),
        i(0x13,3,0,0,-1),store(2,3,12,2),
        i(0x13,3,0,0,2000),store(2,3,60,2),
        i(0x03,4,2,2,4),i(0x13,4,0,4,1000),store(2,4,8,2),
        i(0x03,5,2,2,16),store(2,5,52,2),
        i(0x13,3,0,0,1),store(2,3,48,2),i(0x03,6,2,1,0),store(2,6,52,2),breakpoint)
      ClockedSimulation.run(top(click),name+"-deep-source",s"""
        #3000000; wait(!serviceClockEnable); #100;
        savedEdges=fastEdges; #500000;
        if(fastEdges != savedEdges || serviceClock !== 0 || !sleeping) $$fatal(1,"FAST_SOURCE_NOT_OFF");
        read_words(3,1,0);
        if(supported !== 255 || snapshot[0+:32] !== 129354 || snapshot[32+:32] !== 83333 ||
           snapshot[64+:32] !== 200000 || snapshot[192+:32] !== 100) $$fatal(1,"SLOW_TIMING_DISCOVERY");
        read_words(1,0,0); if(snapshot[160+:32] !== 0) $$fatal(1,"WAKE_PROBE_CHANGED_LOADER");
        set_period(100); expect_error(4); set_period(500); expect_error(0);
        #30000000;
        if(period < 7990000 || period > 8010000 || conversions < 4) $$fatal(1,"COARSE_ADC_CADENCE %f",period);
        ${upload(program)}
        wait(!serviceClockEnable); #100;
        if(!programmed || !locked || mode !== 3) $$fatal(1,"DEEP_SLEEP_FLAGS");
        gpioIn=5; wait(serviceClockEnable); #200000;
        if(mode !== 3) $$fatal(1,"MASKED_GPIO_WOKE_CPU");
        read_words(2,0,0); if(!snapshot[32]) $$fatal(1,"DEEP_TELEMETRY_STALE");
        #18000000;
        if(mode !== 4 || !programmed || !locked || resetReason) $$fatal(1,"SLOW_DEADLINE");
        read_words(128,0,0);
        if(!snapshot[1] || snapshot[32+:32] !== 32'h123) $$fatal(1,"DEEP_RETENTION");
        reset=1; #2000; reset=0; #3000000; wait(!serviceClockEnable);
        // A real oscillator failure still expires the LF watchdog; reset itself
        // re-enables the source, and does not reset the oscillator supplying LF.
        force dut.serviceClockEnable=0;
        wait(resetReason); #1000;
        if(!systemReset || programmed || locked) $$fatal(1,"DEEP_WATCHDOG_COVERAGE");
        release dut.serviceClockEnable; #7000000;
        if(systemReset || programmed || locked) $$fatal(1,"DEEP_WATCHDOG_RECOVERY");
      """,monitor,referenceHalfPeriodNs=1000000,onChipOscillator=true,
        chipParameters=lp,serviceStartupNs=100000,deadlineNs=250000000)
    }
    test(s"$name slow-clock Groundlark cold boot, confirmation and shutdown with stopped fast source") {
      val params=p.copy(config=Groundlark.configuration.copy(programBytes=16,workingRamBytes=32))
      ClockedSimulation.run(top(click,params,x => new GroundlarkBoard(x,PowerPolicy(enabled=true))),
        name+"-deep-board",s"""
        // 361 fastest-bound ticks are needed for 30 s off time. The accelerated
        // reference is 2 ms/tick here; nominal ms must not shorten that minimum.
        #650000000;
        if(gpioOut[0] || programmed) $$fatal(1,"MINIMUM_OFF_USED_NOMINAL_TIME");
        #90000000;
        if(!gpioOut[0] || programmed || sleepEntries < 100) $$fatal(1,"DEEP_CIRCULAR_BOOT");
        // Keep the production ratio (32 LF edges, two-edge reset hold). EBREAK
        // halts the uploaded application and deliberately stops its heartbeat.
        ${upload(Seq(breakpoint))}
        guardPower=1;
        wait(systemReset); #0.001;
        if(!gpioOut[0] || gpioOut[1] || !locked || !programmed) $$fatal(1,"WATCHDOG_CUT_PI_OR_UNLOCKED");
        // Persistent MODE must consume the synchronized reset, not raw expiry.
        repeat(2) begin
          @(posedge serviceClock); #0.001;
          if(mode !== 4) $$fatal(1,"MODE_USED_RAW_WATCHDOG_RESET");
        end
        @(posedge serviceClock); #0.001;
        if(mode !== 2) $$fatal(1,"MODE_MISSED_SYNCHRONIZED_RESET");
        wait(!systemReset); #5000;
        if(mode !== 2) $$fatal(1,"CRASH_NOT_READY_FOR_RESTART");
        read_words(0,0,8);
        if(supported !== 1 || snapshot[0+:32] !== 1) $$fatal(1,"FIRST_CRASH_COUNT");
        read_words(2,0,0);
        if(!snapshot[32]) $$fatal(1,"CRASH_STOPPED_SENSING");
        begin_image(4,0,0,32'h00010000); expect_error(2);
        command(5); // crash again while the permanent controller is shutting down
        adcCode=1500; wait(gpioOut[1]);
        if(!gpioOut[0]) $$fatal(1,"DEEP_EARLY_CUT");
        wait(systemReset); #1;
        if(!gpioOut[0] || !gpioOut[1] || !locked || !programmed) $$fatal(1,"CRASH_LOST_SHUTDOWN");
        wait(!systemReset); read_words(0,0,8);
        if(supported !== 1 || snapshot[0+:32] !== 2) $$fatal(1,"SECOND_CRASH_COUNT");
        gpioIn=0; #1000;
        if(!gpioOut[0]) $$fatal(1,"ACK_NOT_CONFIRMED");
        guardPower=0;
        #7000000;
        if(gpioOut[0] || gpioOut[1]) $$fatal(1,"DEEP_ACK_LOST");
        wait(!serviceClockEnable); reset=1; #1;
        if(gpioOut[0] || programmed || locked || !serviceClockEnable) $$fatal(1,"DEEP_POR_STATE");
      """,monitor+"""
reg guardPower=0;
always @(negedge gpioOut[0]) if(guardPower) $fatal(1,"UNREQUESTED_POWER_CUT");
""",referenceHalfPeriodNs=1000000,onChipOscillator=true,
        // Unchanged simulator replays took 112/114 host seconds after native
        // SRAM expansion; retain the 1.2 s simulated deadline and all assertions.
        chipParameters=lp,serviceStartupNs=100000,deadlineNs=1200000000,processTimeoutSeconds=240)
    }
  }
  test("slow elapsed time carries fractional milliseconds and bounds sample age across service outages") {
    val params=p.copy(adc=None,watchdogCycles=1000,lowPower=Some(lp.copy(stopServiceClock=false)))
    ClockedSimulation.run(new FabricFixture(params),"slow-elapsed","""
      #1000000; referenceEnabled=0; #1000;
      bus(1,32'h30000004,0);
      expected=((lfEdges-2)*129354)/1000;
      if(response_bits_data !== expected) $fatal(1,"INITIAL_SLOW_SCALE actual=%d expected=%d",response_bits_data,expected);
      for(chunk=0;chunk<4;chunk=chunk+1) begin
        bus(2,32'h30000028,123); bus(2,32'h3000002c,1);
        beforeEdges=lfEdges;
        clockEnabled=0; referenceEnabled=1; #3600000; referenceEnabled=0; clockEnabled=1; #5000;
        bus(1,32'h30000004,0);
        expected=((lfEdges-2)*129354)/1000;
        if(response_bits_data !== expected || resetReason) $fatal(1,"LOST_FRACTION_OR_TICKS actual=%d expected=%d",response_bits_data,expected);
        read_words(2,0,0);
        if(snapshot[64+:32] !== (lfEdges-beforeEdges)*200 || snapshot[32] || !snapshot[33])
          $fatal(1,"UNSAFE_SLOW_FRESHNESS %h",snapshot);
      end
    ""","""
integer lfEdges=0, beforeEdges, chunk; reg [31:0] expected;
always @(posedge watchdogClock) lfEdges=lfEdges+1;
task bus(input [1:0] op,input [31:0] addr,input [31:0] data); begin
  @(negedge serviceClock); request_bits_operation=op; request_bits_address=addr;
  request_bits_data=data; request_bits_mask=15; request_valid=1; response_ready=0;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0; wait(response_valid);
  if(response_bits_error) $fatal(1,"SLOW_BUS_ERROR");
  @(negedge serviceClock); response_ready=1; @(posedge serviceClock); #1; response_ready=0;
end endtask
    """,referenceHalfPeriodNs=100000)
  }
}
