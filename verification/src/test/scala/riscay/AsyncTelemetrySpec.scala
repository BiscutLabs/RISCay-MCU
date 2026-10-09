// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Clockless protocol campaigns with explicit, independently calculated states. */
class AsyncTelemetrySpec extends AnyFunSuite {
  private val config = McuConfiguration(16,16,2,Vector(MeasurementChannel(0,"sample",1,0)),
    ApplicationProfile(1,1,"telemetry",Vector(HostRegister(0,"A"),HostRegister(17,"B")),Vector.empty))
  private val p = SocParameters(config)
  private case class Step(kind: Int = 0, events: Int = 0, clear: Int = 0, elapsed: Long = 0,
    offset: Int = 0, data: Long = 0, index: Int = 0,
    capture: Seq[Long] = Seq(0,0,0,0,0,0,0), changes: Map[String,Long] = Map.empty)
  private val initial = Map("output"->0L,"enable"->0L,"pending"->0L,"application_0"->0L,"application_1"->0L,
    "samples_0_value"->0L,"samples_0_valid"->0L,"samples_0_calibrated"->0L,"samples_0_age"->0L,
    "samples_0_sequence"->0L,"samples_0_never"->1L,"samples_0_fault"->0L)
  private val steps = Seq(
    Step(events=63,changes=Map("pending"->63L)),
    Step(events=4,clear=63,changes=Map("pending"->4L)),
    Step(kind=1,offset=24,data=0xdeadbeefL,changes=Map("output"->0xdeadbeefL)),
    Step(kind=1,offset=28,data=3,changes=Map("enable"->3L)),
    Step(kind=1,offset=52,index=17,data=123,changes=Map("application_1"->123L)),
    Step(kind=1,offset=52,index=16,data=999),
    Step(elapsed=9,capture=Seq(1,1,0,0,1,888,0),changes=Map("samples_0_age"->9L,"samples_0_sequence"->1L,"samples_0_fault"->1L)),
    // Two successes followed by a failure: latest status differs from last-good data.
    Step(elapsed=20,capture=Seq(1,3,1,0,1,42,7),changes=Map("samples_0_value"->42L,"samples_0_age"->7L,"samples_0_sequence"->4L,"samples_0_never"->0L)),
    Step(elapsed=5,capture=Seq(1,1,0,0,0,999,0),changes=Map("samples_0_age"->12L,"samples_0_sequence"->5L)),
    Step(elapsed=8,capture=Seq(1,1,1,1,1,100,2),changes=Map("samples_0_value"->100L,"samples_0_age"->2L,"samples_0_sequence"->6L,"samples_0_valid"->1L,"samples_0_calibrated"->1L,"samples_0_fault"->0L)),
    Step(kind=2,events=32,elapsed=3,changes=Map("output"->0L,"enable"->0L,"pending"->32L,"application_1"->0L,"samples_0_age"->5L)),
    Step(elapsed=0xffffffffL,changes=Map("samples_0_age"->0xffffffffL)),
    Step(elapsed=2,capture=Seq(1,0xffffffffL,0,0,0,0,0),changes=Map("samples_0_sequence"->5L,"samples_0_valid"->0L,"samples_0_calibrated"->0L,"samples_0_fault"->1L)),
    Step(capture=Seq(1,2,1,1,0,1234,0),changes=Map("samples_0_sequence"->7L,"samples_0_value"->1234L,"samples_0_age"->0L,"samples_0_valid"->1L,"samples_0_fault"->0L)),
    Step(kind=1,offset=8,clear=2,events=2,changes=Map("pending"->34L)),
    Step(kind=1,offset=8,clear=2,changes=Map("pending"->32L)))
  private def source(click: Boolean, campaign: Seq[Step]): String = campaign.zipWithIndex.map { case(s,i) =>
    val phase=if(click) (i+1)%2 else 1
    val capture=Seq("seen","count","hadValid","valid","calibrated","value","tailAge").zip(s.capture)
      .map { case(k,v) => s"command_bits_captures_0_$k=32'h${v.toHexString};" }.mkString("\n")
    s"""command_bits_kind=${s.kind}; command_bits_events=${s.events}; command_bits_clear=${s.clear};
      command_bits_elapsedUpper=32'h${s.elapsed.toHexString}; command_bits_offset=${s.offset};
      command_bits_data=32'h${s.data.toHexString}; command_bits_appIndex=${s.index}; $capture
      #2; command_req=$phase; wait(command_ack == $phase); #2;
      ${if(click) "" else "command_req=0; wait(!command_ack); #2;"}
    """
  }.mkString("\n")
  private def sink(click: Boolean, campaign: Seq[Step]): String = {
    var expected=initial
    campaign.zipWithIndex.map { case(s,i) =>
      expected ++= s.changes
      val phase=if(click) (i+1)%2 else 1
      val checks=expected.toSeq.sortBy(_._1).map { case(k,v) =>
        s"if(reply_bits_state_$k !== 32'h${v.toHexString}) $$fatal(1,\"TELEMETRY_${i}_$k actual=%h\",reply_bits_state_$k);"
      }.mkString("\n")
      s"""wait(reply_req == $phase); #2; $checks
        #${(i%5+1)*23000000L}; $checks
        if(reply_bits_kind !== ${s.kind}) $$fatal(1,"TELEMETRY_KIND"); reply_ack=$phase;
        ${if(click) "#2;" else "wait(!reply_req); #37000000; reply_ack=0; #2;"}
      """
    }.mkString("\n")
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def top(): AsyncModule = if(click) new riscay.click.ClickTelemetry(p,Vector(0,17),new ResetDomain("root"))
      else new riscay.bd.FourPhaseTelemetry(p,Vector(0,17),new ResetDomain("root"))
    def fresh(suffix: String) = {
      val root=Paths.get("build/async-telemetry-tests"); Files.createDirectories(root)
      Files.createTempDirectory(root,name+suffix)
    }
    test(s"$name native telemetry: clockless commits, coalesced publications, reset retention and reply stalls") {
      AsyncTest.run(top(),1L to 16L,fresh("-state")) { _ => s"""
        ${if(click) "start=1;" else ""}
        fork begin ${source(click,steps)} end begin ${sink(click,steps)} end join
        #1000000000;
        if(delivered_reply != ${steps.size}) $$fatal(1,"TELEMETRY_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native telemetry: POR cancels a stalled response and reinstalls cold state") {
      val before=Seq(Step(kind=1,offset=24,data=123)); val after=Seq(Step())
      AsyncTest.run(top(),Seq(1L,7L,19L),fresh("-por")) { _ => s"""
        ${if(click) "start=1;" else ""}
        ${source(click,before)} wait(reply_req); #100000000;
        reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
        #1000000000; reset=0; #1000000000; ${if(click) "start=1;" else ""}
        fork begin ${source(click,after)} end begin ${sink(click,after)} end join
        #1000000000;
      """ }
    }
  }
}
