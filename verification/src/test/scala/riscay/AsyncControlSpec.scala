// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import java.util.zip.CRC32
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Independent byte-frame/state oracle, exercised with no periodic clock. */
class AsyncControlSpec extends AnyFunSuite {
  private val config = McuConfiguration(12, 12, 1, Vector(MeasurementChannel(0,"test",1,0)),
    ApplicationProfile(1,1,"control",Vector(HostRegister(0,"A"),HostRegister(17,"B")),Vector.empty))
  private val p = SocParameters(config)
  private def top(click: Boolean, parameters: SocParameters = p): AsyncModule = if(click)
    new riscay.click.ClickControl(parameters,new ResetDomain("root"))
    else new riscay.bd.FourPhaseControl(parameters,new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-control-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private case class Step(kind: Int, bytes: Seq[Int] = Seq.empty, memory: (Int,Long,Long,Int) = (0,0,0,0),
    snapshot: Long = 0, changes: Map[String,Long] = Map.empty, error: Int = 0, data: Long = 0,
    write: Int = 0, wake: Int = 0, period: Long = 0)
  private def frame(op: Int, words: Long*) = Seq(op) ++ words.flatMap(w => (0 until 4).map(i => ((w >>> (8*i)) & 255).toInt))
  private val initial = Map("mode"->0L,"programmed"->0L,"locked"->0L,"started"->0L,"lastError"->0L,
    "imageLength"->0L,"entry"->0L,"received"->0L,"imageId"->0L,"expectedCrc"->0L,"crc"->0xffffffffL,
    "loaderPending"->0L,"loaderWord"->0L,"bootSession"->0L,"bootIndex"->0L,
    "loaderHold"->0L,"persistPending"->0L,"persisted"->0L,
    "selector"->0L,"sampleIndex"->0L,"sampleValue"->0L,"appIndex"->0L)
  private def campaign: Seq[Step] = {
    val words=Seq(0x89abcdefL,0x12345678L,0x00000073L)
    val checksum=new CRC32
    val partial=words.map { w => (0 until 4).foreach(i => checksum.update(((w >>> (8*i)) & 255).toInt)); checksum.getValue ^ 0xffffffffL }
    val crc=checksum.getValue
    def host(op: Int, changes: Map[String,Long] = Map.empty) = Step(0,frame(op),changes=changes)
    def mmio(op: Int, offset: Int, value: Long = 0, mask: Int = 15, error: Int = 0,
        data: Long = 0, changes: Map[String,Long] = Map.empty) =
      Step(4,memory=(op,0x30000000L+offset,value,mask),error=error,data=data,changes=changes)
    val steps = Seq(
      Step(0,frame(1,0x8000000cL,0,crc,0x10000L,0,0,0,7),changes=Map("lastError"->4L)),
      Step(0,frame(1,12,0x80000000L,crc,0x10000L,0,0,0,7),changes=Map("lastError"->4L)),
      Step(0,frame(1,12,8,crc,0x10000L,12,1,1,7),changes=Map("lastError"->0L,"mode"->1L,
        "imageLength"->12L,"entry"->8L,"expectedCrc"->crc,"imageId"->7L)),
      host(3,Map("lastError"->7L))) ++ words.zipWithIndex.flatMap { case(w,i) =>
      Seq(Step(0,frame(2,i*4L,w),changes=Map("lastError"->0L,"loaderPending"->1L,"loaderWord"->w),write=1),
        host(3,Map("lastError"->3L)),
        Step(2), // Watchdog reset cannot erase pending accepted SRAM accounting.
        Step(1,changes=Map("loaderPending"->0L,"received"->((i+1)*4L),"crc"->partial(i))),
        Step(1), // A duplicate completion must not add a second word.
        Step(0,frame(2,0x80000000L+i*4L,99),changes=Map("lastError"->4L)))
    } ++ Seq(
      host(3,Map("lastError"->0L,"programmed"->1L,"mode"->2L)),
      host(6,Map("locked"->1L,"started"->1L,"mode"->3L)),
      mmio(1,0,data=0x10000008L),
      Step(0,frame(1,12,8,crc,0x10000L,12,1,1,7),changes=Map("lastError"->2L)),
      mmio(2,36,0), mmio(2,40,0xdeadbeefL,changes=Map("sampleValue"->0xdeadbeefL)),
      mmio(1,40,data=0xdeadbeefL), mmio(2,36,0x10000000L,error=1),
      mmio(2,48,17,changes=Map("appIndex"->17L)), mmio(1,48,data=17),
      mmio(2,48,0x80000011L,error=1), mmio(2,52,123,error=1),
      Step(4,memory=(1,0x30000034L,0,15),snapshot=0x76543210L,data=0x76543210L),
      Step(2,changes=Map("started"->0L,"mode"->2L,"appIndex"->0L)),
      mmio(1,40,data=0xdeadbeefL), mmio(1,0,error=1,data=0x10000008L),
      host(5,Map("lastError"->0L,"started"->1L,"mode"->3L)),
      Step(3,changes=Map("mode"->4L)),
      Step(2,changes=Map("started"->0L,"mode"->2L)),
      Step(0,Seq(0,1,0,4),changes=Map("selector"->0x010004L)),
      Step(0,frame(8),wake=1), Step(0,frame(7,1),changes=Map("lastError"->4L),period=1),
      Step(0,frame(7,0xffffffffL),changes=Map("lastError"->4L),period=0xffffffffL)) ++
      (0 until 15).flatMap(mask => Seq(mmio(1,0,mask=mask,error=1),mmio(1,16,mask=mask,error=1))) ++
      Seq(mmio(0,4,error=1),mmio(2,60,100,error=1),mmio(2,32,0,error=1),mmio(2,32,0x57444f47L))
    steps.flatMap { s =>
      if(s.kind == 4 && s.memory._1 == 2 && s.error == 0)
        Seq(s.copy(changes=Map.empty),s.copy(kind=5))
      else Seq(s)
    }
  }
  private def crcCampaign: Seq[Step] = {
    val random = new scala.util.Random(0x435243L)
    Seq(Seq.fill(32)(0L), Seq.fill(32)(0xffffffffL),
      Seq(0L,0xffffffffL,0x80000000L,1L) ++ Seq.fill(28)(random.nextInt().toLong & 0xffffffffL)).flatMap { words =>
      val oracle = new CRC32
      val partial = words.map { w =>
        (0 until 4).foreach(b => oracle.update(((w >>> (8*b)) & 255).toInt))
        oracle.getValue ^ 0xffffffffL
      }
      Seq(Step(1), Step(0,frame(1,128,0,oracle.getValue,0x10000L,0,0,0,19),changes=Map(
        "mode"->1L,"programmed"->0L,"imageLength"->128L,"entry"->0L,"received"->0L,
        "imageId"->19L,"expectedCrc"->oracle.getValue,"crc"->0xffffffffL))) ++
      words.zipWithIndex.flatMap { case(w,i) => Seq(
        Step(0,frame(2,i*4L,w),changes=Map("loaderPending"->1L,"loaderWord"->w),write=1),
        Step(1,changes=Map("loaderPending"->0L,"received"->((i+1)*4L),"crc"->partial(i))),
        Step(2), // Queued while Stored is executing: accounting precedes recovery.
        Step(1)) // Duplicate completion is inert.
      } ++ Seq(Step(0,frame(3),changes=Map("programmed"->1L,"mode"->2L)))
    }
  }
  /** Independent full-image oracle for inclusive loader counts and host validation. */
  private def capacityCampaign(capacity: Int, countBits: Int, entryBits: Int): Seq[Step] = {
    val words = (0 until capacity/4).map(i => (0x89abcdefL ^ (i.toLong * 0x10203041L)) & 0xffffffffL)
    val oracle = new CRC32
    val partial = words.map { word =>
      (0 until 4).foreach(i => oracle.update(((word >>> (8*i)) & 255).toInt))
      oracle.getValue ^ 0xffffffffL
    }
    val checksum = oracle.getValue
    def begin(length: Long, entry: Long, changes: Map[String,Long]) =
      Step(0,frame(1,length,entry,checksum,0x10000L,0,0,0,capacity),changes=changes)
    val rejected = Map("lastError" -> 4L)
    val badBegins = Seq(begin(0,0,rejected), begin(capacity-1,0,rejected),
      begin(capacity+4L,0,rejected), begin(capacity,capacity,rejected), begin(capacity,1,rejected)) ++
      (countBits until 32).map(bit => begin(capacity.toLong | (1L << bit),0,rejected)) ++
      (entryBits until 32).map(bit => begin(capacity,1L << bit,rejected))
    val accepted = begin(capacity,capacity-4L,Map("lastError"->0L,"mode"->1L,
      "imageLength"->capacity.toLong,"entry"->(capacity-4L),"expectedCrc"->checksum,
      "imageId"->capacity.toLong))
    val badOffsets = (countBits until 32).map(bit =>
      Step(0,frame(2,1L << bit,0xdeadbeefL),changes=rejected))
    badBegins ++ Seq(accepted) ++ badOffsets ++ words.zipWithIndex.flatMap { case(word,index) =>
      Seq(Step(0,frame(2,index*4L,word),changes=Map("lastError"->0L,
          "loaderPending"->1L,"loaderWord"->word),write=1),
        Step(2), // Reset between accepted word and Stored must retain accounting.
        Step(1,changes=Map("loaderPending"->0L,"received"->((index+1)*4L),"crc"->partial(index))),
        Step(1)) // Duplicate Stored cannot wrap or advance the completed count.
    } ++ Seq(
      Step(0,frame(2,capacity,0),changes=rejected),
      Step(0,frame(3),changes=Map("lastError"->0L,"programmed"->1L,"mode"->2L))) ++
      badBegins ++ Seq( // Invalid BEGIN cannot damage the previously validated image.
        Step(0,frame(6),changes=Map("lastError"->0L,"locked"->1L,"started"->1L,"mode"->3L)),
        Step(4,memory=(1,0x30000000L,0,15),data=0x10000000L+capacity-4L),
        Step(2,changes=Map("started"->0L,"mode"->2L)),
        begin(capacity,0,Map("lastError"->2L)))
  }
  private def capacitySchema(directory: Path, click: Boolean, countBits: Int, entryBits: Int,
      stateBits: Int, tokenBits: Int, replyBits: Int, entryLo: Int, lengthLo: Int, errorLo: Int): Unit = {
    val root=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    def child(n: ujson.Value, id: String): ujson.Value = {
      val xs=n("children").arr.filter(_("id").str==id)
      require(xs.size==1,s"CAPACITY_CHILD:$id"); xs.head("contract")
    }
    // Offsets of the resized fields come from the explicit capacity table below.
    val state=Seq(("appIndex",0,6),("sampleValue",6,32),("sampleIndex",38,4),
      ("selector",42,24),("persisted",66,1),("persistPending",67,1),("loaderHold",68,1),
      ("bootIndex",69,4),("bootSession",73,1),("loaderWord",74,32),("loaderPending",106,1),("crc",107,32),
      ("expectedCrc",139,32),("imageId",171,32),("received",203,countBits),
      ("entry",entryLo,entryBits),("imageLength",lengthLo,countBits),("lastError",errorLo,8),
      ("started",errorLo+8,1),("locked",errorLo+9,1),("programmed",errorLo+10,1),("mode",errorLo+11,3))
    require(state.map(_._3).sum==stateBits && errorLo+14==stateBits,"CAPACITY_ORACLE_STATE")
    val token=Seq(("pendingCrc",0,32))++state.map { case(n,l,w)=>("state."+n,l+32,w) }
    val reply=Seq(("memory.error",0,1),("memory.data",1,32),("hostWake",33,1),
      ("period",34,32),("periodUpdate",66,1),("programWrite",67,1))++
      state.map { case(n,l,w)=>("state."+n,l+68,w) }++Seq(("kind",replyBits-3,3))
    def check(n: ujson.Value, id: String, expected: Seq[(String,Int,Int)], width: Int): Unit = {
      val channels=n("channels").arr.filter(_("id").str==id)
      require(channels.size==1,s"CAPACITY_CHANNEL:$id")
      val actual=channels.head("layout").arr.map { f =>
        require(!f("signed").bool,s"CAPACITY_UNSIGNED:$id")
        require(f("source").str==s"~|${n("module").str}>$id.${f("field").str}",s"CAPACITY_SOURCE:$id")
        (f("field").str,f("lsb").num.toInt,f("width").num.toInt)
      }.toSeq
      require(actual==expected.map { case(f,l,w)=>("bits."+f,l,w) },s"CAPACITY_LAYOUT:$id")
      require(actual.map(_._3).sum==width,s"CAPACITY_WIDTH:$id")
    }
    check(root,"reply",reply,replyBits)
    check(child(root,"update"),"out",reply,replyBits)
    check(child(root,"state"),"out",token,tokenBits)
    val left=child(child(root,"join"),if(click) "left_storage" else "left")
    check(left,"in",token,tokenBits); check(left,"out",token,tokenBits)
  }
  private def source(click: Boolean, steps: Seq[Step]): String = steps.zipWithIndex.map { case(s,i) =>
    val phase=if(click) (i+1)%2 else 1
    val bytes=s.bytes.padTo(33,0).zipWithIndex.map { case(v,j) => s"command_bits_frame_bytes_$j=$v;" }.mkString("\n")
    s"""command_bits_kind=${s.kind}; command_bits_frame_length=${s.bytes.size};
      command_bits_frame_overflow=0; $bytes
      command_bits_memory_operation=${s.memory._1}; command_bits_memory_address=32'h${s.memory._2.toHexString};
      command_bits_memory_data=32'h${s.memory._3.toHexString}; command_bits_memory_mask=${s.memory._4};
      command_bits_peripheralData=32'h${s.snapshot.toHexString};
      #2; command_req=$phase; wait(command_ack == $phase); #2;
      ${if(click) "" else "command_req=0; wait(!command_ack); #2;"}
    """
  }.mkString("\n")
  private def sink(click: Boolean, steps: Seq[Step]): String = {
    var expected=initial
    steps.zipWithIndex.map { case(s,i) =>
      expected ++= s.changes
      val phase=if(click) (i+1)%2 else 1
      val fields=expected.toSeq.sortBy(_._1).map { case(k,v) =>
        s"if(reply_bits_state_$k !== 32'h${v.toHexString}) $$fatal(1,\"CONTROL_STATE_${i}_$k actual=%h\",reply_bits_state_$k);"
      }.mkString("\n")
      s"""wait(reply_req == $phase); #${(i%5+1)*17000000L};
        $fields
        if(reply_bits_kind !== ${s.kind} || reply_bits_programWrite !== ${s.write} || reply_bits_hostWake !== ${s.wake} ||
           reply_bits_periodUpdate !== 0 || reply_bits_period !== 32'h${s.period.toHexString} ||
           reply_bits_memory_error !== ${s.error} || reply_bits_memory_data !== 32'h${s.data.toHexString})
          $$fatal(1,"CONTROL_REPLY_$i");
        reply_ack=$phase;
        ${if(click) "#2;" else "wait(!reply_req); #23000000; reply_ack=0; #2;"}
      """
    }.mkString("\n")
  }
  for(bypass <- Seq("none","both","fall")) {
    test(s"BD Control actual both-edge ACK guard with immediate source reuse; bypass=$bypass") {
      val directory=fresh("bd-ack-"+bypass)
      val steps=campaign
      def run(): Unit = AsyncTest.run(top(false),if(bypass!="none") Seq(1L) else Seq(1L,2L,19L),directory) { _ =>
        val root=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
        val guards=root("primitives").arr.filter(_("id").str=="acknowledge_guard")
        require(guards.size==1 && guards.head("parameters")("DELAY_FS").str=="32000000","CONTROL_ACK_BINDING")
        val guard="dut."+guards.head("rtl_path").str.split('.').drop(1).mkString(".")
        s"""
        ${if(bypass=="both") s"force $guard.q=$guard.a;" else ""}
        fork
          begin ${source(false,steps)} end
          begin ${sink(false,steps)} end
          begin : ack_monitor
            time changed;
            integer n;
            for(n=0;n<${steps.size};n=n+1) begin
              @(posedge $guard.a); changed=$$time; wait($guard.q);
              if($$time-changed < 32000000) $$fatal(1,"CONTROL_ACK_RISE_EARLY");
              @(negedge $guard.a); changed=$$time;
              ${if(bypass=="fall") s"force $guard.q=$guard.a;" else ""}
              wait(!$guard.q);
              if($$time-changed < 32000000) $$fatal(1,"CONTROL_ACK_FALL_EARLY");
            end
          end
        join
        #1000000000;
        if(delivered_reply != ${steps.size}) $$fatal(1,"CONTROL_ACK_EXACTLY_ONCE");
        """
      }
      if(bypass!="none") {
        val error=intercept[IllegalArgumentException](run())
        assert(error.getMessage.contains(if(bypass=="fall") "CONTROL_ACK_FALL_EARLY" else "CONTROL_ACK_RISE_EARLY"),error.getMessage)
      } else run()
    }
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    for((capacity,countBits,entryBits,stateBits,tokenBits,replyBits,entryLo,lengthLo,errorLo) <- Seq(
        (4,3,2,225,257,296,206,208,211), (12,4,4,229,261,300,207,211,215),
        (1024,11,10,249,281,320,214,224,235), (1028,11,11,250,282,321,214,225,236),
        (2048,12,11,252,284,323,215,226,238), (3072,12,12,253,285,324,215,227,239))) {
      test(s"$name native loader retains full-capacity $capacity-byte accounting without host truncation") {
        val steps=capacityCampaign(capacity,countBits,entryBits)
        val directory=fresh(name+s"-capacity-$capacity")
        AsyncTest.run(top(click,p.copy(config=config.copy(programBytes=capacity))),
          Seq(1L,19L),directory) { _ =>
          capacitySchema(directory,click,countBits,entryBits,stateBits,tokenBits,replyBits,entryLo,lengthLo,errorLo)
          s"""
          ${if(click) "start=1;" else ""}
          fork begin ${source(click,steps)} end begin ${sink(click,steps)} end join
          #1000000000;
          if(delivered_reply != ${steps.size}) $$fatal(1,"CAPACITY_EXACTLY_ONCE");
        """ }
      }
    }
    test(s"$name native MMIO/loader: full-width validation, retained accounting, lock, reset commands and stalls") {
      val steps=campaign
      AsyncTest.run(top(click),1L to 16L,fresh(name)) { _ => s"""
        ${if(click) "start=1;" else ""}
        fork begin ${source(click,steps)} end begin ${sink(click,steps)} end join
        #1000000000;
        if(delivered_reply != ${steps.size}) $$fatal(1,"CONTROL_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native CRC: independent all-zero/all-one/random images, queued recovery and duplicate Stored") {
      val steps=crcCampaign
      AsyncTest.run(top(click,p.copy(config=config.copy(programBytes=128))),Seq(1L,2L,3L,7L,19L),fresh(name+"-crc")) { _ => s"""
        ${if(click) "start=1;" else ""}
        fork begin ${source(click,steps)} end begin ${sink(click,steps)} end join
        #1000000000;
        if(delivered_reply != ${steps.size}) $$fatal(1,"CRC_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native CRC: POR after actual capture before publication aborts pending accounting") {
      val before=Seq(Step(0,frame(1,4,0,0,0x10000L,0,0,0,1),changes=Map(
        "mode"->1L,"imageLength"->4L,"imageId"->1L)))
      val after=Seq(Step(1),Step(0,frame(3),changes=Map("lastError"->6L)))
      val directory=fresh(name+"-crc-por")
      AsyncTest.run(top(click),Seq(1L,2L,19L),directory) { _ =>
        val root=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
        val nodes=root("children").arr.filter(_("id").str == "crc")
        require(nodes.size == 1, "CRC_POR_CHILD_BINDING")
        val payloads=nodes.head("contract")("primitives").arr.filter(_("id").str == "payload")
        require(payloads.size == 1, "CRC_POR_PAYLOAD_BINDING")
        val payload=payloads.head
        require(payload("model").str == (if(click) "ChiselAsyncEventRegister_v1" else "ChiselAsyncClosingLatch_v1"),
          "CRC_POR_CAPTURE_KIND")
        val capture="dut."+payload("rtl_path").str.split('.').drop(1).mkString(".")+(if(click) ".trigger" else ".closed")
        s"""
        ${if(click) "start=1;" else ""}
        fork begin ${source(click,before)} end begin ${sink(click,before)} end join
        #1000000000;
        command_bits_kind=0; command_bits_frame_length=9; command_bits_frame_bytes_0=2;
        command_bits_frame_bytes_1=0; command_bits_frame_bytes_2=0; command_bits_frame_bytes_3=0; command_bits_frame_bytes_4=0;
        command_bits_frame_bytes_5=1; command_bits_frame_bytes_6=239; command_bits_frame_bytes_7=205; command_bits_frame_bytes_8=171;
        #2; command_req=${if(click) 0 else 1};
        @(posedge $capture); #1;
        if(dut.ca_child_crc.out_req == ${if(click) 0 else 1}) $$fatal(1,"CRC_ALREADY_COMPLETED");
        reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
        #1000000000; reset=0; #1000000000; ${if(click) "start=1;" else ""}
        fork begin ${source(click,after)} end begin ${sink(click,after)} end join
        #1000000000;
      """ }
    }
    test(s"$name native MMIO/loader: POR cancels a stalled reply and reinstalls cold state") {
      val steps=Seq(Step(0,Seq(0,1,0,7),changes=Map("selector"->0x010007L)))
      val after=Seq(Step(0,frame(3),changes=Map("lastError"->6L)))
      AsyncTest.run(top(click),Seq(1L,2L,19L),fresh(name+"-por")) { _ => s"""
        ${if(click) "start=1;" else ""}
        ${source(click,steps)} wait(reply_req); #100000000;
        reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
        #1000000000; reset=0; #1000000000; ${if(click) "start=1;" else ""}
        fork begin ${source(click,after)} end begin ${sink(click,after)} end join
        #1000000000;
      """ }
    }
  }
}
