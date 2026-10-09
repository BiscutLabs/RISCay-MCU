// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.bd.FourPhaseSoc
import riscay.click.ClickSoc
import riscay.profiles._
import java.nio.file.{Files, Paths}
import java.util.zip.CRC32

/** Activity evidence only: native timing models, not a mapped timing/power test.
  * Enabled board policy is an estimate fixture, never a deployment qualification.
  */
class PhysicalEstimateSpec extends AnyFunSuite {
  import Assembly._
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "four-phase"
    test(s"$name full-capacity GF180 estimate has bounded maintenance, ADC and firmware wakes") {
      val p=SocParameters(Groundlark.configuration,staleMs=3000,watchdogCycles=32,watchdogHoldCycles=2,
        adc=Some(AdcParameters(intervalCycles=10000000)),lowPower=Some(LowPowerParameters.gf180Slow))
      val policy=PowerPolicy(enabled=true)
      val top=if(click) () => new ClickSoc(p,x => new GroundlarkSupervisor(x,policy))
        else () => new FourPhaseSoc(p,x => new GroundlarkSupervisor(x,policy))
      // Each iteration: wait for a deadline, acknowledge consumed events, read GPIO,
      // perform 32 integer additions, store the result, renew the lease and park.
      val setup=Seq(0x300000b7L,0x20000137L,0x574451b7L,i(0x13,3,0,3,-185),
        i(0x13,4,0,0,2),store(1,4,56,2),i(0x13,6,0,0,0))
      val park=Seq(i(3,4,2,1,4),i(0x13,4,0,4,1000),store(1,4,8,2),
        i(0x13,4,0,0,2000),store(1,4,60,2),store(1,3,32,2),i(3,5,2,1,16))
      val work=Seq(store(1,5,12,2),i(3,4,2,1,20)) ++ Seq.fill(32)(i(0x13,6,0,6,1)) ++ Seq(store(2,6,0,2))
      val program=setup ++ park ++ work ++ Seq(jal(0,-4*(park.size+work.size)))
      val crc=new CRC32
      program.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b)) & 255).toInt)))
      val body=s"""
        #1000000; wait(!serviceClockEnable); phase=1;
        // Ten actual LF ticks cover maintenance-only and autonomous ADC wakes.
        repeat(10) @(posedge watchdogClock);
        wait(!serviceClockEnable); phase=0;
        begin_image(${program.size*4},0,32'h${crc.getValue.toHexString},32'h00010000);
        ${program.zipWithIndex.map { case(w,n) => s"put_word(${4*n},32'h${w.toHexString});" }.mkString("\n")}
        command(3); command(6);
        wait(!serviceClockEnable); phase=2;
        repeat(20) @(posedge watchdogClock);
        wait(!serviceClockEnable); #100;
        if(!programmed || !locked || resetReason || firmwareWakes<2 || adcWakes<2 || idleWakes<8)
          $$fatal(1,"MISSING_ESTIMATE_ACTIVITY fw=%d adc=%d idle=%d",firmwareWakes,adcWakes,idleWakes);
        $$display("ESTIMATE_ACTIVITY_COMPLETE");
      """
      val monitor=s"""
        integer phase=0, fastEdges=0, workEdges=0, retired=0, conversions=0;
        integer idleWakes=0, adcWakes=0, firmwareWakes=0, measured=0;
        real wakeAt; reg seen=0; reg [15:0] adcShift;
        always @(negedge adcCsN) begin
          adcShift={4'b0,12'd2200}; adcMiso=adcShift[15]; conversions=conversions+1;
        end
        always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1; adcMiso=adcShift[15]; end
        always @(posedge serviceClock) fastEdges=fastEdges+1;
        // This POR-owned bridge uses the gated work clock in both variants.
        always @(posedge dut.soc.ca_child_control_command_bridge.clock) workEdges=workEdges+1;
        initial forever begin
          ${if(click) "wait(traceEvent != seen); seen=traceEvent;" else "wait(traceEvent);"}
          if(trace_valid && trace_pc>=32'h10000000) begin
            retired=retired+1;
            if(trace_trap) $$fatal(1,"ESTIMATE_FIRMWARE_TRAP");
          end
          ${if(click) "#0.001;" else "wait(!traceEvent);"}
        end
        always @(posedge serviceClockEnable) begin
          fastEdges=0; workEdges=0; retired=0; conversions=0; wakeAt=$$realtime; measured=phase;
        end
        always @(negedge serviceClockEnable) if(measured>0) begin
          if(fastEdges<10 || workEdges<5 || fastEdges>10000) $$fatal(1,"INVALID_WAKE_ACTIVITY");
          if(retired>0) firmwareWakes=firmwareWakes+1;
          else if(conversions>0) adcWakes=adcWakes+1; else idleWakes=idleWakes+1;
          $$display("WAKE,%0d,%0d,%0d,%0d,%0d,%0.3f",measured,fastEdges,workEdges,retired,conversions,$$realtime-wakeAt);
        end
      """
      val dir=ClockedSimulation.run(top(),s"$name-physical-estimate",body,monitor,
        referenceHalfPeriodNs=64677286,onChipOscillator=true,chipParameters=p.lowPower.get,
        serviceStartupNs=64,serviceModelHz=12000000,deadlineNs=6000000000L,processTimeoutSeconds=300)
      val log=Files.readString(dir.resolve("simulation.log"))
      assert(log.contains("ESTIMATE_ACTIVITY_COMPLETE"))
      Files.createDirectories(Paths.get("build/gf180-estimate"))
      Files.writeString(Paths.get(s"build/gf180-estimate/$name-export.txt"),dir.toString+"\n")
    }
  }
}
