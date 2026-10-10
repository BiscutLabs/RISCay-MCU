// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdAdmissionFixture(p: SocParameters) extends BdCompletionFixture(p) {
  val pauseGrant=IO(Input(Bool())); val applicationReset=IO(Input(Bool()))
  val grantAvailable=IO(Output(Bool())); grantAvailable:=admissionGrant.out.valid
  val sleepEligible=IO(Output(Bool())); sleepEligible:=fabric.io.canSleep
  fabric.io.admissionGrant.valid:=admissionGrant.out.valid && !pauseGrant
  admissionGrant.out.ready:=fabric.io.admissionGrant.ready && !pauseGrant
  val observed=withClockAndReset(serviceClock,reset) { val a=RegNext(applicationReset,false.B); RegNext(a,false.B) }
  fabric.io.cpuReset:=systemReset || applicationReset
  fabric.io.cpuResetActive:=cpuResetActive || observed
}
class ClickAdmissionFixture(p: SocParameters) extends ClickCompletionFixture(p) {
  val pauseGrant=IO(Input(Bool())); val applicationReset=IO(Input(Bool()))
  val grantAvailable=IO(Output(Bool())); grantAvailable:=admissionGrant.out.valid
  val sleepEligible=IO(Output(Bool())); sleepEligible:=fabric.io.canSleep
  fabric.io.admissionGrant.valid:=admissionGrant.out.valid && !pauseGrant
  admissionGrant.out.ready:=fabric.io.admissionGrant.ready && !pauseGrant
  val observed=withClockAndReset(serviceClock,reset) { val a=RegNext(applicationReset,false.B); RegNext(a,false.B) }
  fabric.io.cpuReset:=systemReset || applicationReset
  fabric.io.cpuResetActive:=cpuResetActive || observed
}

