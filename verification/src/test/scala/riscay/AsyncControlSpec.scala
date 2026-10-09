// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import java.util.zip.CRC32
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Independent byte-frame/state oracle, exercised with no periodic clock. */
class AsyncControlSpec extends AnyFunSuite {
  private val config = McuConfiguration(12, 12, 1, Vector(MeasurementChannel(0,"test",1,0)),
    ApplicationProfile(1,1,"control",Vector(HostRegister(0,"A"),HostRegister(17,"B")),Vector.empty))
  private val p = SocParameters(config)
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickControl(p,new ResetDomain("root"))
    else new riscay.bd.FourPhaseControl(p,new ResetDomain("root"))
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
    "loaderPending"->0L,"loaderWord"->0L,"selector"->0L,"sampleIndex"->0L,"sampleValue"->0L,"appIndex"->0L)
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
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native MMIO/loader: full-width validation, retained accounting, lock, reset commands and stalls") {
      val steps=campaign
      AsyncTest.run(top(click),1L to 16L,fresh(name)) { _ => s"""
        ${if(click) "start=1;" else ""}
        fork begin ${source(click,steps)} end begin ${sink(click,steps)} end join
        #1000000000;
        if(delivered_reply != ${steps.size}) $$fatal(1,"CONTROL_EXACTLY_ONCE");
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
