// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Independent wide-integer oracles, with no service clock in the fixture. */
class AsyncScalingSpec extends AnyFunSuite {
  private val micros = Seq(1,999,129354,83333,200000)
  private val mask = BigInt("ffffffff",16)
  private def fresh(name: String) = {
    val root=Paths.get("build/async-scaling-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def elapsed(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickElapsed(micros,new ResetDomain("root"))
    else new riscay.bd.FourPhaseElapsed(micros,new ResetDomain("root"))
  private def source(click: Boolean, values: Seq[Long]): String = values.zipWithIndex.map { case(v,i) =>
    val phase=if(click) (i+1)%2 else 1
    s"""command_bits=32'h${v.toHexString}; #2; command_req=$phase;
      wait(command_ack == $phase); #2;
      ${if(click) "" else "command_req=0; wait(!command_ack); #2;"}
    """
  }.mkString("\n")
  private def sink(click: Boolean, expected: Seq[Map[String,BigInt]]): String = expected.zipWithIndex.map { case(fields,i) =>
    val phase=if(click) (i+1)%2 else 1
    val checks=fields.toSeq.sortBy(_._1).map { case(k,v) =>
      s"if($k !== 32'h${v.toString(16)}) $$fatal(1,\"SCALING_${i}_$k actual=%h\",$k);"
    }.mkString("\n")
    s"""wait(reply_req == $phase); #2; $checks
      #${(i%7+1)*47000000L}; $checks reply_ack=$phase;
      ${if(click) "#2;" else "wait(!reply_req); #39000000; reply_ack=0; #2;"}
    """
  }.mkString("\n")
  private def elapsedExpected(deltas: Seq[Long]): (Seq[Long],Seq[Map[String,BigInt]]) = {
    var count=BigInt(0); val fractions=Array.fill(micros.size)(BigInt(0))
    val results=deltas.map { delta =>
      count=(count+delta)&mask
      val lanes=micros.indices.flatMap { lane =>
        val total=BigInt(delta)*micros(lane)+fractions(lane)
        fractions(lane)=total%1000
        Seq(s"reply_bits_state_fraction_$lane"->fractions(lane),s"reply_bits_elapsed_$lane"->((total/1000)&mask))
      }
      count.toLong -> (lanes.toMap ++ Map("reply_bits_state_consumed"->count,
        "reply_bits_single"->BigInt(if(delta==1) 1 else 0)))
    }
    (results.map(_._1),results.map(_._2))
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native elapsed: clockless fractions, zero increments, wrap and stalled publication") {
      val random=new scala.util.Random(0x454c4150L)
      val deltas=Seq(0L,1L,2L,0L,0xffffffffL,0x80000000L,1L) ++
        Seq.fill(32)(random.nextInt().toLong & 0xffffffffL) ++ Seq.fill(20)(1L)
      val (targets,expected)=elapsedExpected(deltas)
      AsyncTest.run(elapsed(click),1L to 16L,fresh(name+"-elapsed")) { _ => s"""
        ${if(click) "start=1;" else ""}
        fork begin ${source(click,targets)} end begin ${sink(click,expected)} end join
        #1000000000;
        if(delivered_reply != ${targets.size}) $$fatal(1,"ELAPSED_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native sample: clockless exact ratios and reply backpressure") {
      val random=new scala.util.Random(0x53414d50L)
      val raw=Seq(0L,1L,4095L,4094L,2048L) ++ Seq.fill(64)(random.nextInt(4096).toLong)
      for((n,d) <- Seq((25300,4095),(1000,4095),(7,1),(999983,2147483647))) {
        def top(): AsyncModule = if(click) new riscay.click.ClickSample(n,d,new ResetDomain("root"))
          else new riscay.bd.FourPhaseSample(n,d,new ResetDomain("root"))
        val expected=raw.map(x => Map("reply_bits"->((BigInt(x)*n/d)&mask)))
        AsyncTest.run(top(),Seq(1L,2L,3L,7L,19L),fresh(name+"-sample")) { _ => s"""
          fork begin ${source(click,raw)} end begin ${sink(click,expected)} end join
          #1000000000;
          if(delivered_reply != ${raw.size}) $$fatal(1,"SAMPLE_EXACTLY_ONCE");
        """ }
      }
    }
    test(s"$name native elapsed: POR aborts real arithmetic and a held reply then restores fractions") {
      for(held <- Seq(false,true)) {
        val (targets,expected)=elapsedExpected(Seq(1L,2L,1L))
        AsyncTest.run(elapsed(click),Seq(1L,2L,19L),fresh(name+"-por")) { _ => s"""
          ${if(click) "start=1;" else ""}
          command_bits=32'hffffffff; #2; command_req=1;
          ${if(held) "wait(reply_req); #100000000;" else "wait(dut.ca_child_prepare.out_req); #1; if(reply_req) $fatal(1,\"NOT_MID_ARITHMETIC\");"}
          reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
          #1000000000; reset=0; #1000000000; ${if(click) "start=1;" else ""}
          fork begin ${source(click,targets)} end begin ${sink(click,expected)} end join
          #1000000000;
        """ }
      }
    }
  }
}
