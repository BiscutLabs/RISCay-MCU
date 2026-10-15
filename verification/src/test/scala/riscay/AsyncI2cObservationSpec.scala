// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Independent named-field oracle for the front's native observation.
  * No periodic clock, production projection helper or production packing is used.
  */
class AsyncI2cObservationSpec extends AnyFunSuite {
  private val fields=Seq("headGray"->4,"active"->1,"rejected"->1,"addressByte"->1,
    "drive"->1,"ack"->1,"sent"->6)
  private val omitted=Seq("head"->4,"mode"->4,"selectedWrite"->1,"receive"->8,
    "bit"->3,"reading"->1,"masterAck"->1,"length"->6,"overflow"->1,"send"->32) ++
    (0 until 33).map(i => s"bytes_$i"->8)
  require(fields.map(_._2).sum==15 && omitted.map(_._2).sum==325)
  private def fresh(name: String): Path = {
    val root=Paths.get("build/async-i2c-observation-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.I2cPublication(new ResetDomain("root")) else new riscay.bd.I2cPublication(new ResetDomain("root"))
  private def cell(dir: Path,id: String): String = {
    val node=ujson.read(Files.readString(dir.resolve("export/contract.json")))("manifest")("design")
    val matches=node("primitives").arr.filter(_("id").str==id)
    require(matches.size==1,"I2C_OBSERVATION_PRIMITIVE_IDENTITY")
    val p=matches.head
    if(id=="observation") {
      require(p("model").str=="ChiselAsyncEventRegister_v1" && p("parameters")("WIDTH").str=="15",
        "I2C_OBSERVATION_STORAGE_WIDTH")
    }
    "dut."+p("rtl_path").str.split('.').drop(1).mkString(".")
  }
  // Build patterns as a map of field names, not from the production bundle's
  // packing. Every visible bit toggles independently of every other visible bit.
  private val zero=fields.map { case(n,_) => n->BigInt(0) }.toMap
  private val ones=fields.map { case(n,w) => n->((BigInt(1)<<w)-1) }.toMap
  private val patterns=Seq(zero) ++ fields.flatMap { case(n,w) =>
    (0 until w).map(b => zero.updated(n,BigInt(1)<<b))
  } ++ Seq(ones) ++ fields.flatMap { case(n,w) =>
    (0 until w).map(b => ones.updated(n,ones(n)^(BigInt(1)<<b)))
  }
  private def assign(values: Map[String,BigInt]): String = fields.map { case(n,w) =>
    s"in_bits_state_$n=$w'h${values(n).toString(16)};"
  }.mkString("\n")
  private def expect(values: Map[String,BigInt],id: String): String = fields.map { case(n,w) =>
    s"if(observed_$n !== $w'h${values(n).toString(16)}) $$fatal(1,\"I2C_OBSERVATION_${id}_$n\");"
  }.mkString("\n")
  private def noise(index: Int): String = omitted.zipWithIndex.map { case((n,w),i) =>
    val value=if((index+i)%2==0) BigInt(0) else (BigInt(1)<<w)-1
    s"in_bits_state_$n=$w'h${value.toString(16)};"
  }.mkString("\n")
  private def sourceFrame(index: Int): String = {
    val bytes=(0 until 33).map { i =>
      val value=if(index==0) (i*53+7)&255 else (i*29+index*17)&255
      s"in_bits_frame_ingress_frame_bytes_$i=8'd$value;"
    }.mkString("\n")
    s"""in_bits_frame_ingress_frame_length=${if(index==0) 33 else index%64};
      in_bits_frame_ingress_frame_overflow=${if(index==0) 1 else index%2};
      in_bits_frame_ingress_resetActive=${if(index==0) 1 else index%2};
      in_bits_frame_ingress_programBusy=${if(index==0) 0 else (index+1)%2};
      in_bits_frame_resetEpoch=64'h${if(index==0) "fedcba9876543210" else (BigInt(index)*0x102030405L).toString(16)};
      in_bits_snapshotTag=${if(index==0) 165 else index};
      $bytes
    """
  }
  private val retainedFrame="""if(frame_bits_ingress_frame_length !== 33 || !frame_bits_ingress_frame_overflow ||
      !frame_bits_ingress_resetActive || frame_bits_ingress_programBusy ||
      frame_bits_resetEpoch !== 64'hfedcba9876543210 || snapshot_bits !== 8'ha5)
      $fatal(1,"I2C_OBSERVATION_RETAINED_CONTEXT");
    """+(0 until 33).map(i => s"if(frame_bits_ingress_frame_bytes_$i !== 8'd${(i*53+7)&255}) $$fatal(1,\"I2C_OBSERVATION_RETAINED_BYTE_$i\");").mkString("\n")
  private def monitor(dir: Path): String = {
    val p=cell(dir,"observation")
    s"""begin
      time rise=0,fall=0,changed=0; bit rose=0,fell=0,seen=0;
      fork
        begin forever begin @(posedge $p.trigger or posedge reset);
          if(reset) begin rose=0; fell=0; seen=0; end else begin
            if(fell && $$time-fall <= 100000) $$fatal(1,"I2C_OBSERVATION_PULSE_LOW");
            if(seen && $$time-changed <= 100000) $$fatal(1,"I2C_OBSERVATION_SETUP");
            rise=$$time; rose=1;
          end
        end end
        begin forever begin @(negedge $p.trigger); if(!reset && rose) begin
          if($$time-rise <= 100000) $$fatal(1,"I2C_OBSERVATION_PULSE_HIGH"); fall=$$time; fell=1;
        end end end
        begin forever begin @($p.d); if(!reset) begin
          if(rose && $$time-rise <= 100000) $$fatal(1,"I2C_OBSERVATION_HOLD"); changed=$$time; seen=1;
        end end end
      join
    end"""
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name I2C observation: every bit, omitted-field noise and held independent effects") {
      val dir=fresh(name+"-projection")
      AsyncTest.run(top(click),Seq(1L,2L,19L),dir) { _ =>
        val p=cell(dir,"observation")
        val transactions=patterns.zipWithIndex.map { case(values,i) =>
          val phase=if(click) (i+1)%2 else 1
          val previous=if(i==0) zero else patterns(i-1)
          s"""
            ${assign(values)} ${noise(i)} ${sourceFrame(i)}
            in_bits_frameValid=${if(i==0) 1 else 0}; in_bits_snapshotValid=${if(i==0) 1 else 0};
            #20000000;
            ${expect(previous,"IDLE")}
            if(captures!=$i) $$fatal(1,"I2C_OBSERVATION_SPURIOUS_CAPTURE");
            in_req=$phase; wait(in_ack==$phase); #2;
            ${expect(values,"CAPTURE")}
            if(captures!=${i+1}) $$fatal(1,"I2C_OBSERVATION_CAPTURE_COUNT");
            ${if(click) "" else "in_req=0; wait(!in_ack); #2;"}
            wait(frame_req==1 && snapshot_req==1);
            $retainedFrame
          """
        }.mkString
        s"""begin
          integer captures=0;
          fork
            ${monitor(dir)}
            begin forever begin @(posedge $p.trigger); if(!reset) captures=captures+1; end end
          join_none
          $transactions
          frame_ack=1; snapshot_ack=1;
          ${if(click) "" else "wait(!frame_req && !snapshot_req); #2; frame_ack=0; snapshot_ack=0;"}
          #200000000;
          if(delivered_frame!=1 || delivered_snapshot!=1) $$fatal(1,"I2C_OBSERVATION_EFFECT_COUNT");
          ${assign(zero)} ${noise(39)} in_bits_frameValid=0; in_bits_snapshotValid=0;
          #20000000; in_req=1; wait(in_ack==1); #2;
          ${expect(zero,"AFTER_DRAIN")}
          ${if(click) "" else "in_req=0; wait(!in_ack);"}
          #200000000;
          if(captures!=${patterns.size+1} || delivered_frame!=1 || delivered_snapshot!=1)
            $$fatal(1,"I2C_OBSERVATION_FINAL_COUNT");
        end"""
      }
    }
    test(s"$name I2C observation: POR at request, capture and held effect without replay") {
      val dir=fresh(name+"-projection-por")
      AsyncTest.run(top(click),Seq(1L,2L,19L),dir) { _ =>
        val p=cell(dir,"observation")
        val attempts=(0 until 3).map { point =>
          val abort=point match {
            case 0 => "#1000000;"
            case 1 => s"@(posedge $p.trigger); #2;"
            case _ => "wait(frame_req && snapshot_req); #20000000;"
          }
          s"""
            reset=1; in_req=0; frame_ack=0; snapshot_ack=0;
            in_bits_frameValid=0; in_bits_snapshotValid=0;
            #1000000000; reset=0; #1000000000;
            ${expect(zero,"POR_INITIAL")}
            ${assign(ones)} ${noise(point)} ${sourceFrame(0)}
            in_bits_frameValid=1; in_bits_snapshotValid=1;
            #20000000; in_req=1; $abort
            reset=1; in_req=0; frame_ack=0; snapshot_ack=0;
            in_bits_frameValid=0; in_bits_snapshotValid=0;
            #1000000000; reset=0; #1000000000;
            ${expect(zero,"POR_ABORT")}
            if(frame_req || snapshot_req || in_ack) $$fatal(1,"I2C_OBSERVATION_POR_REPLAY");
            ${assign(patterns(1+point))} ${noise(9+point)}
            #20000000; in_req=1; wait(in_ack==1); #2;
            ${expect(patterns(1+point),"POR_RECOVERY")}
            ${if(click) "" else "in_req=0; wait(!in_ack);"}
            #200000000;
            if(frame_req || snapshot_req) $$fatal(1,"I2C_OBSERVATION_POR_FRESH_EFFECT");
          """
        }.mkString
        val inputPhase=if(click) 0 else 1 // last recovery accepted phase one
        val completion=s"""
          ${assign(ones)} ${noise(47)} ${sourceFrame(1)}
          in_bits_frameValid=1; in_bits_snapshotValid=1;
          #20000000; in_req=$inputPhase; wait(in_ack==$inputPhase); #2;
          ${expect(ones,"POR_COMPLETION")}
          ${if(click) "" else "in_req=0; wait(!in_ack); #2;"}
          wait(frame_req==1 && snapshot_req==1); #2;
          if(frame_bits_ingress_frame_length !== 1 ||
             !frame_bits_ingress_frame_overflow || !frame_bits_ingress_resetActive ||
             frame_bits_ingress_programBusy ||
             frame_bits_resetEpoch !== 64'h0000000102030405 || snapshot_bits !== 8'h01)
            $$fatal(1,"I2C_OBSERVATION_POR_FRESH_IDENTITY");
          ${(0 until 33).map(i =>
            s"if(frame_bits_ingress_frame_bytes_$i !== 8'd${(i*29+17)&255}) $$fatal(1,\"I2C_OBSERVATION_POR_FRESH_BYTE_$i\");").mkString("\n")}
          if(delivered_frame!=0 || delivered_snapshot!=0)
            $$fatal(1,"I2C_OBSERVATION_POR_STALE_DELIVERY");
          frame_ack=1;
          ${if(click) "" else "wait(!frame_req); #2; frame_ack=0;"}
          #20000000;
          if(delivered_frame!=1 || delivered_snapshot!=0 || snapshot_req!=1)
            $$fatal(1,"I2C_OBSERVATION_POR_INDEPENDENT_ACK");
          snapshot_ack=1;
          ${if(click) "" else "wait(!snapshot_req); #2; snapshot_ack=0;"}
          #200000000;
          if(delivered_frame!=1 || delivered_snapshot!=1)
            $$fatal(1,"I2C_OBSERVATION_POR_FINAL_COUNT");
        """
        s"fork ${monitor(dir)} join_none\n$attempts\n$completion"
      }
    }
  }
}
