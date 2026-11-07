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
  private case class Step(kind: Int = 1, offset: Int = 0, data: Long = 0, index: Int = 0,
    value: Long = 0, timestamp: Long = 0, changes: Map[String,Long] = Map.empty, recovery: Int = 0)
  private val initial = Map("output"->0L,"enable"->0L,"application_0"->0L,"application_1"->0L,
    "samples_0_value"->0L,"samples_0_valid"->0L,"samples_0_calibrated"->0L,"samples_0_timestamp"->0L,
    "samples_0_sequence"->0L,"samples_0_seen"->0L,"samples_0_fault"->0L)
  private val steps = Seq(
    Step(offset=24,data=0xdeadbeefL,changes=Map("output"->0xdeadbeefL)),
    Step(offset=28,data=3,changes=Map("enable"->3L)),
    Step(offset=52,index=17,data=123,changes=Map("application_1"->123L)),
    Step(offset=52,index=16,data=999),
    Step(offset=44,data=0,value=888,timestamp=9,changes=Map("samples_0_sequence"->1L,"samples_0_fault"->1L)),
    Step(offset=44,data=3,value=41,timestamp=22,changes=Map("samples_0_value"->41L,"samples_0_timestamp"->22L,
      "samples_0_sequence"->2L,"samples_0_seen"->1L,"samples_0_valid"->1L,"samples_0_calibrated"->1L,"samples_0_fault"->0L)),
    Step(offset=44,data=3,value=42,timestamp=29,changes=Map("samples_0_value"->42L,"samples_0_timestamp"->29L,"samples_0_sequence"->3L)),
    Step(offset=44,data=2,value=999,timestamp=34,changes=Map("samples_0_sequence"->4L,"samples_0_valid"->0L,"samples_0_calibrated"->0L,"samples_0_fault"->1L)),
    Step(offset=44,data=3,value=100,timestamp=42,changes=Map("samples_0_value"->100L,"samples_0_timestamp"->42L,"samples_0_sequence"->5L,
      "samples_0_valid"->1L,"samples_0_calibrated"->1L,"samples_0_fault"->0L)),
    Step(kind=2,changes=Map("output"->0L,"enable"->0L,"application_1"->0L)),
    // The bank retains the timestamp across low-word time-coordinate carry and failed attempts.
    // Age saturation is checked at the Services projection, where time is owned.
    Step(offset=44,data=0,value=0,timestamp=0x100000001L,changes=Map("samples_0_sequence"->6L,"samples_0_valid"->0L,
      "samples_0_calibrated"->0L,"samples_0_fault"->1L)),
    Step(offset=44,data=1,value=1234,timestamp=0x100000002L,changes=Map("samples_0_sequence"->7L,"samples_0_value"->1234L,
      "samples_0_timestamp"->0x100000002L,"samples_0_valid"->1L,"samples_0_fault"->0L)),
    Step(offset=8))
  private def source(click: Boolean, campaign: Seq[Step]): String = campaign.zipWithIndex.map { case(s,i) =>
    val phase=if(click) (i+1)%2 else 1
    s"""${if(click) "" else s"command_bits_recovery=${s.recovery};"}command_bits_kind=${s.kind}; command_bits_offset=${s.offset};
      command_bits_data=32'h${s.data.toHexString}; command_bits_appIndex=${s.index};
      command_bits_sample_index=0; command_bits_sample_value=32'h${s.value.toHexString};
      command_bits_sample_timestamp=${SampleTime.Width}'h${s.timestamp.toHexString};
      #2; command_req=$phase; wait(command_ack == $phase); #2;
      ${if(click) "" else "command_req=0; wait(!command_ack); #2;"}
    """
  }.mkString("\n")
  private def bankPort(field: String): String =
    if(field.startsWith("samples_")) "sampleView_"+field.stripPrefix("samples_") else "view_"+field
  private val bank=initial.keys.toSeq.sorted.map(bankPort).mkString("{",",","}")
  private def bdSink(campaign: Seq[Step], authorization: Option[Seq[Boolean]]=None): String = {
    require(authorization.forall(_.size==campaign.size),"TELEMETRY_QUALIFICATION_CAMPAIGN")
    var expected=initial
    val body=campaign.zipWithIndex.map { case(s,i) =>
      expected ++= s.changes
      val mask=(1L << p.config.gpioCount)-1
      expected=expected.updated("output",expected("output") & mask).updated("enable",expected("enable") & mask)
      val committed=expected.toSeq.sortBy(_._1).map { case(k,v) =>
        s"if(${bankPort(k)} !== 64'h${v.toHexString}) $$fatal(1,\"TELEMETRY_COMMITTED_${i}_$k actual=%h\",${bankPort(k)});"
      }.mkString("\n")
      val held=s"""
        if($bank !== savedBank) $$fatal(1,"TELEMETRY_BANK_CHANGED_BEFORE_ACCEPTANCE");
        if(reply_bits_kind !== ${s.kind} || reply_bits_recovery !== ${s.recovery})
          $$fatal(1,"TELEMETRY_IDENTITY");
      """
      val qualify=authorization.map(a => s"commitAck=${if(a(i)) 1 else 0};").getOrElse("")
      val qualifyReturn=if(authorization.nonEmpty) "commitAck=0;" else ""
      // Exercise both ACK-skew directions. The real receipt has separate FFs;
      // its ordinary ACK may precede the authorized bank capture. Keep the
      // borrowed command intact and the same bank oracle/deadline in that case.
      val accept=if(authorization.exists(_(i)) && i%2==0)
        s"reply_ack=1;#5000000;$qualify" else s"$qualify reply_ack=1;"
      s"""savedBank=$bank;wait(reply_req);#2;$held
        #${(i%5+1)*23000000L};$held
        $accept wait(!reply_req);#37000000;reply_ack=0;$qualifyReturn #2;
        $committed
      """
    }.mkString("\n")
    s"begin reg [$$bits($bank)-1:0] savedBank; $body end"
  }
  private def sink(click: Boolean, campaign: Seq[Step]): String = {
    if(!click) return bdSink(campaign)
    var expected=initial
    campaign.zipWithIndex.map { case(s,i) =>
      expected ++= s.changes;
      // Both independent banks store only implemented GPIO bits.
      { val mask=(1L << p.config.gpioCount)-1
        expected=expected.updated("output",expected("output") & mask).updated("enable",expected("enable") & mask)
      }
      val phase=if(click) (i+1)%2 else 1
      val checks=expected.toSeq.sortBy(_._1).map { case(k,v) =>
        s"if(reply_bits_state_$k !== 64'h${v.toHexString}) $$fatal(1,\"TELEMETRY_${i}_$k actual=%h\",reply_bits_state_$k);"
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
    test(s"$name native telemetry: clockless commits, single-writer publications, reset retention and reply stalls") {
      AsyncTest.run(top(),1L to 16L,fresh("-state")) { _ => s"""
        ${if(click) "start=1;" else ""}
        fork begin ${source(click,steps)} end begin ${sink(click,steps)} end join
        #1000000000;
        if(delivered_reply != ${steps.size}) $$fatal(1,"TELEMETRY_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native telemetry: sequence wraps modulo 32 bits without discarding the last good record") {
      // Seed only the closed-bank read port for one transaction, avoiding four
      // billion publications. The real transform, capture and return still run.
      val first=Seq(Step(offset=44,data=3,value=42,timestamp=99,changes=Map("samples_0_value"->42L,
        "samples_0_timestamp"->99L,"samples_0_sequence"->0xffffffffL,"samples_0_seen"->1L,
        "samples_0_valid"->1L,"samples_0_calibrated"->1L)))
      AsyncTest.run(top(),Seq(3L,11L),fresh("-sequence-wrap")) { _ => if(click) s"""
        ${if(click) "start=1;" else ""}
        force dut.ca_child_update.in_bits_samples_0_sequence=32'hfffffffe;
        fork begin ${source(click,first)} end begin ${sink(click,first)} end join
        #1000000000;release dut.ca_child_update.in_bits_samples_0_sequence;#1000000000;
        if(sampleView_0_sequence!==32'hffffffff) $$fatal(1,"SEQUENCE_SEED_NOT_COMMITTED");
        command_bits_offset=44;command_bits_data=0;command_bits_sample_value=999;
        #20000000;command_req=${if(click) 0 else 1};
        wait(reply_req===${if(click) 0 else 1});#20000000;
        if(reply_bits_state_samples_0_sequence!==0 || reply_bits_state_samples_0_value!==42 ||
           reply_bits_state_samples_0_timestamp!==99 || !reply_bits_state_samples_0_fault)
          $$fatal(1,"SEQUENCE_WRAP_LAST_GOOD");
        reply_ack=${if(click) 0 else 1};
        ${if(click) "wait(command_ack===0);" else "wait(command_ack);command_req=0;wait(!reply_req);#37000000;reply_ack=0;wait(!command_ack);"}
        #1000000000;
      """ else s"""
        // Seed the actual old bank Q slice, never the increment result or D.
        // The public sampleView output is only an alias; forcing it does not
        // change the internal retained read used by the transition.
        // Release just after real capture, before delayed Q publication. The
        // actual increment, EventRegister capture and reply return all execute.
        force dut.ca_primitive_sample_bank.q[35:4]=32'hfffffffe;
        #2;if(sampleView_0_sequence!==32'hfffffffe) $$fatal(1,"SEQUENCE_OLD_BANK_SEED");
        fork
          begin ${source(false,first)} end
          begin ${bdSink(first)} end
          begin @(posedge reply_ack);#2;release dut.ca_primitive_sample_bank.q[35:4];end
        join
        #1000000000;
        if(sampleView_0_sequence!==32'hffffffff) $$fatal(1,"SEQUENCE_SEED_NOT_COMMITTED");
        command_bits_offset=44;command_bits_data=0;command_bits_sample_value=999;
        #20000000;command_req=1;wait(reply_req);#20000000;
        if(sampleView_0_sequence!==32'hffffffff || sampleView_0_value!==42 ||
           sampleView_0_timestamp!==99 || sampleView_0_fault)
          $$fatal(1,"SEQUENCE_BANK_CHANGED_BEFORE_ACCEPTANCE");
        if(reply_bits_kind!==1 || reply_bits_recovery) $$fatal(1,"TELEMETRY_IDENTITY");
        reply_ack=1;wait(command_ack);command_req=0;
        wait(!reply_req);#37000000;reply_ack=0;wait(!command_ack);
        #1000000000;
        if(sampleView_0_sequence!==0 || sampleView_0_value!==42 ||
           sampleView_0_timestamp!==99 || !sampleView_0_fault)
          $$fatal(1,"SEQUENCE_WRAP_LAST_GOOD");
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
    if(!click) {
      test("bd native telemetry: revoked application publication still commits accepted software samples") {
        val qualified=Seq(
          Step(offset=52,index=0,data=123),
          Step(offset=44,data=3,value=42,timestamp=99,changes=Map("samples_0_value"->42L,
            "samples_0_timestamp"->99L,"samples_0_sequence"->1L,"samples_0_seen"->1L,
            "samples_0_valid"->1L,"samples_0_calibrated"->1L)),
          Step(offset=52,index=0,data=456,changes=Map("application_0"->456L)),
          Step(kind=2,recovery=1,changes=Map("application_0"->0L)))
        AsyncTest.run(new riscay.bd.FourPhaseTelemetry(p,Vector(0,17),new ResetDomain("root"),qualifyCommit=true),
          Seq(1L,2L,19L),fresh("-qualified-commit")) { _ => s"""
          commitAck=0;
          fork begin ${source(false,qualified)} end
            begin ${bdSink(qualified,Some(Seq(false,false,true,true)))} end join
          #1000000000;
          if(delivered_reply!=${qualified.size}) $$fatal(1,"TELEMETRY_QUALIFIED_EXACTLY_ONCE");
        """ }
      }
      test("bd native telemetry: a queued next command cannot overwrite the borrowed first update") {
        val first=Seq(Step(offset=52,index=0,data=0x12345678L))
        val second=Seq(Step(offset=52,index=17,data=0x76543210L,recovery=1))
        AsyncTest.run(top(),Seq(1L,2L,19L),fresh("-command-borrow")) { _ => s"""
          begin
            reg second_offered=0;
            fork
              begin ${source(false,first)} second_offered=1;${source(false,second)} end
              begin
                wait(reply_req);#100000000;
                if(!second_offered || !command_req || view_application_0!==0 || view_application_1!==0 ||
                  reply_bits_kind!==1 || reply_bits_recovery)
                  $$fatal(1,"TELEMETRY_BORROW_FIRST_HELD");
                reply_ack=1;wait(!reply_req);#37000000;
                if(view_application_0!==32'h12345678 || view_application_1!==0)
                  $$fatal(1,"TELEMETRY_BORROW_FIRST_COMMITTED");
                reply_ack=0;#2;
                wait(reply_req);#100000000;
                if(view_application_0!==32'h12345678 || view_application_1!==0 ||
                  reply_bits_kind!==1 || !reply_bits_recovery)
                  $$fatal(1,"TELEMETRY_BORROW_SECOND_HELD");
                reply_ack=1;wait(!reply_req);#37000000;reply_ack=0;#2;
              end
            join
            #1000000000;
            if(view_application_0!==32'h12345678 || view_application_1!==32'h76543210 || delivered_reply!=2)
              $$fatal(1,"TELEMETRY_BORROW_EXACTLY_ONCE");
          end
        """ }
      }
    }
  }
}
