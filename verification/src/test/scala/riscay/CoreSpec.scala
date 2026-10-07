// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.AsyncModule
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.bd.FourPhaseCore
import riscay.click.ClickCore

class CoreSpec extends AnyFunSuite {
  import Assembly._
  private def fresh(name: String) = {
    val root = Paths.get("build/core-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root, name)
  }
  private def hex(x: Long) = "32'h" + java.lang.Long.toHexString(x & 0xffffffffL)
  private def core(click: Boolean): AsyncModule = if(click) new ClickCore else new FourPhaseCore

  private def bus(a: Reference.Access, click: Boolean, number: Int): String = {
    val arrival = if(click) "wait(request_req != request_ack);" else "wait(request_req);"
    val release = if(click) "request_ack=request_req;" else "request_ack=1; wait(!request_req); #100000000; request_ack=0;"
    val reply = if(a.op == 3) "" else s"""
      response_bits_data=${hex(a.response)}; response_bits_error=${if(a.error) 1 else 0};
      #${100000000L + (number % 5)*19000000L};
      ${if(click) "response_req=~response_req; wait(response_ack == response_req);" else "response_req=1; wait(response_ack); #100000000; response_req=0; wait(!response_ack);"}
    """
    s"""
      $arrival
      #${70000000L + (number % 7)*13000000L};
      if(request_bits_operation !== 2'd${a.op} || request_bits_address !== ${hex(a.address)} ||
         request_bits_data !== ${hex(a.data)} || request_bits_mask !== 4'd${a.mask})
        $$fatal(1,"BUS_MISMATCH_${number} op=%d address=%h data=%h mask=%h",request_bits_operation,request_bits_address,request_bits_data,request_bits_mask);
      $release
      $reply
    """
  }

  private def stimulus(result: Reference.Result, click: Boolean, resetPending: Boolean = false,
      corruptExpectation: Boolean = false): String = {
    val checks = result.traces.zipWithIndex.map { case (original, index) =>
      val t = if(corruptExpectation && index == 0) original.copy(data=original.data ^ 1) else original
      s"""$index: begin
        if(trace_pc !== ${hex(t.pc)} || trace_instruction !== ${hex(t.instruction)} ||
           trace_writeRegister !== 1'b${if(t.rd != 0 && !t.trap) 1 else 0} || trace_rd !== 4'd${t.rd} ||
           trace_data !== ${hex(t.data)} || trace_trap !== 1'b${if(t.trap) 1 else 0} || trace_cause !== 4'd${t.cause})
          $$fatal(1,"RETIRE_MISMATCH_$index pc=%h insn=%h rd=%d data=%h trap=%d cause=%d",
            trace_pc,trace_instruction,trace_rd,trace_data,trace_trap,trace_cause);
      end"""
    }.mkString("\n")
    val pending = if(!resetPending) "" else s"""
      ${if(click) "start=1; wait(request_req != request_ack); #100000000; request_ack=request_req;" else "wait(request_req); #100000000; request_ack=1; wait(!request_req); #100000000; request_ack=0;"}
      #300000000;
      reset=1; ${if(click) "start=0;" else ""} request_ack=0; response_req=0; response_bits_data=0; response_bits_error=0;
      #1000000000; reset=0; #1000000000;
    """
    s"""
      begin
      integer retired;
      reg seen;
      reg bus_done;
      retired=0; seen=0; bus_done=0;
      $pending
      ${if(click) "start=1;" else ""}
      fork
        begin
          ${result.accesses.zipWithIndex.map { case(a,i) => bus(a,click,i) }.mkString("\n")}
          bus_done=1;
        end
        begin
          while(retired < ${result.traces.size}) begin
            ${if(click) "wait(traceEvent != seen); seen=traceEvent;" else "wait(traceEvent);"}
            if(trace_valid) begin
              case(retired)
                $checks
                default: $$fatal(1,"EXTRA_RETIREMENT");
              endcase
              retired=retired+1;
            end
            ${if(click) "#1;" else "wait(!traceEvent);"}
          end
        end
      join
      #2000000000;
      if(!bus_done || retired != ${result.traces.size}) $$fatal(1,"MISSING_ACTIVITY");
      ${if(click) "if(request_req != request_ack) $fatal(1,\"HALT_NOT_QUIESCENT\");" else "if(request_req) $fatal(1,\"HALT_NOT_QUIESCENT\");"}
      $$display("RISCAY_ACTIVITY retirements=%0d transactions=${result.accesses.size}",retired);
      end
    """
  }

  private val known = Seq(
    i(0x13,1,0,0,-1), i(0x13,2,0,0,1), r(3,0,1,2), r(4,2,1,2), r(5,3,1,2),
    i(0x13,0,0,0,99), i(0x13,6,0,0,7), breakpoint)

  test("independent oracle agrees with hand-calculated signed, unsigned and x0 results") {
    val r = Reference.run(known)
    assert(r.registers.take(7) == Vector(0L,0xffffffffL,1L,0L,1L,0L,7L))
    assert(r.traces.last.cause == 3)
  }

  private def arithmetic: Seq[Long] = {
    val random = new scala.util.Random(3027)
    val seeds = (1 to 15).map(r => i(0x13,r,0,0,random.nextInt(4096)-2048))
    val body = (0 until 120).map { _ =>
      val rd=random.nextInt(16); val a=random.nextInt(16); val b=random.nextInt(16); val f=random.nextInt(8)
      if(random.nextBoolean()) r(rd,f,a,b,if((f==0 || f==5) && random.nextBoolean()) 32 else 0)
      else i(0x13,rd,f,a,if(f==1) random.nextInt(32) else if(f==5) random.nextInt(32)+(if(random.nextBoolean()) 1024 else 0) else random.nextInt(4096)-2048)
    }
    known.dropRight(1) ++ seeds ++ body ++ Seq(0x800002b7L,0x297L,0x0fL,breakpoint)
  }

  private val memoryAndControl = Seq(
    i(0x13,15,0,0,1024), i(0x13,1,0,0,-128), store(15,1,0,2),
    i(0x03,2,0,15,0), i(0x03,3,4,15,0), i(0x03,4,1,15,0), i(0x03,5,5,15,0), i(0x03,6,2,15,0),
    i(0x13,7,0,0,18), store(15,7,1,0), i(0x03,8,4,15,1),
    store(15,1,2,1), i(0x03,9,1,15,2), i(0x03,10,5,15,2),
    i(0x13,11,0,0,3), i(0x13,11,0,11,-1), branch(11,0,-4,1),
    branch(1,7,8,4), i(0x13,1,0,0,99), branch(7,1,8,6), i(0x13,2,0,0,99),
    jal(12,8), i(0x13,3,0,0,99),
    i(0x17,13,0,0,0), // AUIPC x13,0 (i encoder supplies the same zero upper immediate)
    i(0x67,14,0,13,12), i(0x13,4,0,0,99),
    breakpoint)

  private val predicates = Seq(i(0x13,1,0,0,-1),i(0x13,2,0,0,1),i(0x13,3,0,0,0)) ++
    Seq(0,1,4,5,6,7).flatMap { f =>
      Seq(branch(1,2,8,f),i(0x13,3,0,3,1),branch(2,1,8,f),i(0x13,3,0,3,2),
        branch(1,1,8,f),i(0x13,3,0,3,4))
    } ++ Seq(jal(0,8),i(0x13,3,0,3,100),i(0x13,4,0,0,7),breakpoint)

  for(click <- Seq(false,true)) {
    val name = if(click) "click" else "four-phase"
    test(s"$name RV32E arithmetic matches independent retirement and memory traces under varied delays") {
      val expected = Reference.run(arithmetic)
      AsyncTest.run(core(click),Seq(1,2,19,81),fresh(name+"-arithmetic"))(_ => stimulus(expected,click))
    }
    test(s"$name loads stores branches jumps and stalled memory preserve exactly-once effects") {
      val expected = Reference.run(memoryAndControl)
      assert(expected.registers(3)==128 && expected.registers(8)==18 && expected.registers(9)==0xffffff80L)
      AsyncTest.run(core(click),Seq(1,19,81),fresh(name+"-memory"))(_ => stimulus(expected,click))
    }
    test(s"$name all six branch predicates cover signed unsigned equal and unequal operands") {
      val expected=Reference.run(predicates)
      assert(expected.registers(0)==0 && expected.registers(3)==21 && expected.registers(4)==7)
      AsyncTest.run(core(click),Seq(1,19),fresh(name+"-branches"))(_ => stimulus(expected,click))
    }
    test(s"$name reset aborts an outstanding fetch and restarts at reset PC") {
      AsyncTest.run(core(click),Seq(1,19),fresh(name+"-reset"))(_ => stimulus(Reference.run(known),click,resetPending=true))
    }
    test(s"$name reports illegal instructions alignment and memory faults") {
      val cases = Seq(
        Seq(0L), Seq(i(0x13,16,0,0,1)), Seq(i(0x13,1,0,16,1)), Seq(r(1,0,0,16)),
        Seq(r(1,0,0,0,1)), Seq(0x100fL), Seq(0x73L), Seq(jal(1,2)),
        Seq(i(0x03,1,2,0,1)), Seq(store(0,1,1,1)), Seq(i(0x03,1,2,0,1024)), Seq(store(0,1,1024,2)))
      cases.zipWithIndex.foreach { case(program,index) =>
        val expected = Reference.run(program,denied=Set(1024L))
        AsyncTest.run(core(click),Seq(19),fresh(s"$name-fault$index"))(_ => stimulus(expected,click))
      }
      AsyncTest.run(core(click),Seq(1),fresh(name+"-fetch-error"))(_ => stimulus(Reference.run(Seq(breakpoint),denied=Set(0L)),click))
    }
    test(s"$name retirement checker rejects a deliberately wrong architectural result") {
      val error = intercept[IllegalArgumentException] {
        AsyncTest.run(core(click),Seq(1),fresh(name+"-negative"))(_ => stimulus(Reference.run(known),click,corruptExpectation=true))
      }
      assert(error.getMessage.contains("RETIRE_MISMATCH_0"),error.getMessage)
    }
  }
}
