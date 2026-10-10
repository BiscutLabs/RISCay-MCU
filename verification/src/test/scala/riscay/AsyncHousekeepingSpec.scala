// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Explicit architectural cases; no production transition helper in the oracle. */
class AsyncHousekeepingSpec extends AnyFunSuite {
  private type Fields=Map[String,Long]
  private case class Step(command: Fields,expected: Fields)
  private val p=SocParameters(McuConfiguration(8,8,0,Vector(MeasurementChannel(0,"sample",1,0)),
    ApplicationProfile(1,1,"housekeeping",Vector.empty,Vector.empty)),
    adc=Some(AdcParameters(halfPeriodCycles=2,intervalCycles=100000)),lowPower=Some(LowPowerParameters()))
  private val fields=Seq("timeValid","target","single","elapsed_0","elapsed_1","elapsed_2","elapsedOverflow",
    "resetApplication","started","parked","adcBusy","discard","write","offset","data",
    "waitAccepted","periodUpdate","period","cpuCompletion")
  private val defaults=Map("started"->1L,"adcBusy"->1L)
  private def time(n: Long): Fields=Map("timeValid"->1L,"target"->n,"single"->1L,
    "elapsed_0"->n,"elapsed_1"->n,"elapsed_2"->n)
  private def write(offset: Long,value: Long): Fields=Map("write"->1L,"offset"->offset,"data"->value,"cpuCompletion"->1L)
  private def state(values: (String,Long)*): Fields=values.map { case(k,v) => "state_"+k->v }.toMap
  private def fresh(name: String) = {
    val root=Paths.get("build/async-housekeeping-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickHousekeeping(p,new ResetDomain("root"))
    else new riscay.bd.FourPhaseHousekeeping(p,new ResetDomain("root"))
  private def campaign(click: Boolean,steps: Seq[Step]): String = {
    val source=steps.zipWithIndex.map { case(s,i) =>
      val phase=if(click) (i+1)%2 else 1
      val values=defaults++s.command
      val data=fields.map(f => s"command_bits_$f=32'h${values.getOrElse(f,0L).toHexString};").mkString("\n")
      s"""$data #${(i%3+1)*31000000L}; command_req=$phase; wait(command_ack == $phase); #2;
        ${if(click) "" else "command_req=0; wait(!command_ack); #2;"}
      """
    }.mkString("\n")
    val sink=steps.zipWithIndex.map { case(s,i) =>
      val phase=if(click) (i+1)%2 else 1
      val checks=s.expected.toSeq.sortBy(_._1).map { case(k,v) =>
        s"if(reply_bits_$k !== 32'h${v.toHexString}) $$fatal(1,\"HOUSEKEEPING_${i}_$k actual=%h\",reply_bits_$k);"
      }.mkString("\n")
      s"""wait(reply_req == $phase); #2; $checks
        repeat(5) begin #${(i%5+1)*41000000L}; $checks end
        reply_ack=$phase;
        ${if(click) "#2;" else "wait(!reply_req); #37000000; reply_ack=0; #2;"}
      """
    }.mkString("\n")
    s"fork begin $source end begin $sink end join #1000000000;"
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native housekeeping: ordered lease/deadline writes, reset and wrapping elapsed time") {
      val steps=Seq(
        Step(write(56,4),state("wakeMask"->4)),
        Step(write(60,5),state("lease"->5)++Map("leaseExpired"->0L)),
        Step(time(3),state("now"->3,"lease"->2)),
        Step(time(2)++write(60,9),state("now"->5,"lease"->9)++Map("leaseExpired"->1L)),
        Step(time(4)++Map("waitAccepted"->1L),state("now"->9,"lease"->0)),
        Step(write(8,13),state("deadline"->13,"armed"->1)++Map("due"->0L)),
        Step(time(4)++write(8,100),state("now"->13,"deadline"->100,"armed"->1)++Map("due"->0L)),
        Step(time(87),state("now"->100,"armed"->0)++Map("due"->1L)),
        Step(time(1),state("now"->101)++Map("due"->0L)),
        Step(write(8,99),state("armed"->0)++Map("due"->1L)),
        Step(write(8,200),state("armed"->1)),
        Step(time(5)++Map("resetApplication"->1L),state("now"->106,"boardNow"->106,"deadline"->0,
          "armed"->0,"lease"->0,"wakeMask"->15,"period"->10)++Map("due"->0L,"leaseExpired"->0L)),
        Step(write(60,3),state("lease"->3)),
        Step(write(8,120),state("armed"->1)),
        Step(Map("timeValid"->1L,"elapsedOverflow"->1L,"elapsed_2"->0xffffffffL),
          state("now"->106,"lease"->0)++Map("tick"->1L,"leaseExpired"->1L,"due"->1L,"elapsed_2"->0xffffffffL)),
        Step(write(8,120),state("armed"->1)),
        Step(time(0xfffffffeL),state("now"->104,"armed"->0)++Map("due"->1L)),
        Step(write(8,120),state("armed"->1)),
        Step(time(0xffffffffL)++write(8,200),state("now"->103,"armed"->1)++Map("due"->0L)),
        Step(time(3),state("now"->106)))
      AsyncTest.run(top(click),1L to 16L,fresh(name+"-timers")) { _ =>
        s"${if(click) "start=1;" else ""} ${campaign(click,steps)} if(delivered_reply != ${steps.size}) $$fatal(1,\"HOUSEKEEPING_EXACTLY_ONCE\");"
      }
    }
    test(s"$name native housekeeping: discard retry, cadence coalescing and simultaneous period application/write") {
      val steps=Seq(
        Step(Map("adcBusy"->0L),state("requested"->0,"countdown"->9)++Map("startAdc"->1L)),
        Step(Map("discard"->1L),state("requested"->1)++Map("startAdc"->0L)),
        Step(time(4),state("countdown"->5,"requested"->1)),
        Step(Map("adcBusy"->0L),state("requested"->0)++Map("startAdc"->1L)),
        Step(time(6),state("countdown"->9,"requested"->1)),
        Step(Map("periodUpdate"->1L,"period"->6L),state("nextPeriod"->6,"periodPending"->1,"period"->10)),
        Step(Map("adcBusy"->0L),state("requested"->0)++Map("startAdc"->1L)),
        Step(time(1)++Map("adcBusy"->0L,"periodUpdate"->1L,"period"->8L),
          state("period"->6,"nextPeriod"->8,"periodPending"->1,"countdown"->5,"requested"->1)++Map("startAdc"->0L)),
        Step(Map("adcBusy"->0L),state("requested"->0)++Map("startAdc"->1L)),
        Step(time(1),state("period"->6,"countdown"->4,"periodPending"->1)),
        Step(time(1)++Map("adcBusy"->0L),state("period"->8,"countdown"->7,"requested"->1,"periodPending"->0)),
        Step(Map("resetApplication"->1L),state("period"->8,"requested"->1,"lease"->0)),
        Step(time(80),state("period"->8,"requested"->1,"countdown"->7)))
      AsyncTest.run(top(click),1L to 16L,fresh(name+"-cadence")) { _ =>
        s"${if(click) "start=1;" else ""} ${campaign(click,steps)}"
      }
    }
    test(s"$name native housekeeping: kick policy uses finite native lease and observed application progress") {
      val steps=Seq(
        Step(write(32,0x57444f47L),Map("kick"->1L)),
        Step(Map.empty,Map("kick"->0L)),
        Step(write(60,2),state("lease"->2)++Map("kick"->0L)),
        Step(time(2)++Map("parked"->1L),state("lease"->0)++Map("kick"->1L,"leaseExpired"->1L)),
        Step(time(1)++Map("parked"->1L),Map("kick"->0L)),
        Step(Map("resetApplication"->1L),state("lease"->0)++Map("kick"->0L)),
        Step(time(1)++Map("started"->0L),Map("kick"->1L)),
        Step(write(60,10),state("lease"->10)++Map("kick"->0L)),
        Step(time(1),state("lease"->9)++Map("kick"->0L)))
      AsyncTest.run(top(click),1L to 16L,fresh(name+"-watchdog")) { _ =>
        s"${if(click) "start=1;" else ""} ${campaign(click,steps)}"
      }
    }
    test(s"$name native housekeeping: POR cancels admission, transform and stalled publication") {
      for(abort <- 0 until 3) {
        val first=Step(write(60,77),state("lease"->77))
        val after=Seq(Step(Map.empty,state("now"->0,"lease"->0,"wakeMask"->15,"period"->10,"requested"->1)))
        AsyncTest.run(top(click),Seq(1L,7L,19L),fresh(name+s"-por-$abort")) { _ => s"""
          ${if(click) "start=1;" else ""}
          ${fields.map(f => s"command_bits_$f=32'h${(defaults++first.command).getOrElse(f,0L).toHexString};").mkString("\n")}
          command_req=1;
          ${Seq("wait(command_ack);","wait(dut.ca_child_update.in_req);","wait(reply_req);")(abort)}
          #1; reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
          #1000000000; reset=0; #1000000000;
          if(reply_req || command_ack) $$fatal(1,"HOUSEKEEPING_POR_REPLAY");
          ${if(click) "start=1;" else ""} ${campaign(click,after)}
        """ }
      }
    }
  }
}
