// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Exercises the exact production CRC stage with an independent serial oracle. */
class AsyncCrcSpec extends AnyFunSuite {
  private val mask = 0xffffffffL
  private case class Input(crc: Long, word: Long, pending: Boolean)
  private def oracle(x: Input): Long = {
    var crc=x.crc
    if(x.pending) for(byte <- 0 until 4; bit <- 0 until 8) {
      val feedback=(crc ^ (x.word >>> (byte*8+bit))) & 1L
      crc=(crc >>> 1) ^ (if(feedback != 0) 0xedb88320L else 0L)
    }
    crc & mask
  }
  private def top(click: Boolean): AsyncModule = if(click)
    riscay.click.ClickCrc32.stage(new ResetDomain("root"))
    else riscay.bd.FourPhaseCrc32.stage(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-crc-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private val random=new scala.util.Random(0x43524332L)
  private val vectors=Seq(Input(0,0,true)) ++
    (0 until 32).flatMap(bit => Seq(Input(1L<<bit,0,true),Input(0,1L<<bit,true))) ++
    Seq(Input(mask,mask,true),Input(mask,0,true),Input(0,mask,true)) ++
    (0 until 32).map(bit => Input(1L<<bit,mask ^ (1L<<bit),false)) ++
    Seq.fill(64)(Input(random.nextInt().toLong & mask, random.nextInt().toLong & mask,true)) ++
    Seq.fill(16)(Input(random.nextInt().toLong & mask, random.nextInt().toLong & mask,false))

  private def transactions(click: Boolean, xs: Seq[Input]): String = xs.zipWithIndex.map { case(x,i) =>
    val phase=if(click) (i+1)%2 else 1
    val result=oracle(x).toHexString
    s"""
      in_bits_crc=32'h${x.crc.toHexString}; in_bits_word=32'h${x.word.toHexString};
      in_bits_pending=${if(x.pending) 1 else 0}; #2; in_req=$phase;
      wait(in_ack == $phase); #2;
      ${if(click) "in_bits_crc=32'hdeadbeef; in_bits_word=32'h13579bdf; in_bits_pending=0;" else "in_req=0;"}
      ${if(click) "" else """
        fork
          begin
            wait(!in_ack); #1;
            in_bits_crc=32'hdeadbeef; in_bits_word=32'h13579bdf; in_bits_pending=0;
          end
          begin
      """}
      wait(out_req == $phase); #2;
      repeat(3) begin
        #${(i%7+1)*11000000L};
        if(out_bits !== 32'h$result) $$fatal(1,"CRC_STAGE_RESULT_$i actual=%h",out_bits);
      end
      out_ack=$phase;
      ${if(click) "#2;" else "wait(!out_req); #19000000; out_ack=0; #2; end join"}
    """
  }.mkString("\n")

  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name CRC: complete linear basis, bypass, full-width random, held results and earliest source reuse") {
      AsyncTest.run(top(click),1L to 16L,fresh(name)) { _ => s"""
        ${transactions(click,vectors)}
        #1000000000;
        if(delivered_out != ${vectors.size}) $$fatal(1,"CRC_STAGE_EXACTLY_ONCE");
      """ }
    }
    test(s"$name CRC: POR discards a held result and both native phase polarities restart") {
      AsyncTest.run(top(click),Seq(1L,2L,19L),fresh(name+"-por")) { _ => s"""
        in_bits_crc=32'hffffffff; in_bits_word=32'habcd1234; in_bits_pending=1;
        #2; in_req=1; wait(in_ack); wait(out_req); #37000000;
        reset=1; in_req=0; out_ack=0; #1000000000; reset=0; #1000000000;
        if(in_ack || out_req) $$fatal(1,"CRC_STAGE_STALE_AFTER_POR");
        ${transactions(click,vectors.take(3))}
        #1000000000;
      """ }
    }
  }
}
