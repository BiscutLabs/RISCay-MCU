// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.clocked.ClockedCore

class ClockedCoreSpec extends AnyFunSuite {
  protected def desynchronized: Boolean = false
  private def runCore(name: String, body: String): java.nio.file.Path =
    SynchronousSimulation.run(if(desynchronized) new riscay.desync.ClockedCore else new ClockedCore,
      (if(desynchronized) "desync-" else "")+name,body,prototypeClock=desynchronized)
  import Assembly._
  import CorePrograms._
  private def hex(x: Long)=s"32'h${java.lang.Long.toHexString(x & 0xffffffffL)}"

  private def stimulus(expected: Reference.Result, seed: Int,
      resetPending: Boolean=false, corrupt: Boolean=false, dirtyReset: Boolean=false): String = {
    val random=new scala.util.Random(seed)
    val bus=expected.accesses.zipWithIndex.map { case(a,index) =>
      s"""
      wait(request_valid);
      repeat(${random.nextInt(5)+1}) begin
        @(negedge clock);
        if(!request_valid || request_bits_operation !== 2'd${a.op} ||
          request_bits_address !== ${hex(a.address)} || request_bits_data !== ${hex(a.data)} ||
          request_bits_mask !== 4'd${a.mask}) $$fatal(1,"BUS_STABILITY_$index");
      end
      request_ready=1;
      @(posedge clock);
      if(!request_valid) $$fatal(1,"MISSING_REQUEST_$index");
      @(negedge clock); request_ready=0;
      ${if(a.op==3) "" else s"""
      repeat(${random.nextInt(7)}) @(negedge clock);
      response_bits_data=${hex(a.response)}; response_bits_error=1'b${if(a.error) 1 else 0}; response_valid=1;
      @(posedge clock);
      if(!response_ready) $$fatal(1,"RESPONSE_NOT_ACCEPTED_$index");
      @(negedge clock); response_valid=0;
      """}
      """
    }.mkString("\n")
    val checks=expected.traces.zipWithIndex.map { case(t0,index) =>
      val t=if(corrupt && index==0) t0.copy(data=t0.data^1) else t0
      s"""$index: if(trace_pc !== ${hex(t.pc)} || trace_instruction !== ${hex(t.instruction)} ||
        trace_rd !== 4'd${t.rd} || trace_data !== ${hex(t.data)} ||
        trace_writeRegister !== 1'b${if(t.rd!=0 && !t.trap) 1 else 0} ||
        trace_trap !== 1'b${if(t.trap) 1 else 0} || trace_cause !== 4'd${t.cause})
        $$fatal(1,"RETIRE_MISMATCH_$index");"""
    }.mkString("\n")
    s"""module Testbench;
timeunit 1ns; timeprecision 1ps;
reg reset=1;
${if(desynchronized) "wire clock;"+DesyncSimulation.directClock(5,"clock","1'b1")
  else "reg clock=0; always #5 clock=~clock;"}
reg request_ready=0,response_valid=0,response_bits_error=0;
reg [31:0] response_bits_data=0;
wire request_valid,response_ready;
wire [1:0] request_bits_operation;
wire [31:0] request_bits_address,request_bits_data;
wire [3:0] request_bits_mask;
wire trace_valid,trace_writeRegister,trace_trap,traceEvent;
wire [31:0] trace_pc,trace_instruction,trace_data;
wire [3:0] trace_rd,trace_cause;
ClockedCore dut(.*);
integer retired=0;
reg observing=${if(dirtyReset) 0 else 1};
always @(posedge clock) begin
  #1;
  if(!reset && observing && traceEvent) begin
    if(!trace_valid) $$fatal(1,"INVALID_TRACE_EVENT");
    case(retired)
      $checks
      default: $$fatal(1,"EXTRA_RETIREMENT");
    endcase
    retired=retired+1;
  end
end
initial begin #1000000; $$fatal(1,"CLOCKED_CORE_DEADLINE"); end
task dirty_fetch(input [31:0] pc, input [31:0] word); begin
  wait(request_valid); @(negedge clock);
  if(request_bits_operation !== 0 || request_bits_address !== pc) $$fatal(1,"DIRTY_RESET_FETCH");
  request_ready=1; @(negedge clock); request_ready=0;
  response_bits_data=word; response_valid=1;
  @(negedge clock); response_valid=0;
end endtask
initial begin
  repeat(3) @(negedge clock); reset=0;
  ${if(dirtyReset) (1 to 15).map(n => s"dirty_fetch(${hex((n-1)*4)},${hex(i(0x13,n,0,0,n))});").mkString("\n") + s"""
  dirty_fetch(32'd60,${hex(i(0x03,1,2,0,1024))});
  wait(request_valid); @(negedge clock);
  if(request_bits_operation !== 1 || request_bits_address !== 1024) $$fatal(1,"DIRTY_RESET_DATA");
  request_ready=1; @(negedge clock); request_ready=0;
  repeat(4) @(negedge clock);
  if(!response_ready) $$fatal(1,"DATA_NOT_PENDING");
  reset=1; repeat(3) @(negedge clock); reset=0; observing=1;
  """ else ""}
  ${if(resetPending) """
  wait(request_valid); @(negedge clock); request_ready=1;
  @(negedge clock); request_ready=0;
  repeat(4) @(negedge clock);
  if(!response_ready) $fatal(1,"FETCH_NOT_PENDING");
  reset=1; repeat(3) @(negedge clock); reset=0;
  """ else ""}
  $bus
  repeat(5) @(negedge clock);
  if(request_valid || response_ready || retired != ${expected.traces.size}) $$fatal(1,"HALT_NOT_QUIESCENT");
  $$display("RISCAY_CLOCKED_PASS"); $$finish;
end
endmodule
"""
  }

  test("clocked arithmetic, memory, branches and stalls match the shared independent oracle") {
    for((program,name) <- Seq(arithmetic->"arithmetic",memoryAndControl->"memory",predicates->"branches"); seed <- Seq(1,19)) {
      runCore("core-"+name,stimulus(Reference.run(program),seed))
    }
  }
  test("clocked reset cancels an outstanding fetch") {
    runCore("core-reset",stimulus(Reference.run(known),31,resetPending=true))
  }
  test("clocked reset during a pending load clears progressed PC and all fifteen written registers") {
    val program=(1 to 15).map(n => store(0,n,1024+4*(n-1),2)) ++ Seq(breakpoint)
    runCore("core-dirty-reset",stimulus(Reference.run(program),7,dirtyReset=true))
  }
  test("clocked illegal encodings, alignment and access faults preserve architectural causes") {
    val cases=Seq(Seq(0L),Seq(i(0x13,16,0,0,1)),Seq(i(0x13,1,0,16,1)),Seq(r(1,0,0,16)),
      Seq(r(1,0,0,0,1)),Seq(0x100fL),Seq(0x73L),Seq(jal(1,2)),
      Seq(i(0x03,1,2,0,1)),Seq(store(0,1,1,1)),Seq(i(0x03,1,2,0,1024)),Seq(store(0,1,1024,2)))
    for(program <- cases) runCore("core-fault",stimulus(Reference.run(program,denied=Set(1024L)),19))
    runCore("core-fetch-fault",stimulus(Reference.run(Seq(breakpoint),denied=Set(0L)),1))
  }
  test("clocked retirement oracle rejects an incorrect architectural result") {
    val e=intercept[IllegalArgumentException] {
      runCore("core-negative",stimulus(Reference.run(known),1,corrupt=true))
    }
    assert(e.getMessage.contains("RETIRE_MISMATCH_0"),e.getMessage)
  }
}

class DesyncCoreSpec extends ClockedCoreSpec {override protected def desynchronized = true}
