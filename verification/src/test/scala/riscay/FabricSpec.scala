// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chiselasync.protocol.Channel
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Direct service-bus fixture complements the full serial-host/CPU SoC tests. */
class FabricFixture(p: SocParameters) extends riscay.bd.FourPhasePlatform(p, x => new GenericBoard(x)) {
  val request = IO(Flipped(Decoupled(new MemoryRequest)))
  val response = IO(Decoupled(new MemoryResponse))
  val timeNow = IO(Output(UInt(32.W))); timeNow := fabric.io.now
  fabric.io.request <> request; response <> fabric.io.response
  trace := 0.U.asTypeOf(new Retirement); traceEvent := false.B
  contract.clockedChannel("request", request, serviceClock, new Channel(new MemoryRequest, resetDomain), "input")
  contract.clockedChannel("response", response, serviceClock, new Channel(new MemoryResponse, resetDomain), "output")
}

class KickFixture(p: SocParameters) extends FabricFixture(p) {
  val ack = IO(Input(Bool())); val heartbeat = IO(Output(Bool()))
  fabric.io.watchdogAck := ack; heartbeat := fabric.io.heartbeat
}

class WaitValidationFixture(p: SocParameters) extends FabricFixture(p) {
  val sleepEligible = IO(Output(Bool())); sleepEligible := fabric.io.canSleep
}

class ResetCrossingFixture(p: SocParameters) extends FabricFixture(p) {
  val heartbeatEnabled = IO(Input(Bool()))
  val resetObserved = IO(Output(Bool())); resetObserved := cpuResetActive
  val gatedClock = IO(Output(Clock())); gatedClock := workClock
  watchdog.io.heartbeat := Mux(heartbeatEnabled, fabric.io.heartbeat, false.B)
}

class ClickFabricFixture(p: SocParameters) extends riscay.click.ClickPlatform(p, x => new GenericBoard(x)) {
  val request = IO(Flipped(Decoupled(new MemoryRequest)))
  val response = IO(Decoupled(new MemoryResponse))
  val timeNow = IO(Output(UInt(32.W))); timeNow := fabric.io.now
  fabric.io.request <> request; response <> fabric.io.response
  trace := 0.U.asTypeOf(new Retirement); traceEvent := false.B
  contract.clockedChannel("request", request, serviceClock, new Channel(new MemoryRequest, resetDomain), "input")
  contract.clockedChannel("response", response, serviceClock, new Channel(new MemoryResponse, resetDomain), "output")
}

class ClickKickFixture(p: SocParameters) extends ClickFabricFixture(p) {
  val ack = IO(Input(Bool())); val heartbeat = IO(Output(Bool()))
  fabric.io.watchdogAck := ack; heartbeat := fabric.io.heartbeat
}

class ClickWaitValidationFixture(p: SocParameters) extends ClickFabricFixture(p) {
  val sleepEligible = IO(Output(Bool())); sleepEligible := fabric.io.canSleep
}

class ClickResetCrossingFixture(p: SocParameters) extends ClickFabricFixture(p) {
  val heartbeatEnabled = IO(Input(Bool()))
  val resetObserved = IO(Output(Bool())); resetObserved := cpuResetActive
  val gatedClock = IO(Output(Clock())); gatedClock := workClock
  watchdog.io.heartbeat := Mux(heartbeatEnabled, fabric.io.heartbeat, false.B)
}

