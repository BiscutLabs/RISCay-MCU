// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.AsyncModule
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.bd.FourPhaseCore
import riscay.click.ClickCore

class CoreSpec extends AnyFunSuite {
  import Assembly._
  import CorePrograms._
  private def fresh(name: String) = {
    val root = Paths.get("build/core-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root, name)
  }
  private def hex(x: Long) = "32'h" + java.lang.Long.toHexString(x & 0xffffffffL)
  private def core(click: Boolean): AsyncModule = if(click) new ClickCore else new FourPhaseCore

  private def bus(a: Reference.Access, click: Boolean, number: Int, fastest: Boolean): String = {
    val arrival = if(click) "wait(request_req != request_ack);" else "wait(request_req);"
    val pause = if(fastest) 2L else 100000000L
    val release = if(click) "request_ack=request_req; #2;" else s"request_ack=1; wait(!request_req); #$pause; request_ack=0; #2;"
    val reply = if(a.op == 3) "" else s"""
      response_bits_data=${hex(a.response)}; response_bits_error=${if(a.error) 1 else 0};
      #${if(fastest) 2L else 100000000L + (number % 5)*19000000L};
      ${if(click) "response_req=~response_req; wait(response_ack == response_req); #2;" else s"response_req=1; wait(response_ack); #$pause; response_req=0; wait(!response_ack); #2;"}
    """
    s"""
      $arrival
      #${if(fastest) 2L else 70000000L + (number % 7)*13000000L};
      if(request_bits_operation !== 2'd${a.op} || request_bits_address !== ${hex(a.address)} ||
         request_bits_data !== ${hex(a.data)} || request_bits_mask !== 4'd${a.mask})
        $$fatal(1,"BUS_MISMATCH_${number} op=%d address=%h data=%h mask=%h",request_bits_operation,request_bits_address,request_bits_data,request_bits_mask);
      ${if(fastest && a.op != 3) s"fork begin $release end begin $reply end join" else s"$release\n$reply"}
    """
  }

  private def stimulus(result: Reference.Result, click: Boolean, resetPending: Boolean = false,
      corruptExpectation: Boolean = false, fastest: Boolean = false, guardMonitor: String = ""): String = {
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
      $guardMonitor
      $pending
      ${if(click) "start=1;" else ""}
      fork
        begin
          ${result.accesses.zipWithIndex.map { case(a,i) => bus(a,click,i,fastest) }.mkString("\n")}
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

  test("independent oracle agrees with hand-calculated signed, unsigned and x0 results") {
    val r = Reference.run(known)
    assert(r.registers.take(7) == Vector(0L,0xffffffffL,1L,0L,1L,0L,7L))
    assert(r.traces.last.cause == 3)
  }

  private def writebackMonitor(directory: Path, click: Boolean, bypass: Boolean = false): String = {
    val design = ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    def path(value: ujson.Value) = "dut." + value("rtl_path").str.split('.').drop(1).mkString(".")
    val guard = path(design("primitives").arr.find(_("id").str == "request_guard").get)
    val rf = design("children").arr.find(_("id").str == "register_file").get("contract")
    val checks = (1 to 15).map { i =>
      val bank = path(rf("primitives").arr.find(_("id").str == s"x$i").get)
      val select = path(rf("primitives").arr.find(_("id").str == s"select$i").get)
      s"if($select.rising && $bank.q !== $bank.d) $$fatal(1,\"WRITEBACK_FORWARDED_EARLY_$i\");"
    }.mkString("\n")
    s"""fork begin
      forever begin
        @(${if(click) "" else "posedge "}$guard.q); #2;
        if(!reset) begin $checks end
      end
    end join_none
    ${if(bypass) s"force $guard.q = $guard.a;" else ""}"""
  }


  // Physical trace projection is checked against the same independent memory
  // history as the debug core. Signature stores make every RV32E register visible.
  private def busOnly(result: Reference.Result, fastest: Boolean, retainTrace: Boolean,
      resetLoad: Boolean = false): String = {
    val zeroTrace = if(retainTrace) "" else """
      if({traceEvent,trace_valid,trace_pc,trace_instruction,trace_rd,trace_data,
          trace_writeRegister,trace_trap,trace_cause} !== 0) $fatal(1,"PHYSICAL_TRACE_NOT_ZERO");
    """
    val pending = if(!resetLoad) "" else {
      val index=result.accesses.indexWhere(_.op==1)
      require(index>=0,"RESET_TEST_NEEDS_LOAD")
      val a=result.accesses(index)
      s"""
        ${result.accesses.take(index).zipWithIndex.map { case(a,i) => bus(a,false,i,fastest) }.mkString("\n")}
        wait(request_req); #2;
        if(request_bits_operation!==2'd1 || request_bits_address!==${hex(a.address)} ||
           request_bits_data!==${hex(a.data)} || request_bits_mask!==4'd${a.mask})
          $$fatal(1,"RESET_LOAD_NOT_ACCEPTED");
        request_ack=1; wait(!request_req); #100000000; request_ack=0;
        #300000000;
        reset=1; request_ack=0; response_req=0; response_bits_data=0; response_bits_error=0;
        #1000000000; reset=0; #1000000000;
      """
    }
    s"""begin
      $pending
      ${result.accesses.zipWithIndex.map { case(a,i) => bus(a,false,i,fastest)+zeroTrace }.mkString("\n")}
      #2000000000;
      if(request_req) $$fatal(1,"PROJECTED_CORE_HALT_NOT_QUIESCENT");
      $zeroTrace
      $$display("PROJECTED_CORE_MEMORY_PASS:${result.accesses.size}");
    end"""
  }

  test("BD projected physical core matches debug memory histories with full register signatures") {
    val signatures=(0 to 15).map(r => store(0,r,1024+4*r,2))
    val programs=Seq(arithmetic.dropRight(1) ++ signatures ++ Seq(breakpoint),
      memoryAndControl.dropRight(1) ++ signatures ++ Seq(breakpoint))
    for((program,index) <- programs.zipWithIndex; retain <- Seq(true,false); fastest <- Seq(false,true)) {
      val expected=Reference.run(program)
      AsyncTest.run(new FourPhaseCore(retainTrace=retain),Seq(1,19),
        fresh(s"bd-projected-$index-$retain-$fastest"))(_ => busOnly(expected,fastest,retain))
    }
  }
  test("BD projected physical core retains fault and accepted-load reset behavior") {
    val faults=Seq((Seq(breakpoint),Set(0L)),
      (Seq(i(0x03,1,2,0,1024)),Set(1024L)),(Seq(store(0,1,1024,2)),Set(1024L)))
    for(((program,denied),index) <- faults.zipWithIndex) {
      AsyncTest.run(new FourPhaseCore(retainTrace=false),Seq(1,19),fresh(s"bd-projected-fault$index"))(
        _ => busOnly(Reference.run(program,denied=denied),fastest=true,retainTrace=false))
    }
    val resetProgram=(0 to 15).map(r => store(0,r,1024+4*r,2)) ++ memoryAndControl
    for(retain <- Seq(true,false)) {
      AsyncTest.run(new FourPhaseCore(retainTrace=retain),Seq(1,19),fresh(s"bd-projected-reset-$retain"))(
        _ => busOnly(Reference.run(resetProgram),fastest=false,retainTrace=retain,resetLoad=true))
    }
  }

  for(click <- Seq(false,true)) {
    val name = if(click) "click" else "four-phase"
    test(s"$name minimum-latency memory and writeback-before-forwarding hold across cell corners") {
      val directory = fresh(name+"-fast-memory")
      val expected = Reference.run(arithmetic.dropRight(1) ++ memoryAndControl)
      AsyncTest.run(core(click),Seq(1,2,19,81),directory) { _ =>
        stimulus(expected,click,fastest=true,guardMonitor=writebackMonitor(directory,click))
      }
    }
    test(s"$name writeback timing checker rejects a bypassed request guard") {
      val directory = fresh(name+"-writeback-negative")
      val error = intercept[IllegalArgumentException] {
        AsyncTest.run(core(click),Seq(1),directory) { _ =>
          stimulus(Reference.run(known),click,fastest=true,
            guardMonitor=writebackMonitor(directory,click,bypass=true))
        }
      }
      assert(error.getMessage.contains("WRITEBACK_FORWARDED_EARLY"),error.getMessage)
    }
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
