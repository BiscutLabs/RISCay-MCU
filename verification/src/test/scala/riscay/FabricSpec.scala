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
}