class FabricSpec extends AnyFunSuite {
  private val config = McuConfiguration(16, 16, 1,
    Vector(MeasurementChannel(0,"first",2,0), MeasurementChannel(1,"second",1,-3)),
    ApplicationProfile(123,1,"fixture",Vector(HostRegister(0,"COUNT")),Vector.empty))
  private val tasks = """
integer effects=0;
always @(posedge serviceClock) if(!systemReset && commit_valid) effects=effects+1;
task issue(input [1:0] operation, input [31:0] address, input [31:0] data, input [3:0] mask);
begin
  @(negedge serviceClock);
  request_bits_operation=operation; request_bits_address=address; request_bits_data=data; request_bits_mask=mask;
  request_valid=1;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
end endtask
task answer(input [31:0] expected, input error, input integer stalls);
reg [32:0] saved; integer n; begin
  wait(response_valid); saved={response_bits_error,response_bits_data};
  if(response_bits_error !== error || (!error && response_bits_data !== expected))
    $fatal(1,"FABRIC_ANSWER actual=%h error=%b expected=%h error=%b",response_bits_data,response_bits_error,expected,error);
  for(n=0;n<stalls;n=n+1) begin
    @(negedge serviceClock);
    if(!response_valid || {response_bits_error,response_bits_data} !== saved) $fatal(1,"RESPONSE_CHANGED_WHILE_STALLED");
  end
  @(negedge serviceClock); response_ready=1;
  @(posedge serviceClock); #1; response_ready=0;
end endtask
task write_bus(input [31:0] address, input [31:0] value);
begin issue(2,address,value,15); answer(0,0,3); end endtask
reg [31:0] timeValue;
"""
  for(click <- Seq(false,true)) {
    def fixture(p: SocParameters): SocTop = if(click) new ClickFabricFixture(p) else new FabricFixture(p)
    def waitFixture(p: SocParameters): SocTop = if(click) new ClickWaitValidationFixture(p) else new WaitValidationFixture(p)
    def resetFixture(p: SocParameters): SocTop = if(click) new ClickResetCrossingFixture(p) else new ResetCrossingFixture(p)
    def kickFixture(p: SocParameters): SocTop = if(click) new ClickKickFixture(p) else new KickFixture(p)
    val variant = if(click) "click" else "bd"
  test(s"$variant: invalid boot/WAIT read masks fault promptly without parking or consuming events and leases") {
    val params = SocParameters(config, watchdogCycles=1000000, lowPower=Some(LowPowerParameters()))
    ClockedSimulation.run(waitFixture(params), "wait-validation", """
      // Freeze the timebase before its first edge so a lease cannot age and
      // no periodic event can accidentally release a malformed WAIT.
      referenceEnabled=0;
      write_bus(32'h30000038,4);
      for(eventCase=0;eventCase<2;eventCase=eventCase+1) begin
        write_bus(32'h3000000c,32'hffffffff);
        if(eventCase==1) begin gpioIn=1; #1000; end
        write_bus(32'h3000003c,30000);
        for(badMask=0;badMask<15;badMask=badMask+1) begin
          reject_read(32'h30000000,badMask);
          reject_read(32'h30000010,badMask);
          issue(1,32'h3000003c,0,15); answer(30000,0,2);
          issue(1,32'h3000000c,0,15); answer(eventCase==0 ? 0 : 4,0,2);
        end
      end
      // A valid WAIT must still consume the lease and return the GPIO event.
      issue(1,32'h30000010,0,15); answer(4,0,2);
      issue(1,32'h3000003c,0,15); answer(0,0,2);
    """, tasks+"""
integer eventCase,badMask;
task reject_read(input [31:0] address, input [3:0] mask);
integer cycles; reg accepted; begin
  @(negedge serviceClock);
  request_valid=1; request_bits_operation=1; request_bits_address=address;
  request_bits_data=0; request_bits_mask=mask; accepted=0;
  for(cycles=0;cycles<30 && !accepted;cycles=cycles+1) begin
    @(posedge serviceClock);
    if(sleepEligible) $fatal(1,"MALFORMED_READ_PARKED");
    if(request_ready) begin accepted=1; #1; request_valid=0; end
  end
  if(!accepted) $fatal(1,"MALFORMED_READ_BLOCKED address=%h mask=%h",address,mask);
  answer(0,1,2);
end endtask
""", referenceHalfPeriodNs=10000000)
  }

  test(s"$variant: deadline replacement consumes stale or coincident expiry, preserves GPIO, and arms the next wait") {
    ClockedSimulation.run(fixture(SocParameters(config,serviceHz=100000,watchdogCycles=1000000)),
      "deadline-replacement","""
      gpioIn=1; #1000;
      write_bus(32'h30000038,2); // Only deadline wakes the blocking read.
      write_bus(32'h30000008,0); // Expire while handling the previous GPIO wake.
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(!response_bits_data[1] || !response_bits_data[2]) $fatal(1,"OLD_EVENTS_MISSING");
      timeValue=response_bits_data; answer(timeValue,0,1);
      // A rejected byte write must not consume the old deadline event.
      issue(2,32'h30000008,timeNow+10,1); answer(0,1,1);
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(!response_bits_data[1]) $fatal(1,"REJECTED_REPLACEMENT_CLEARED_EVENT");
      timeValue=response_bits_data; answer(timeValue,0,1);
      targetTime=timeNow+10;
      write_bus(32'h30000008,targetTime);
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(response_bits_data[1] || !response_bits_data[2]) $fatal(1,"REPLACEMENT_LOST_WRONG_EVENTS");
      timeValue=response_bits_data; answer(timeValue,0,1);
      @(negedge serviceClock);
      request_bits_operation=1; request_bits_address=32'h30000010;
      request_bits_data=0; request_bits_mask=15; request_valid=1;
      repeat(200) begin @(posedge serviceClock); if(request_ready || response_valid) $fatal(1,"NEXT_WAIT_ENDED_EARLY"); end
      @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
      #1; request_valid=0; wait(response_valid);
      if(timeNow < targetTime || !response_bits_data[1]) $fatal(1,"NEW_DEADLINE_NOT_ARMED");
      timeValue=response_bits_data; answer(timeValue,0,1);
      write_bus(32'h3000000c,32'hffffffff);
      targetTime=timeNow+4; write_bus(32'h30000008,targetTime);
      // 100 clocks/ms: GPIO's second synchronizer changes with NOW, so both
      // its pending bit and the old deadline become due on the replacement edge.
      wait(timeNow == targetTime-1);
      repeat(98) @(posedge serviceClock);
      @(negedge serviceClock); gpioIn=0;
      wait(timeNow == targetTime);
      write_bus(32'h30000008,targetTime+4);
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(response_bits_data[1] || !response_bits_data[2]) $fatal(1,"COINCIDENT_REPLACEMENT_PRIORITY");
      timeValue=response_bits_data; answer(timeValue,0,1);
      // A newly programmed already-due deadline fires on the following edge.
      write_bus(32'h30000008,timeNow);
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(!response_bits_data[1]) $fatal(1,"PAST_REPLACEMENT_NEVER_FIRED");
      timeValue=response_bits_data; answer(timeValue,0,1);
    """,tasks+"reg [31:0] targetTime;\n")
  }
  test(s"$variant: watchdog reset data uses two service edges and the retained clock has complete pulses") {
    val params=SocParameters(config,watchdogCycles=32,watchdogHoldCycles=2,
      lowPower=Some(LowPowerParameters.gf180Slow.copy(stopServiceClock=false)))
    ClockedSimulation.run(resetFixture(params),"reset-crossing","""
      heartbeatEnabled=1; #100000;
      read_words(0,0,8); if(supported !== 1 || snapshot[0+:32] !== 0) $fatal(1,"POR_COUNTED_AS_CRASH");
      for(crashes=1;crashes<=3;crashes=crashes+1) begin
        write_bus(32'h30000018,1);
        // Park at the boot wait so the retained gate closes between LF ticks.
        @(negedge serviceClock); request_valid=1; request_bits_operation=1;
        request_bits_address=32'h30000000; request_bits_mask=15;
        wait(sleeping); heartbeatEnabled=0;
        @(posedge systemReset);
        if(resetObserved) $fatal(1,"RESET_DATA_ASSERTED_ASYNCHRONOUSLY");
        #0.001; if(gpioOut[0]) $fatal(1,"RESET_PINS_WAITED_FOR_SYNCHRONIZER");
        heartbeatEnabled=1;
        wait(resetObserved); wait(!systemReset); wait(!resetObserved);
        @(negedge serviceClock); request_valid=0;
        read_words(0,0,8);
        if(supported !== 1 || snapshot[0+:32] !== crashes) $fatal(1,"REPEAT_CRASH_COUNT");
      end
      if(assertions != 3 || pulseChecks < 20 || sleepEntries == 0) $fatal(1,"RESET_CROSSING_NO_COVERAGE");
      reset=1; #2000; reset=0; #3000;
      read_words(0,0,8); if(snapshot[0+:32] !== 0) $fatal(1,"CRASH_COUNT_NOT_POR_CLEARED");
    """,tasks+"""
integer crashes,assertions=0,pulseChecks=0;
reg expectedFirst=1,expectedSecond=1;
real gateRise=0, gateFall=0;
always @(posedge serviceClock or posedge reset) begin
  if(reset) begin expectedFirst=1; expectedSecond=1; end
  else begin expectedSecond=expectedFirst; expectedFirst=systemReset; end
  #0.001; if(resetObserved !== expectedSecond) $fatal(1,"RESET_TWO_FLOP_LATENCY");
end
always @(posedge systemReset) if(!reset) assertions=assertions+1;
always @(posedge gatedClock) begin
  if(!reset && gateFall>0 && $realtime-gateFall<49.999) $fatal(1,"RUNT_GATED_LOW");
  gateRise=$realtime;
end
always @(negedge gatedClock) begin
  if(!reset && gateRise>0 && $realtime-gateRise<49.999) $fatal(1,"RUNT_GATED_HIGH");
  gateFall=$realtime; pulseChecks=pulseChecks+1;
end
""",referenceHalfPeriodNs=17003)
  }
  test(s"$variant: clocked services: access errors, byte lanes, backpressure, events, failed/stale samples and interrupted reset") {
    ClockedSimulation.run(fixture(SocParameters(config, staleMs=2)), "fabric", """
      issue(0,0,0,15); answer(32'h300000b7,0,7);
      issue(2,0,0,15); answer(0,1,2);
      issue(0,32'h20000000,0,15); answer(0,1,2);
      issue(1,32'h10000000,0,15); answer(0,1,2);
      issue(1,32'h20000010,0,15); answer(0,1,2);
      issue(2,32'h20000000,32'h11223344,15); answer(0,0,3);
      issue(2,32'h20000001,32'h0000aa00,2); answer(0,0,11);
      issue(1,32'h20000000,0,15); answer(32'h1122aa44,0,2);
      issue(2,32'h2000000c,32'hdeadbeef,15); answer(0,0,3);
      issue(1,32'h2000000c,0,15); answer(32'hdeadbeef,0,2);
      issue(2,32'h30000018,1,1); answer(0,1,2);
      write_bus(32'h30000018,1); write_bus(32'h3000001c,1);
      if(gpioOut !== 1 || gpioOe !== 1) $fatal(1,"GENERIC_GPIO");
      write_bus(32'h30000024,1); write_bus(32'h30000028,12345); write_bus(32'h3000002c,3);
      read_words(2,1,0);
      if(snapshot[0+:32] !== 12345 || snapshot[32+:32] !== 17 || snapshot[96+:32] !== 1) $fatal(1,"GENERIC_SAMPLE");
      write_bus(32'h3000002c,0); // Failure preserves old value and last-good age.
      read_words(2,1,0);
      if(snapshot[0+:32] !== 12345 || snapshot[32] || !snapshot[35] || snapshot[96+:32] !== 2 || snapshot[64+:32] == 0) $fatal(1,"FAILED_SAMPLE");
      #3000000; read_words(2,1,0);
      if(!snapshot[33] || snapshot[32]) $fatal(1,"STALE_SAMPLE");
      read_words(2,0,0);
      if(!snapshot[34] || snapshot[64+:32] !== 32'hffffffff) $fatal(1,"NEVER_SAMPLED");
      write_bus(32'h3000000c,32'hffffffff);
      // Timer event wakes a wait independently of the CPU and host bus.
      issue(1,32'h30000010,0,15); wait(response_valid);
      if(!response_bits_data[0]) $fatal(1,"WAIT_LOST_TICK");
      @(negedge serviceClock); response_ready=1; @(posedge serviceClock); #1; response_ready=0;
      // An accepted response may be stalled while host reads continue.
      issue(1,32'h20000000,0,15); read_words(0,0,0); answer(32'h1122aa44,0,9);
      issue(1,32'h20000000,0,15); wait(response_valid);
      reset=1; #2000;
      if(response_valid) $fatal(1,"STALE_RESET_RESPONSE");
      reset=0; #5000;
      issue(1,32'h20000000,0,15); answer(32'h1122aa44,0,1);
      if(effects != 22) $fatal(1,"EXACTLY_ONCE effects=%d",effects);
      // GPIO event and software clear commit together: the event must win.
      gpioIn=1;
      @(posedge serviceClock); @(posedge serviceClock);
      write_bus(32'h3000000c,32'hffffffff);
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(!response_bits_data[2]) $fatal(1,"CLEAR_LOST_GPIO_EVENT");
      timeValue=response_bits_data; answer(timeValue,0,1);
      issue(1,32'h30000004,0,15); wait(response_valid);
      timeValue=response_bits_data; answer(timeValue,0,1);
      write_bus(32'h30000008,timeValue+3);
      write_bus(32'h3000000c,32'hffffffff);
      #4000000;
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(!response_bits_data[1]) $fatal(1,"DEADLINE_NOT_CAPTURED");
      timeValue=response_bits_data; answer(timeValue,0,1);
      // Drop an incomplete loader transaction with full reset, then recover.
      begin_image(4,0,0,32'h00010000);
      start_bus(); write_byte(8'h6a); write_byte(2); write_word(0); write_byte(8'h73);
      reset=1; #2000; stop_bus(); reset=0; #5000;
      command(3); expect_error(6);
      if(programmed || locked) $fatal(1,"RESET_REPLAYED_PARTIAL_UPLOAD");
    """, tasks)
  }
  test(s"$variant: zero-channel, zero-GPIO profile elaborates and rejects absent resources") {
    val minimal = config.copy(gpioCount=0, measurements=Vector.empty)
    ClockedSimulation.run(fixture(SocParameters(minimal)), "empty-profile", """
      read_words(0,0,0);
      if(snapshot[160+:32] !== 0 || snapshot[192+:32] !== 0) $fatal(1,"NONEMPTY_CAPACITIES");
      read_words(2,0,0); if(supported !== 0) $fatal(1,"ABSENT_MEASUREMENT");
      issue(2,32'h30000024,0,15); answer(0,1,1);
    """, tasks)
  }
  test(s"$variant: watchdog kicks queue behind CDC acknowledgement; lease writes cannot substitute for the magic word") {
    val params=SocParameters(config,watchdogCycles=1000,lowPower=Some(LowPowerParameters.gf180Slow))
    ClockedSimulation.run(kickFixture(params),"kick-queue","""
      // Stop reference before its first edge: no automatic bootstrap tick.
      referenceEnabled=0;
      write_bus(32'h3000003c,0);
      write_bus(32'h3000003c,1000);
      issue(2,32'h30000020,0,15); answer(0,1,1);
      if(heartbeat) $fatal(1,"LEASE_OR_BAD_MAGIC_KICKED");
      write_bus(32'h30000020,32'h57444f47);
      if(!heartbeat) $fatal(1,"FIRST_KICK_LOST");
      write_bus(32'h30000020,32'h57444f47);
      #1000; if(!heartbeat) $fatal(1,"BUSY_KICK_OVERWROTE_PHASE");
      ack=1; #1000;
      if(heartbeat) $fatal(1,"QUEUED_KICK_LOST");
      ack=0; #1000;
      repeat(10) begin write_bus(32'h3000003c,0); write_bus(32'h3000003c,1000); end
      if(heartbeat) $fatal(1,"LEASE_WRITE_KICKED");
      reset=1; #1000;
      if(heartbeat) $fatal(1,"KICK_POR");
    """,tasks,referenceHalfPeriodNs=10000000)
  }
  test(s"$variant: sparse application words reject holes and share coherent snapshot data across byte boundaries") {
    val sparse=config.copy(application=config.application.copy(registers=Vector(
      HostRegister(0,"FIRST"),HostRegister(1,"NEXT"),HostRegister(17,"MIDDLE"),HostRegister(63,"LAST"))))
    ClockedSimulation.run(fixture(SocParameters(sparse)),"sparse-application","""
      write_bus(32'h30000034,32'h12345678);
      write_bus(32'h30000030,1); write_bus(32'h30000034,32'h02468ace);
      write_bus(32'h30000030,17); write_bus(32'h30000034,32'h89abcdef);
      write_bus(32'h30000030,63); write_bus(32'h30000034,32'h76543210);
      issue(2,32'h30000030,2,15); answer(0,1,1);
      issue(1,32'h30000034,0,15); answer(32'h76543210,0,1);
      read_words(128,0,16);
      if(supported !== 2 || snapshot[0+:32] !== 32'hffffffff || snapshot[32+:32] !== 32'h89abcdef)
        $fatal(1,"SPARSE_WORD_ALIASED");
      read_words(128,0,63);
      if(supported !== 1 || snapshot[0+:32] !== 32'h76543210 || snapshot[32+:32] !== 32'hffffffff)
        $fatal(1,"SPARSE_END_WRAPPED");
      // Keep the serial transaction open while software updates the bank.
      start_bus(); write_byte(8'h6a); write_byte(0); write_byte(128); write_byte(0); write_byte(0);
      start_bus(); write_byte(8'h6b);
      read_byte(firstByte,0);
      write_bus(32'h30000030,0); write_bus(32'h30000034,32'hffffffff);
      write_bus(32'h30000030,1); write_bus(32'h30000034,32'hffffffff);
      read_byte(secondByte,0); read_byte(thirdByte,0); read_byte(fourthByte,0);
      for(byteNo=0;byteNo<4;byteNo=byteNo+1) begin
        read_byte(laterByte,byteNo==3); laterWord[byteNo*8+:8]=laterByte;
      end
      stop_bus();
      if({fourthByte,thirdByte,secondByte,firstByte} !== 32'h12345678) $fatal(1,"TORN_SNAPSHOT");
      if(laterWord !== 32'h02468ace) $fatal(1,"TORN_LATER_WORD");
      read_words(128,0,0); if(snapshot[0+:32] !== 32'hffffffff) $fatal(1,"SNAPSHOT_NOT_REFRESHED");
    """,tasks+"reg [7:0] firstByte,secondByte,thirdByte,fourthByte,laterByte; reg [31:0] laterWord; integer byteNo;\n")
  }
  }
}
