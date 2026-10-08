// SPDX-License-Identifier: Apache-2.0
package riscay.physical

import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.bd.FourPhaseCore
import riscay.click.ClickCore

class PhysicalTimingSpec extends AnyFunSuite {
  for(click <- Seq(false,true)) test(s"physical timing policy, click=$click: dependent writes with fastest memory") {
    val root=Paths.get("build/physical-policy-tests"); Files.createDirectories(root)
    val out=Files.createTempDirectory(root,if(click) "click" else "bd")
    val program=Seq("00700093","00508113","002081b3","00100073")
    val arrival=if(click) "wait(request_req != request_ack); #2;" else "wait(request_req); #2;"
    val accept=if(click) "request_ack=request_req; #2;" else "request_ack=1; wait(!request_req); #2; request_ack=0; #2;"
    val fetches=program.zipWithIndex.map { case(word,i) => s"""
      $arrival
      if(request_bits_operation != 0 || request_bits_address != ${i*4} || request_bits_mask != 15)
        $$fatal(1,"PHYSICAL_FETCH_$i");
      fork
        begin $accept end
        begin
          response_bits_data=32'h$word; response_bits_error=0; #2;
          ${if(click) "response_req=~response_req; wait(response_ack==response_req); #2;" else
            "response_req=1; wait(response_ack); #2; response_req=0; wait(!response_ack); #2;"}
        end
      join
    """ }.mkString("\n")
    def gen = if(click) new ClickCore(timing=PhysicalTiming.click,executeData=PhysicalTiming.executeData)
      else new FourPhaseCore(timing=PhysicalTiming.bd(20),executeTiming=PhysicalTiming.bd(180))
    AsyncTest.run(gen,Seq(1,19),out) { _ => s"""
      begin
        integer retired; reg seen; retired=0; seen=0;
        ${if(click) "start=1;" else ""}
        fork
          begin
            $fetches
            $arrival
            if(request_bits_operation != 3) $$fatal(1,"PHYSICAL_NO_HALT");
            $accept
          end
          begin
            while(retired<4) begin
              ${if(click) "wait(traceEvent != seen); seen=traceEvent;" else "wait(traceEvent);"}
              if(trace_valid) begin
                if(trace_pc != retired*4) $$fatal(1,"PHYSICAL_RETIRE_PC");
                case(retired)
                  0: if(trace_rd!=1 || trace_data!=7 || trace_trap) $$fatal(1,"PHYSICAL_X1");
                  1: if(trace_rd!=2 || trace_data!=12 || trace_trap) $$fatal(1,"PHYSICAL_X2");
                  2: if(trace_rd!=3 || trace_data!=19 || trace_trap) $$fatal(1,"PHYSICAL_X3");
                  3: if(!trace_trap || trace_cause!=3) $$fatal(1,"PHYSICAL_EBREAK");
                endcase
                retired=retired+1;
              end
              ${if(click) "#1;" else "wait(!traceEvent);"}
            end
          end
        join
        #2000000000;
        if(retired!=4) $$fatal(1,"PHYSICAL_NO_ACTIVITY");
        $$display("PHYSICAL_POLICY_ACTIVITY retirements=%d",retired);
      end
    """ }
  }
}
