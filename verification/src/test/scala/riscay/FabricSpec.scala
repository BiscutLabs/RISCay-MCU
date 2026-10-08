// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chiselasync.protocol.Channel
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Direct service-bus fixture complements the full serial-host/CPU SoC tests. */
class FabricFixture(p: SocParameters) extends SocTop(p, x => new GenericBoard(x)) {
  val request = IO(Flipped(Decoupled(new MemoryRequest)))
  val response = IO(Decoupled(new MemoryResponse))
  fabric.io.request <> request; response <> fabric.io.response
  trace := 0.U.asTypeOf(new Retirement); traceEvent := false.B
  contract.clockedChannel("request", request, serviceClock, new Channel(new MemoryRequest, resetDomain), "input")
  contract.clockedChannel("response", response, serviceClock, new Channel(new MemoryResponse, resetDomain), "output")
}

class KickFixture(p: SocParameters) extends FabricFixture(p) {
  val ack = IO(Input(Bool())); val heartbeat = IO(Output(Bool()))
  fabric.io.watchdogAck := ack; heartbeat := fabric.io.heartbeat
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
  test("shared fabric: access errors, byte lanes, backpressure, events, failed/stale samples and interrupted reset") {
    ClockedSimulation.run(new FabricFixture(SocParameters(config, staleMs=2)), "fabric", """
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
  test("zero-channel, zero-GPIO profile elaborates and rejects absent resources") {
    val minimal = config.copy(gpioCount=0, measurements=Vector.empty)
    ClockedSimulation.run(new FabricFixture(SocParameters(minimal)), "empty-profile", """
      read_words(0,0,0);
      if(snapshot[160+:32] !== 0 || snapshot[192+:32] !== 0) $fatal(1,"NONEMPTY_CAPACITIES");
      read_words(2,0,0); if(supported !== 0) $fatal(1,"ABSENT_MEASUREMENT");
      issue(2,32'h30000024,0,15); answer(0,1,1);
    """, tasks)
  }
  test("watchdog kicks queue behind CDC acknowledgement; lease writes cannot substitute for the magic word") {
    val params=SocParameters(config,watchdogCycles=1000,lowPower=Some(LowPowerParameters.gf180Slow))
    ClockedSimulation.run(new KickFixture(params),"kick-queue","""
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
  test("sparse application words reject holes and share coherent snapshot data across byte boundaries") {
    val sparse=config.copy(application=config.application.copy(registers=Vector(
      HostRegister(0,"FIRST"),HostRegister(1,"NEXT"),HostRegister(17,"MIDDLE"),HostRegister(63,"LAST"))))
    ClockedSimulation.run(new FabricFixture(SocParameters(sparse)),"sparse-application","""
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
