// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Independent addressed-byte oracle. No periodic clocks or production packing
  * helper is used.
  */
class AsyncI2cByteStoreSpec extends AnyFunSuite {
  private def fresh(name: String): Path = {
    val root=Paths.get("build/async-i2c-addressed-byte-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def publication(click: Boolean): AsyncModule = if(click)
    new riscay.click.I2cPublication(new ResetDomain("root")) else
    new riscay.bd.I2cPublication(new ResetDomain("root"))
  private def native(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickI2c(0x35,new ResetDomain("root")) else
    new riscay.bd.FourPhaseI2c(0x35,new ResetDomain("root"))
  private case class Cell(id: String,path: String,width: Int)
  private def cells(dir: Path): Seq[Cell] = {
    def visit(n: ujson.Value): Seq[Cell] = n("primitives").arr.toSeq.filter { p =>
      p("model").str=="ChiselAsyncEventRegister_v1"
    }.map { p => Cell(p("id").str,"dut."+p("rtl_path").str.split('.').drop(1).mkString("."),
      p("parameters")("WIDTH").str.toInt)
    } ++ n("children").arr.toSeq.flatMap(c => visit(c("contract")))
    visit(ujson.read(Files.readString(dir.resolve("export/contract.json")))("manifest")("design"))
  }
  private def scratch(dir: Path): Seq[Cell] = {
    def nodes(n: ujson.Value): Seq[ujson.Value] = Seq(n) ++
      n("children").arr.toSeq.flatMap(c => nodes(c("contract")))
    val candidates=nodes(ujson.read(Files.readString(dir.resolve("export/contract.json")))("manifest")("design"))
      .filter(n => n("primitives").arr.exists(p => Set("receive_all","receive_0")(p("id").str)))
    require(candidates.size==1,"I2C_BYTE_PUBLICATION_METADATA_IDENTITY")
    val n=candidates.head
    val endpoints=n("endpoints").arr.map(e => e("id").str->e("width").num.toInt).toMap
    require(endpoints.size==n("endpoints").arr.size,"I2C_BYTE_ENDPOINT_DUPLICATION")
    val selective=n("primitives").arr.exists(_("id").str=="receive_0")
    val click=n("primitives").arr.exists(_("id").str=="accepted_phase")
    val expected=Map("in_data"->174,"frame_data"->337,"snapshot_data"->8,"observed"->15,
      "capture"->1,"sources"->(if(click) 785 else 783),
      "register_data"->(if(click) 362 else 360),"captured"->(if(click) 362 else 360),
      "byte_sources"->(if(selective) 16 else 280),
      "byte_register_data"->(if(selective) 41 else 264),"receive_bytes"->264,"write_legal"->1) ++
      (if(selective) Map("byte_value"->8,"byte_triggers"->33,"byte_idle"->1,"byte_complete"->1) ++
        (0 until 33).flatMap(i => Seq(s"byte_trigger_$i"->1,s"byte_q_$i"->8)).toMap else Map.empty[String,Int])
    expected.foreach { case(id,width) => require(endpoints.get(id).contains(width),s"I2C_BYTE_ENDPOINT_WIDTH_$id") }
    val registerIds=if(selective) (0 until 33).map(i => s"receive_$i") else Seq("receive_all")
    registerIds.foreach { id =>
      val p=n("primitives").arr.filter(_("id").str==id)
      require(p.size==1 && p.head("parameters")("RESET_VALUE").str=="0","I2C_BYTE_REGISTER_RESET")
      val ports=p.head("ports").arr.map(p => p("name").str->(p("width").num.toInt,p("direction").str)).toMap
      val width=if(selective) 8 else 264
      require(ports==Map("reset"->(1,"input"),"trigger"->(1,"input"),"d"->(width,"input"),"q"->(width,"output")),
        "I2C_BYTE_ACTUAL_REGISTER_PORTS")
    }
    val all=cells(dir).filter(c => c.id.startsWith("receive_"))
    val common=all.filter(_.id=="receive_all")
    if(common.nonEmpty) {
      require(all.size==1 && common.head.width==264,"I2C_BYTE_COMMON_IDENTITY")
      common
    } else {
      require(all.size==33 && all.forall(_.width==8),"I2C_BYTE_SELECTIVE_IDENTITY")
      (0 until 33).map(i => all.find(_.id==s"receive_$i").get)
    }
  }
  private def q(c: Seq[Cell],i: Int): String = if(c.size==1)
    s"${c.head.path}.q[${i*8+7}:${i*8}]" else s"${c(i).path}.q"
  private def memory(c: Seq[Cell],expected: Seq[Int],label: String): String =
    expected.zipWithIndex.map { case(value,i) =>
      s"if(${q(c,i)} !== 8'd$value) $$fatal(1,\"I2C_BYTE_${label}_$i\");"
    }.mkString("\n")
  private def frame(expected: Seq[Int],length: Int,overflow: Boolean,resetActive: Boolean,
      busy: Boolean,epoch: BigInt,label: String): String = {
    s"""if(frame_bits_ingress_frame_length !== 6'd$length ||
      frame_bits_ingress_frame_overflow !== 1'b${if(overflow) 1 else 0} ||
      frame_bits_ingress_resetActive !== 1'b${if(resetActive) 1 else 0} ||
      frame_bits_ingress_programBusy !== 1'b${if(busy) 1 else 0} ||
      frame_bits_resetEpoch !== 64'h${epoch.toString(16)}) $$fatal(1,"I2C_BYTE_${label}_CONTEXT");
    """+expected.zipWithIndex.map { case(value,i) =>
      s"if(frame_bits_ingress_frame_bytes_$i !== 8'd$value) $$fatal(1,\"I2C_BYTE_${label}_FRAME_$i\");"
    }.mkString("\n")
  }
  private def metadata(length: Int,overflow: Boolean=false,resetActive: Boolean=false,
      busy: Boolean=false,epoch: BigInt=0,tag: Int=0): String = s"""
    in_bits_frame_ingress_frame_length=$length;
    in_bits_frame_ingress_frame_overflow=${if(overflow) 1 else 0};
    in_bits_frame_ingress_resetActive=${if(resetActive) 1 else 0};
    in_bits_frame_ingress_programBusy=${if(busy) 1 else 0};
    in_bits_frame_resetEpoch=64'h${epoch.toString(16)}; in_bits_snapshotTag=$tag;
  """
  private def aperture(c: Cell): String = s"""begin
    time rise=0,fall=0,changed=0; bit rose=0,fell=0,seen=0;
    fork
      begin forever begin @(posedge ${c.path}.trigger or posedge reset);
        if(reset) begin rose=0; fell=0; seen=0; end else begin
          if(fell && $$time-fall <= 100000) $$fatal(1,"I2C_BYTE_LOW_${c.id}");
          if(seen && $$time-changed <= 100000) $$fatal(1,"I2C_BYTE_SETUP_${c.id}");
          rise=$$time; rose=1;
        end
      end end
      begin forever begin @(negedge ${c.path}.trigger); if(!reset && rose) begin
        if($$time-rise <= 100000) $$fatal(1,"I2C_BYTE_HIGH_${c.id}"); fall=$$time; fell=1;
      end end end
      begin forever begin @(${c.path}.d); if(!reset) begin
        if(rose && $$time-rise <= 100000) $$fatal(1,"I2C_BYTE_HOLD_${c.id}"); changed=$$time; seen=1;
      end end end
    join
  end"""
  private def monitors(c: Seq[Cell],qualified: Boolean=true): String = {
    val count=c.zipWithIndex.map { case(p,i) =>
      val qualification=if(qualified && c.size==33) s"""
        if(!in_bits_byteWrite_valid || in_bits_frameValid || in_bits_byteWrite_index != $i)
          $$fatal(1,"I2C_BYTE_UNSELECTED_TRIGGER_$i");
        if(${p.path}.d !== in_bits_byteWrite_data) $$fatal(1,"I2C_BYTE_CAPTURE_D_$i");
      """ else ""
      s"""begin forever begin @(posedge ${p.path}.trigger or posedge reset);
        if(reset) pulseCount[$i]=0; else begin pulseCount[$i]=pulseCount[$i]+1; $qualification end
      end end"""
    }.mkString("\n")
    s"""integer pulseCount[0:${c.size-1}];
      for(integer i=0;i<${c.size};i=i+1) pulseCount[i]=0;
      fork ${c.map(aperture).mkString("\n")} $count join_none
    """
  }
  private class Stimulus(click: Boolean,c: Seq[Cell]) {
    var phase=0; var transactions=0
    var bytes=Vector.fill(33)(0); var pulses=Vector.fill(c.size)(0)
    def afterAck(label: String): String = memory(c,bytes,label)+pulses.zipWithIndex.map { case(n,i) =>
      s"if(pulseCount[$i]!=$n) $$fatal(1,\"I2C_BYTE_${label}_PULSES_$i\");"
    }.mkString("\n")
    def returned: String = if(click) "" else "in_req=0; wait(!in_ack); #2;"
    def offer(write: Option[(Int,Int)]=None,frameValid: Boolean=false,snapshotValid: Boolean=false): String = {
      phase=if(click) 1-phase else 1; transactions+=1
      write.foreach { case(i,v) => bytes=bytes.updated(i,v) }
      if(c.size==1) pulses=pulses.updated(0,pulses.head+1)
      else write.foreach { case(i,_) => pulses=pulses.updated(i,pulses(i)+1) }
      val (index,value)=write.getOrElse(((transactions*7)%64,(transactions*91)&255))
      s"""
        in_bits_byteWrite_valid=${if(write.nonEmpty) 1 else 0};
        in_bits_byteWrite_index=$index; in_bits_byteWrite_data=$value;
        in_bits_frameValid=${if(frameValid) 1 else 0}; in_bits_snapshotValid=${if(snapshotValid) 1 else 0};
        in_bits_state_headGray=${transactions%16};
        #1000000; in_req=$phase;
      """
    }
    def finish(label: String): String = s"""
      wait(in_ack==$phase); #2;
      ${afterAck(label)}
      if(observed_headGray !== ${transactions%16}) $$fatal(1,"I2C_BYTE_${label}_OBSERVATION");
      $returned
    """
    def send(write: Option[(Int,Int)]=None,frameValid: Boolean=false,snapshotValid: Boolean=false): String = {
      val offered=offer(write,frameValid,snapshotValid)
      offered+finish(s"ACK_$transactions")
    }
    def por: String = {
      phase=0; transactions=0; bytes=Vector.fill(33)(0); pulses=Vector.fill(c.size)(0)
      s"""reset=1; in_req=0; frame_ack=0; snapshot_ack=0;
        in_bits_byteWrite_valid=0; in_bits_frameValid=0; in_bits_snapshotValid=0;
        #1000000000; reset=0; #1000000000;
        ${afterAck("POR")}
        if(in_ack || frame_req || snapshot_req) $$fatal(1,"I2C_BYTE_POR_REPLAY");
      """
    }
  }
  private def release(click: Boolean,channel: String,phase: Int): String =
    s"${channel}_ack=$phase; #2; "+(if(click) "" else
      s"wait(!${channel}_req); #2; ${channel}_ack=0; #2;")

  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name addressed bytes: all lanes, retained tail, immediate reuse and independent held effects") {
      val dir=fresh(name+"-scratch")
      AsyncTest.run(publication(click),Seq(1L,2L,19L),dir) { _ =>
        val c=scratch(dir); val s=new Stimulus(click,c)
        val initial=memory(c,s.bytes,"INITIAL")
        val fill=(0 until 4).flatMap { round => (0 until 33).map { i =>
          val value=round match {
            case 0 => 0
            case 1 => 255
            case 2 => 1 << (i%8)
            case _ => (i*53+7)&255
          }
          s.send(Some(i->value))
        }}.mkString
        val held=s.bytes
        val first=metadata(33,true,true,false,BigInt("fedcba9876543210",16),165)+s.send(frameValid=true,snapshotValid=true)
        val heldCheck=frame(held,33,true,true,false,BigInt("fedcba9876543210",16),"HELD")+
          "if(snapshot_bits !== 8'ha5) $fatal(1,\"I2C_BYTE_HELD_SNAPSHOT\");"
        // Scratch writes continue while both effects are held. Every unselected
        // byte and the complete old output frame are checked after each input ACK.
        val refill=(0 until 33).map(i => s.send(Some(i->((i*29+101)&255)))+heldCheck).mkString
        val idle=(0 until 4).map(_ => s.send()+heldCheck).mkString
        // A short frame copies the entire retained scratch array; its unused
        // tail must be preserved, not cleared or borrowed from the held frame.
        val shortWrites=s.send(Some(0->0x3c))+s.send(Some(1->0xc3))
        val latest=s.bytes
        val secondOffer=metadata(2,false,false,true,73,90)+s.offer(frameValid=true)
        val pendingPhase=s.phase; val oldPhase=if(click) 1-pendingPhase else 0
        val secondFinish=s.finish("SECOND_FRAME")
        val secondFramePhase=if(click) 0 else 1
        s"""begin
          ${monitors(c)} $initial $fill $first
          wait(frame_req==1 && snapshot_req==1); #2; $heldCheck
          $refill $idle $shortWrites $secondOffer
          #300000000;
          if(in_ack!=$oldPhase || delivered_frame!=0 || delivered_snapshot!=0)
            $$fatal(1,"I2C_BYTE_SECOND_FRAME_DID_NOT_STALL");
          $heldCheck
          ${release(click,"frame",1)}
          $secondFinish
          wait(frame_req==$secondFramePhase); #2;
          ${frame(latest,2,false,false,true,73,"SECOND")}
          if(snapshot_bits!==8'ha5 || snapshot_req!=1 || delivered_snapshot!=0)
            $$fatal(1,"I2C_BYTE_SNAPSHOT_RETENTION");
          ${release(click,"frame",secondFramePhase)}
          #200000000;
          if(delivered_frame!=2 || delivered_snapshot!=0) $$fatal(1,"I2C_BYTE_FRAME_COUNT");
          ${release(click,"snapshot",1)}
          #200000000;
          if(delivered_frame!=2 || delivered_snapshot!=1) $$fatal(1,"I2C_BYTE_FINAL_COUNT");
        end"""
      }
    }
    test(s"$name addressed bytes: POR during request, actual byte capture and retained frame") {
      val dir=fresh(name+"-scratch-por")
      AsyncTest.run(publication(click),Seq(1L,2L,19L),dir) { _ =>
        val c=scratch(dir); val s=new Stimulus(click,c)
        val attempts=(0 until 3).map { point =>
          val reset=s.por
          val index=point*16
          val atWrite=s.offer(Some(index->(0x91+point)))
          val abort=point match {
            case 0 => "#1000000;"
            case 1 => s"@(posedge ${if(c.size==1) c.head.path else c(index).path}.trigger); #2;"
            case _ => s.finish("BEFORE_HELD_POR")+metadata(33,epoch=99)+s.offer(frameValid=true)+
              "wait(frame_req==1); #20000000;"
          }
          reset+atWrite+abort+s.por
        }.mkString
        val freshWrite=s.send(Some(32->0x7d))
        val freshFrame=metadata(33,epoch=BigInt("1020304050607080",16))+s.send(frameValid=true)
        s"""begin
          ${monitors(c)} $attempts $freshWrite $freshFrame
          wait(frame_req==1); #2;
          ${frame(s.bytes,33,false,false,false,BigInt("1020304050607080",16),"FRESH")}
          if(delivered_frame!=0 || delivered_snapshot!=0) $$fatal(1,"I2C_BYTE_POR_STALE_DELIVERY");
          ${release(click,"frame",1)}
          #200000000;
          if(delivered_frame!=1 || delivered_snapshot!=0) $$fatal(1,"I2C_BYTE_POR_FINAL_COUNT");
        end"""
      }
    }
    test(s"$name addressed bytes: illegal index or simultaneous write and frame is fail-closed") {
      val dir=fresh(name+"-scratch-invalid")
      AsyncTest.run(publication(click),Seq(1L,2L,19L),dir) { _ =>
        val c=scratch(dir); val s=new Stimulus(click,c)
        val invalid=Seq((33,false),(63,false),(0,true)).map { case(index,withFrame) =>
          s.por+s"""
            in_bits_byteWrite_valid=1; in_bits_byteWrite_index=$index; in_bits_byteWrite_data=255;
            in_bits_frameValid=${if(withFrame) 1 else 0}; in_bits_frame_ingress_frame_length=1;
            #1000000; in_req=1; #500000000;
            if(in_ack || frame_req || snapshot_req) $$fatal(1,"I2C_BYTE_ILLEGAL_ACCEPTANCE");
            ${s.afterAck("ILLEGAL")}
          """
        }.mkString
        val recovery=s.por+s.send(Some(0->0x35))+metadata(1,epoch=42)+s.send(frameValid=true)
        s"""begin
          ${monitors(c)} $invalid $recovery
          wait(frame_req==1); #2;
          ${frame(s.bytes,1,false,false,false,42,"ILLEGAL_RECOVERY")}
          ${release(click,"frame",1)}
          #200000000;
          if(delivered_frame!=1 || delivered_snapshot!=0) $$fatal(1,"I2C_BYTE_ILLEGAL_RECOVERY_COUNT");
        end"""
      }
    }
    test(s"$name addressed bytes: composed serial short, partial, timeout, rejection and overflow") {
      val dir=fresh(name+"-scratch-serial")
      AsyncTest.run(native(click),Seq(1L,2L,19L),dir) { _ =>
        val c=scratch(dir); var head=0; var framePhase=0
        var expected=Vector.fill(33)(0); var delivered=0
        def edge(rise: Boolean=false,fall: Boolean=false,start: Boolean=false,stop: Boolean=false,
            timeout: Boolean=false,sda: Boolean=true): String = {
          val slot=head%8; head=(head+1)%16; val gray=head^(head>>1)
          s"""edges_${slot}_rise=${if(rise) 1 else 0}; edges_${slot}_fall=${if(fall) 1 else 0};
            edges_${slot}_start=${if(start) 1 else 0}; edges_${slot}_stop=${if(stop) 1 else 0};
            edges_${slot}_timeout=${if(timeout) 1 else 0}; edges_${slot}_sda=${if(sda) 1 else 0};
            edges_${slot}_resetEpoch=73; #1000000; tailGray=$gray;
            wait(observed_headGray==$gray); #400000000;
          """
        }
        def byte(value: Int,ack: Boolean=true): String =
          (7 to 0 by -1).map(b => edge(rise=true,sda=(value&(1<<b))!=0)+edge(fall=true)).mkString+
            s"if(observed_drive !== 1'b${if(ack) 1 else 0}) $$fatal(1,\"I2C_BYTE_SERIAL_ACK\");\n"+
            edge(rise=true)+edge(fall=true)
        def start= edge(start=true)+byte(0x6a)
        def data(values: Seq[Int]): String = values.zipWithIndex.map { case(v,i) =>
          if(i<33) expected=expected.updated(i,v)
          byte(v,i<33)
        }.mkString
        def take(length: Int,overflow: Boolean): String = {
          framePhase=if(click) 1-framePhase else 1; delivered+=1
          s"""wait(frame_req==$framePhase); #2;
            ${frame(expected,length,overflow,false,false,73,s"SERIAL_$delivered")}
            ${memory(c,expected,s"SERIAL_$delivered")}
            ${release(click,"frame",framePhase)}
            #200000000;
            if(delivered_frame!=$delivered) $$fatal(1,"I2C_BYTE_SERIAL_COUNT");
          """
        }
        val full=start+data((0 until 33).map(i=>(i*37+9)&255))+edge(stop=true)+take(33,false)
        val short=start+data(Seq(0xa3,0x5c))+edge(stop=true)+take(2,false)
        val partial=start+data(Seq(0xe1))+
          Seq(true,false,true).map(b=>edge(rise=true,sda=b)+edge(fall=true)).mkString+
          edge(stop=true)+take(1,true)
        val timeout=start+data(Seq(0x24,0x42))+edge(timeout=true)+
          s"if(delivered_frame!=$delivered || frame_req!=frame_ack) $$fatal(1,\"I2C_BYTE_TIMEOUT_FRAME\");"+
          memory(c,expected,"AFTER_TIMEOUT")
        val rejected=edge(start=true)+byte(0x68,false)+byte(0xff,false)+edge(stop=true)+
          s"if(delivered_frame!=$delivered || frame_req!=frame_ack) $$fatal(1,\"I2C_BYTE_REJECTED_FRAME\");"+
          memory(c,expected,"AFTER_REJECTION")
        val afterTimeout=start+data(Seq(0x96))+edge(stop=true)+take(1,false)
        val overflow=start+data((0 until 34).map(i=>(i*17+3)&255))+edge(stop=true)+take(33,true)
        s"""begin
          ${monitors(c,qualified=false)}
          ${if(click) "start=1;" else ""}
          $full $short $partial $timeout $rejected $afterTimeout $overflow
          if(delivered_snapshot!=0) $$fatal(1,"I2C_BYTE_SERIAL_UNEXPECTED_SNAPSHOT");
        end"""
      }
    }
  }
}
