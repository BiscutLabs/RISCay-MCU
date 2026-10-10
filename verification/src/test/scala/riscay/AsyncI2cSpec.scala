// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Independent effect/serial oracle; these fixtures have no service clock. */
class AsyncI2cSpec extends AnyFunSuite {
  private def fresh(name: String): Path = {
    val root=Paths.get("build/async-i2c-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def publication(click: Boolean): AsyncModule = if(click)
    new riscay.click.I2cPublication(new ResetDomain("root")) else new riscay.bd.I2cPublication(new ResetDomain("root"))
  private def native(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickI2c(0x35,new ResetDomain("root")) else new riscay.bd.FourPhaseI2c(0x35,new ResetDomain("root"))
  private def monitor(dir: Path, click: Boolean, bypass: Boolean=false): String = {
    val node=ujson.read(Files.readString(dir.resolve("export/contract.json")))("manifest")("design")
    def cell(id: String)="dut."+node("primitives").arr.find(_("id").str==id).get("rtl_path").str.split('.').drop(1).mkString(".")
    val ids=Seq("observation","frame_payload","snapshot_payload") ++ (if(click) Seq("accepted_phase","frame_phase","snapshot_phase") else Seq.empty)
    val checks=ids.map { id => val p=cell(id); s"""begin
      time rise=0,fall=0,changed=0; bit rose=0,fell=0,seen=0;
      fork
        begin forever begin @(posedge $p.trigger or posedge reset);
          if(reset) begin rose=0; fell=0; seen=0; end else begin
            if(fell && $$time-fall <= 100000) $$fatal(1,"I2C_PULSE_LOW_$id");
            ${if(id!="accepted_phase") s"if(seen && $$time-changed <= 100000) $$fatal(1,\"I2C_SETUP_$id\");" else ""}
            rise=$$time; rose=1;
          end
        end end
        begin forever begin @(negedge $p.trigger); if(!reset && rose) begin
          if($$time-rise <= 100000) $$fatal(1,"I2C_PULSE_HIGH_$id"); fall=$$time; fell=1;
        end end end
        ${if(id!="accepted_phase") s"""begin forever begin @($p.d); if(!reset) begin
          if(rose && $$time-rise <= 100000) $$fatal(1,"I2C_HOLD_$id"); changed=$$time; seen=1;
        end end end""" else ""}
      join
    end""" }.mkString("\n")
    val drain=if(click) s"""begin forever begin @(${cell("acknowledge_guard")}.q); #2;
      if(!reset && ${cell("capture_gate")}.q) $$fatal(1,"I2C_RELEASE_BEFORE_CAPTURE_DRAIN"); end end""" else ""
    s"""fork $checks $drain join_none
      ${if(bypass) s"force ${cell("acknowledge_guard")}.q=${cell("acknowledge_guard")}.a;" else ""}
    """
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name I2C publication: independent effects, held payloads, delayed source return and capture apertures") {
      val dir=fresh(name+"-publication")
      AsyncTest.run(publication(click),1L to 24L,dir) { _ =>
        val transactions=(0 until 24).map { i =>
          val p=if(click) (i+1)%2 else 1
          s"""
            in_bits_frameValid=1; in_bits_snapshotValid=1;
            in_bits_state_head=${i%16}; in_bits_frame_ingress_frame_length=1;
            in_bits_frame_ingress_frame_bytes_0=${i+17}; in_bits_frame_resetEpoch=${i+5}; in_bits_snapshotTag=${i+31};
            #1000000; in_req=$p;
            fork
              begin wait(in_ack==$p); #700000000;
                ${if(click) "" else "in_req=0; wait(!in_ack);"}
              end
              begin wait(frame_req==$p); #${if(i%2==0) 2 else 900000000};
                if(frame_bits_ingress_frame_bytes_0 !== ${i+17} || frame_bits_resetEpoch !== ${i+5}) $$fatal(1,"I2C_FRAME_PAYLOAD");
                frame_ack=$p;
                ${if(click) "" else "wait(!frame_req); #2; frame_ack=0;"}
              end
              begin wait(snapshot_req==$p); #${if(i%2==1) 2 else 900000000};
                if(snapshot_bits !== ${i+31}) $$fatal(1,"I2C_SNAPSHOT_PAYLOAD"); snapshot_ack=$p;
                ${if(click) "" else "wait(!snapshot_req); #2; snapshot_ack=0;"}
              end
            join
            #200000000;
            if(delivered_frame != ${i+1} || delivered_snapshot != ${i+1}) $$fatal(1,"I2C_DUPLICATE_EFFECT");
          """
        }.mkString
        s"${monitor(dir,click)} $transactions"
      }
    }
    test(s"$name I2C native: serial receive, wraparound, repeated START commit, 36-byte little-endian read and NACK") {
      AsyncTest.run(native(click),Seq(1L,2L,19L),fresh(name+"-serial")) { _ =>
        var head=0
        def edge(rise: Boolean=false,fall: Boolean=false,start: Boolean=false,stop: Boolean=false,sda: Boolean=true,word: Long=0): String = {
          val slot=head%8;head=(head+1)%16;val gray=head^(head>>1)
          s"""edges_${slot}_rise=${if(rise) 1 else 0}; edges_${slot}_fall=${if(fall) 1 else 0};
            edges_${slot}_start=${if(start) 1 else 0}; edges_${slot}_stop=${if(stop) 1 else 0};
            edges_${slot}_sda=${if(sda) 1 else 0}; edges_${slot}_readWord=32'h${word.toHexString};
            edges_${slot}_resetEpoch=73; #1000000; tailGray=$gray;
            wait(observed_headGray==$gray); #400000000;
          """
        }
        def byte(value: Int, word: Long=0): String = (7 to 0 by -1).map(b => edge(rise=true,sda=(value&(1<<b))!=0)+edge(fall=true)).mkString +
          "if(!observed_drive) $fatal(1,\"I2C_EXPECTED_ACK\");\n"+edge(rise=true)+edge(fall=true,word=word)
        val write=edge(start=true)+byte(0x6a)+(0 until 33).map(i=>byte((i*37+9)&255)).mkString+edge(start=true)
        val frame="""wait(frame_req); #1000000000;
          if(frame_bits_ingress_frame_length !== 33 || frame_bits_ingress_frame_overflow || frame_bits_resetEpoch !== 73) $fatal(1,"I2C_FRAME_SHAPE");
        """+(0 until 33).map(i=>s"if(frame_bits_ingress_frame_bytes_$i !== ${(i*37+9)&255}) $$fatal(1,\"I2C_BYTE_$i\");").mkString("\n")+
          "frame_ack=1; "+(if(click) "" else "wait(!frame_req); #2; frame_ack=0;")
        val words=(0 until 9).map(i => (0x89abcdefL ^ (i*0x10203041L)) & 0xffffffffL)
        val read=byte(0x6b,words.head)+"wait(snapshot_req); snapshot_ack=1; "+(if(click) "" else "wait(!snapshot_req); #2; snapshot_ack=0;")+
          (0 until 36).map { i =>
            val value=(words(i/4) >>> ((i%4)*8))&255
            (7 to 0 by -1).map { b =>
              s"if(observed_drive !== ${if((value&(1<<b))==0) 1 else 0}) $$fatal(1,\"I2C_READ_${i}_$b\");\n"+
                edge(rise=true)+edge(fall=true)
            }.mkString+edge(rise=true,sda=i==35)+edge(fall=true,word=words(math.min(8,(i+1)/4)))
          }.mkString+"if(observed_drive || observed_active) $fatal(1,\"I2C_FINAL_NACK\");"
        s"${if(click) "start=1;" else ""} $write $frame $read"
      }
    }
  }
  test("Click I2C publication rejects a bypassed release guard") {
    val dir=fresh("click-guard-negative")
    val error=intercept[IllegalArgumentException] {
      AsyncTest.run(publication(true),Seq(2L),dir) { _ => s"""
        ${monitor(dir,true,bypass=true)}
        in_bits_frameValid=1; #1000000; in_req=1;
        wait(frame_req); frame_ack=1; #1000000000;
      """ }
    }
    assert(error.getMessage.contains("I2C_RELEASE_BEFORE_CAPTURE_DRAIN"),error.getMessage)
  }

}
