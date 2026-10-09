// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.profiles.PowerPolicy

/** Scripted safety scenarios with explicit expected states, without a clock or
  * production transition helper in the oracle. Every reply is backpressured.
  */
class AsyncSupervisorSpec extends AnyFunSuite {
  private type Fields = Map[String,Long]
  private case class Step(command: Fields, expected: Fields)
  private val fields=Seq("now","tick","elapsedUpper","observationMs","firstObservationMs",
    "observationGap","gpio","gpioChanged","power","shutdown","capture_seen","capture_count",
    "capture_hadValid","capture_valid","capture_calibrated","capture_value","capture_tailAge",
    "capture_firstAge","capture_maximumGap","capture_minimum","capture_maximum","capture_failed")
  private def cmd(now: Long, ms: Long = 1, gpio: Long = 4, power: Long = 0): Fields =
    Map("now"->now,"tick"->1L,"observationMs"->ms,"firstObservationMs"->ms,"gpio"->gpio,"power"->power)
  private def sample(value: Long): Fields = Map("capture_seen"->1L,"capture_count"->1L,
    "capture_hadValid"->1L,"capture_valid"->1L,"capture_calibrated"->1L,"capture_value"->value,
    "capture_minimum"->value,"capture_maximum"->value)
  private def boot(base: Long = 0): Seq[Step] = Seq(
    Step(cmd(base)++sample(13000),Map("mode"->0L,"sample_sequence"->1L)),
    Step(cmd(base+1000,1000),Map("mode"->0L,"counts_2"->0L)),
    Step(cmd(base+2000,1000),Map("mode"->0L,"counts_2"->1000L)),
    Step(cmd(base+30000),Map("mode"->1L,"waitRun"->1L,"qualified"->0L)))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-supervisor-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def top(click: Boolean, enabled: Boolean = true): AsyncModule = {
    val p=SocParameters(riscay.profiles.Groundlark.configuration,staleMs=60000)
    if(click) new riscay.click.ClickSupervisor(p,PowerPolicy(enabled=enabled),new ResetDomain("root"))
    else new riscay.bd.FourPhaseSupervisor(p,PowerPolicy(enabled=enabled),new ResetDomain("root"))
  }
  private def campaign(click: Boolean, steps: Seq[Step]): String = {
    val source=steps.zipWithIndex.map { case(s,i) =>
      val phase=if(click) (i+1)%2 else 1
      val data=fields.map(f => s"command_bits_$f=32'h${s.command.getOrElse(f,0L).toHexString};").mkString("\n")
      s"""$data #2; command_req=$phase; wait(command_ack == $phase); #2;
        ${if(click) "" else "command_req=0; wait(!command_ack); #2;"}
      """
    }.mkString("\n")
    val sink=steps.zipWithIndex.map { case(s,i) =>
      val phase=if(click) (i+1)%2 else 1
      val checks=s.expected.toSeq.sortBy(_._1).map { case(k,v) =>
        s"if(reply_bits_$k !== 32'h${v.toHexString}) $$fatal(1,\"SUPERVISOR_${i}_$k actual=%h\",reply_bits_$k);"
      }.mkString("\n")
      s"""wait(reply_req == $phase); #2; $checks
        #${(i%5+1)*41000000L}; $checks reply_ack=$phase;
        ${if(click) "#2;" else "wait(!reply_req); #37000000; reply_ack=0; #2;"}
      """
    }.mkString("\n")
    s"fork begin $source end begin $sink end join #1000000000;"
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native supervisor: current-boot ACK and physical publication dwell under backpressure") {
      val steps=boot() ++ Seq(
        Step(cmd(50000,20000),Map("mode"->1L,"waitRun"->1L,"qualified"->0L,"counts_0"->0L)),
        Step(cmd(50001,power=1),Map("waitRun"->0L,"counts_0"->0L)),
        Step(cmd(50021,20,power=1),Map("counts_0"->0L,"qualified"->0L)),
        Step(cmd(50041,20,power=1),Map("counts_0"->20L,"qualified"->0L)),
        Step(cmd(50042,power=1),Map("qualified"->1L)),
        Step(cmd(50043,gpio=0,power=1)++Map("gpioChanged"->4L),Map("counts_1"->0L,"mode"->1L)),
        Step(cmd(50063,20,gpio=0,power=1),Map("counts_1"->0L)),
        Step(cmd(50083,20,gpio=0,power=1),Map("counts_1"->20L)),
        Step(cmd(50084,gpio=0,power=1),Map("mode"->0L,"waitOff"->1L,"fault"->5L)),
        Step(cmd(100000,power=1),Map("mode"->0L,"waitOff"->1L)),
        Step(cmd(100001)++Map("gpioChanged"->4L),Map("offAt"->100001L,"waitOff"->0L)),
        Step(cmd(100002),Map("mode"->0L)),
        Step(cmd(101002,1000),Map("counts_2"->1000L)),
        Step(cmd(130000),Map("mode"->0L)),
        Step(cmd(130001),Map("mode"->1L,"waitRun"->1L)))
      AsyncTest.run(top(click),1L to 16L,fresh(name+"-ack")) { _ =>
        s"${if(click) "start=1;" else ""} ${campaign(click,steps)} if(delivered_reply != ${steps.size}) $$fatal(1,\"SUPERVISOR_EXACTLY_ONCE\");"
      }
    }
    test(s"$name native supervisor: bad history, projection-qualified shutdown timeout and three-strike latch") {
      val steps=collection.mutable.ArrayBuffer.empty[Step]
      steps ++= boot()
      for(attempt <- 0 until 3) {
        val b=attempt*100000L
        steps += Step(cmd(b+30001,power=1),Map("waitRun"->0L))
        // Last sample is good, but a failed acquisition in the batch must survive.
        steps += Step(cmd(b+30002,power=1)++sample(13000)++Map("capture_failed"->1L),Map("mode"->2L,"fault"->3L,"waitShutdown"->1L))
        steps += Step(cmd(b+50000,power=1),Map("mode"->2L,"timeouts"->attempt.toLong))
        steps += Step(cmd(b+50001,power=1)++Map("shutdown"->1L),Map("shutdownAt"->(b+50001),"waitShutdown"->0L))
        steps += Step(cmd(b+60000,power=1)++Map("shutdown"->1L),Map("mode"->2L))
        steps += Step(cmd(b+60001,power=1)++Map("shutdown"->1L),Map("mode"->(if(attempt==2) 3L else 0L),"timeouts"->(attempt+1L),"fault"->4L))
        if(attempt<2) {
          steps += Step(cmd(b+70000),Map("offAt"->(b+70000),"mode"->0L))
          steps += Step(cmd(b+71000,1000),Map("mode"->0L))
          steps += Step(cmd(b+130000),Map("mode"->1L,"waitRun"->1L))
        }
      }
      steps += Step(cmd(0xffffffffL,100000)++sample(18000),Map("mode"->3L,"timeouts"->3L,"fault"->4L))
      AsyncTest.run(top(click),Seq(1L,2L,7L,19L),fresh(name+"-timeouts")) { _ =>
        s"${if(click) "start=1;" else ""} ${campaign(click,steps.toSeq)}"
      }
    }
    test(s"$name native supervisor: freshness boundary, GPIO history and observation gaps cancel credit") {
      val steps=boot().take(3) ++ Seq(
        Step(cmd(2001)++sample(13000)++Map("capture_firstAge"->60000L),Map("mode"->0L,"counts_2"->0L,"observed_2"->0L)),
        Step(cmd(2002,1000),Map("counts_2"->0L)),
        Step(cmd(3002,1000),Map("counts_2"->1000L)),
        Step(cmd(3003)++sample(13000)++Map("capture_count"->2L,"capture_maximumGap"->60000L),Map("counts_2"->0L)),
        Step(cmd(3004,1000),Map("counts_2"->0L)),
        Step(cmd(4004,1000),Map("counts_2"->1000L)),
        Step(cmd(4005)++Map("gpioChanged"->4L),Map("counts_0"->0L,"counts_2"->0L)),
        Step(cmd(4006,1000),Map("counts_2"->0L)),
        Step(cmd(5006,1000),Map("counts_2"->1000L)),
        Step(cmd(5007,2000)++Map("observationGap"->1L),Map("counts_2"->0L)),
        Step(cmd(5008)++Map("elapsedUpper"->0xffffffffL),Map("sample_age"->0xffffffffL)),
        Step(cmd(5009)++Map("elapsedUpper"->1L),Map("sample_age"->0xffffffffL)))
      AsyncTest.run(top(click),Seq(1L,2L,19L),fresh(name+"-history")) { _ =>
        s"${if(click) "start=1;" else ""} ${campaign(click,steps)}"
      }
    }
    test(s"$name native supervisor: non-tick hazards survive recovery and low voltage needs continuous confirmation") {
      val split=boot() ++ Seq(
        Step(cmd(30001,power=1),Map("waitRun"->0L)),
        Step(cmd(30002,power=1)++Map("tick"->0L,"capture_seen"->1L,"capture_count"->1L,"capture_failed"->1L),
          Map("mode"->1L,"sensingFault"->1L)),
        Step(cmd(30002,power=1)++sample(13000)++Map("tick"->0L),Map("mode"->1L,"sensingFault"->1L)),
        Step(cmd(30003,power=1),Map("mode"->2L,"fault"->3L)))
      val low=boot() ++ Seq(
        Step(cmd(30001,power=1),Map("waitRun"->0L)),
        Step(cmd(30002,power=1)++sample(9000),Map("mode"->1L,"counts_3"->0L)),
        Step(cmd(30003,power=1),Map("mode"->1L,"counts_3"->0L)),
        Step(cmd(31002,999,power=1),Map("mode"->1L,"counts_3"->999L)),
        // Brief recovery clears prior low-voltage credit even without a tick.
        Step(cmd(31002,power=1)++sample(13000)++Map("tick"->0L),Map("counts_3"->0L)),
        Step(cmd(31003,power=1)++sample(9000),Map("counts_3"->0L)),
        Step(cmd(31004,power=1),Map("counts_3"->0L)),
        Step(cmd(32003,999,power=1),Map("mode"->1L,"counts_3"->999L)),
        Step(cmd(32004,power=1),Map("mode"->1L,"counts_3"->1000L)),
        Step(cmd(32005,power=1),Map("mode"->2L,"fault"->2L)))
      for(steps <- Seq(split,low)) {
        AsyncTest.run(top(click),Seq(1L,2L,19L),fresh(name+"-split-low")) { _ =>
          s"${if(click) "start=1;" else ""} ${campaign(click,steps)}"
        }
      }
    }
    test(s"$name native supervisor: disabled policy and POR during request or held reply") {
      for(held <- Seq(false,true); enabled <- Seq(false,true)) {
        AsyncTest.run(top(click,enabled),Seq(1L,2L,19L),fresh(name+"-por")) { _ =>
          s"""${if(click) "start=1;" else ""}
            ${if(enabled) campaign(click,boot()) else ""}
            ${fields.map(f => s"command_bits_$f=0;").mkString("\n")}
            command_req=1; ${if(held) "wait(reply_req); #19000000;" else "#1;"}
            reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
            #1000000000; reset=0; #1000000000; ${if(click) "start=1;" else ""}
            ${campaign(click,if(enabled) boot() else boot().map(s => s.copy(expected=Map("mode"->3L,"fault"->1L))))}
          """
        }
      }
    }
  }
}
