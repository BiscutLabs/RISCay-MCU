// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chiselasync.protocol.{Channel,FourPhase,TwoPhase}
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdCompletionFixture(p: SocParameters) extends riscay.bd.FourPhasePlatform(p,x => new GenericBoard(x),false) {
  val request=IO(Flipped(Decoupled(new MemoryRequest)))
  val cpuResponse=fourPhaseOutput("cpu_response",new MemoryResponse)
  val planPhase=IO(Output(Bool())); planPhase:=completionPlan.out.req
  val grantAck=IO(Output(Bool())); grantAck:=admission.grant.ack
  fabric.io.request <> request; FourPhase.connect(cpuResponse,completion.response)
  trace:=0.U.asTypeOf(new Retirement); traceEvent:=false.B
  contract.clockedChannel("request",request,serviceClock,new Channel(new MemoryRequest,resetDomain),"input")
}
class ClickCompletionFixture(p: SocParameters) extends riscay.click.ClickPlatform(p,x => new GenericBoard(x),false) {
  val request=IO(Flipped(Decoupled(new MemoryRequest)))
  val cpuResponse=twoPhaseOutput("cpu_response",new MemoryResponse)
  val planPhase=IO(Output(Bool())); planPhase:=completionPlan.out.req
  val grantAck=IO(Output(Bool())); grantAck:=admission.grant.ack
  fabric.io.request <> request; TwoPhase.connect(cpuResponse,completion.response)
  trace:=0.U.asTypeOf(new Retirement); traceEvent:=false.B
  contract.clockedChannel("request",request,serviceClock,new Channel(new MemoryRequest,resetDomain),"input")
}
class CompletionSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,0,Vector.empty,
    ApplicationProfile(1,1,"completion",Vector.empty,Vector.empty)),watchdogCycles=1000000)
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name service completion progresses and retires without service edges after plan launch") {
      ClockedSimulation.run(if(click) new ClickCompletionFixture(p) else new BdCompletionFixture(p),name+"-completion-clock-stop",
        (0 until 12).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            @(negedge serviceClock); request_valid=1; request_bits_operation=1;
            request_bits_address=32'hdeadbeec; request_bits_data=0; request_bits_mask=15;
            @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
            #1; request_valid=0;
            wait(planPhase == $phase); #0.001; clockEnabled=0;
            ${if(click) "" else "if(!grantAck) $fatal(1,\"GRANT_RETURN_ALREADY_FINISHED\");"}
            if(cpuResponse_req == $phase) $$fatal(1,"COMPLETION_CLOCK_STOP_TOO_LATE");
            wait(cpuResponse_req == $phase); #500;
            if(!cpuResponse_bits_error || cpuResponse_bits_data != 0) $$fatal(1,"COMPLETION_CLOCKLESS_DATA");
            if(request_ready) $$fatal(1,"COMPLETION_PREMATURE_REUSE");
            cpuResponse_ack=$phase;
            ${if(click) "#500;" else "wait(!cpuResponse_req); #500; cpuResponse_ack=0;"}
            clockEnabled=1;
            repeat(20) @(negedge serviceClock);
          """
        }.mkString("\n"))
    }
  }
}