/** Count actual service admissions independently of native credit phases. */
class AdmissionSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,1,Vector.empty,
    ApplicationProfile(1,1,"admission",Vector.empty,Vector.empty)),watchdogCycles=1000000,
    lowPower=Some(LowPowerParameters(stopServiceClock=false)))
  private val counter="""
    integer accepted=0;
    always @(posedge serviceClock) if(!reset && request_valid && request_ready) accepted=accepted+1;
  """
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture = if(click) new ClickAdmissionFixture(p) else new BdAdmissionFixture(p)
    val tasks=s"""
      reg replyPhase=0;
      task offer(input [1:0] op,input [31:0] addr,input [31:0] data); begin
        @(negedge serviceClock); request_valid=1; request_bits_operation=op;
        request_bits_address=addr; request_bits_data=data; request_bits_mask=15;
      end endtask
      task admitted; begin
        @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
        #1; request_valid=0; replyPhase=${if(click) "!replyPhase" else "1"};
        wait(cpuResponse_req == replyPhase);
      end endtask
      task retire; begin
        @(negedge serviceClock); cpuResponse_ack=replyPhase;
        ${if(click) "#500;" else "wait(!cpuResponse_req); #300; cpuResponse_ack=0;"}
      end endtask
      task write_mmio(input [31:0] addr,input [31:0] data); begin
        offer(2,addr,data); admitted();
        if(cpuResponse_bits_error) $$fatal(1,"ADMISSION_SETUP_WRITE");
        retire();
      end endtask
    """
    test(s"$name admission: GPIO arriving behind owned response survives a later MMIO clear") {
      ClockedSimulation.run(fixture,name+"-admission-clear-window","""
        referenceEnabled=0; gpioIn=0; #1000;
        write_mmio(32'h3000000c,32'hffffffff);
        offer(1,32'hdeadbeec,0); admitted();
        offer(2,32'h3000000c,32'hffffffff);
        repeat(3) @(negedge serviceClock); gpioIn=1;
        repeat(50) begin @(negedge serviceClock);
          if(request_ready || grantAvailable) $fatal(1,"CLEAR_ADMITTED_WITHOUT_CREDIT");
        end
        // Keep the clear continuously offered through the previous retirement.
        pauseGrant=1; retire(); @(negedge serviceClock); pauseGrant=0; admitted();
        if(cpuResponse_bits_error) $fatal(1,"CLEAR_REJECTED");
        retire(); offer(1,32'h3000000c,0); admitted();
        if(cpuResponse_bits_error || !cpuResponse_bits_data[2]) $fatal(1,"CREDIT_WINDOW_LOST_GPIO");
        retire();
      """,counter+tasks,referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
    test(s"$name admission: valid leased WAIT stays awake until credit returns then wakes on GPIO") {
      ClockedSimulation.run(fixture,name+"-admission-wait-window","""
        referenceEnabled=0; gpioIn=0; #1000;
        write_mmio(32'h30000038,4); write_mmio(32'h3000000c,32'hffffffff);
        write_mmio(32'h3000003c,30000);
        offer(1,32'hdeadbeec,0); admitted();
        offer(1,32'h30000010,0);
        repeat(50) begin @(negedge serviceClock);
          if(request_ready || grantAvailable || sleepEligible) $fatal(1,"WAIT_WITHOUT_CREDIT");
        end
        retire(); wait(grantAvailable); wait(sleepEligible);
        if(request_ready) $fatal(1,"WAIT_CONSUMED_LEASE_EARLY");
        @(negedge serviceClock); gpioIn=1; admitted();
        if(cpuResponse_bits_error || cpuResponse_bits_data != 4) $fatal(1,"WAIT_LOST_GPIO");
        retire(); offer(1,32'h3000003c,0); admitted();
        if(cpuResponse_bits_error || cpuResponse_bits_data != 0) $fatal(1,"WAIT_DID_NOT_CONSUME_LEASE");
        retire();
      """,counter+tasks,referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
    test(s"$name admission: stalled recycled credit and response return cannot admit extra work") {
      ClockedSimulation.run(fixture,name+"-admission-stalls",(0 until 12).map { n =>
        val phase=if(click) (n+1)%2 else 1
        s"""
          @(negedge serviceClock); pauseGrant=1; request_valid=1;
          request_bits_operation=1; request_bits_address=32'hdeadbeec; request_bits_mask=15;
          wait(grantAvailable);
          repeat(12) begin @(negedge serviceClock);
            if(request_ready || accepted != $n) $$fatal(1,"ADMISSION_IGNORED_GRANT_STALL");
          end
          pauseGrant=0;
          @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
          #1; request_valid=0;
          wait(cpuResponse_req == $phase);
          @(negedge serviceClock); request_valid=1;
          repeat(16) begin @(negedge serviceClock);
            if(request_ready || grantAvailable || accepted != ${n+1}) $$fatal(1,"ADMISSION_BEFORE_RETIREMENT");
            if(!cpuResponse_bits_error || cpuResponse_bits_data != 0) $$fatal(1,"ADMISSION_RESPONSE_CHANGED");
          end
          pauseGrant=1; cpuResponse_ack=$phase;
          ${if(click) "" else """
            wait(!cpuResponse_req);
            repeat(16) begin @(negedge serviceClock);
              if(grantAvailable || request_ready) $fatal(1,"ADMISSION_BEFORE_FULL_RESPONSE_RETURN");
            end
            cpuResponse_ack=0;
          """}
          wait(grantAvailable);
          repeat(16) begin @(negedge serviceClock);
            if(request_ready || accepted != ${n+1}) $$fatal(1,"ADMISSION_RECYCLE_DUPLICATED");
          end
          request_valid=0;
        """
      }.mkString("\n"),counter,deadlineNs=2000000)
    }
    test(s"$name admission: real HALT and repeated application resets restore exactly one seed") {
      ClockedSimulation.run(fixture,name+"-admission-halt",(0 until 8).map { n => s"""
        @(negedge serviceClock); request_valid=1; request_bits_operation=3;
        request_bits_address=0; request_bits_mask=15;
        @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
        #1; request_valid=0;
        @(negedge serviceClock); request_valid=1; request_bits_operation=1; request_bits_address=32'hdeadbeec;
        repeat(100) begin @(negedge serviceClock);
          if(request_ready || grantAvailable || cpuResponse_req || accepted != ${n+1}) $$fatal(1,"HALT_REPLENISHED_CREDIT");
        end
        request_valid=0; applicationReset=1;
        #3200; applicationReset=0;
        wait(grantAvailable); repeat(20) @(negedge serviceClock);
        if(accepted != ${n+1}) $$fatal(1,"RESET_REPLAYED_REQUEST");
      """ }.mkString("\n"),counter,deadlineNs=2000000)
    }
    test(s"$name admission: offered boot wait cannot authorize sleep before prior retirement") {
      ClockedSimulation.run(fixture,name+"-admission-sleep","""
        // Isolate admission from continuous housekeeping demand. Dedicated
        // sleep suites cover the running LF source and actual gate transitions.
        referenceEnabled=0;
        @(negedge serviceClock); request_valid=1; request_bits_operation=1;
        request_bits_address=32'hdeadbeec; request_bits_mask=15;
        @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
        #1; request_valid=0; wait(cpuResponse_req);
        @(negedge serviceClock); request_valid=1; request_bits_address=32'h30000000;
        repeat(50) begin @(negedge serviceClock);
          if(sleepEligible || request_ready || grantAvailable) $fatal(1,"BOOT_SLEEP_WITHOUT_CREDIT");
        end
        cpuResponse_ack=1;
      """+(if(click) "" else "wait(!cpuResponse_req); #300; cpuResponse_ack=0;\n")+"""
        wait(grantAvailable); wait(sleepEligible);
        if(accepted != 1 || request_ready) $fatal(1,"BOOT_WAIT_ADMITTED");
      """,counter,referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
  }
}
