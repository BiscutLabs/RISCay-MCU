// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chiselasync.core.ResetDomain
import chiselasync.metadata.ClickTiming
import chiselasync.testing.AsyncTest
import chiselasync.testing.AsyncTest.{Input, Output}
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.click.{ClickFork, ClickJoin}

class NativeRoutingSpec extends AnyFunSuite {
  private def fresh(name: String) = {
    val root=Paths.get("build/routing-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private val words = Seq(0,0,255,255,1,128,0,19,19,7) ++ (0 until 30).map(i => (i*73)&255)
  test("native phase fork delivers exactly once to consumers with independent stalls") {
    AsyncTest.check(new ClickFork(UInt(8.W),new ResetDomain("root")),
      Seq(Input.literals("in",words.map(_.U(8.W)))),
      Seq(Output.literals("left",words.map(_.U(8.W))),Output.literals("right",words.map(_.U(8.W)))),
      1L to 24L,fresh("fork"))
  }
  test("native phase join pairs independently stalled operands by transaction number") {
    val other=words.reverse
    AsyncTest.check(new ClickJoin(UInt(8.W),UInt(8.W),ClickTiming.Simulation,new ResetDomain("root")),
      Seq(Input.literals("left",words.map(_.U(8.W))),Input.literals("right",other.map(_.U(8.W)))),
      Seq(Output("out",words.zip(other).map { case(a,b) => Map("out_bits_left"->BigInt(a),"out_bits_right"->BigInt(b)) })),
      1L to 24L,fresh("join"))
  }
  test("native phase join discards a lone operand on reset before accepting a fresh pair") {
    AsyncTest.run(new ClickJoin(UInt(8.W),UInt(8.W),ClickTiming.Simulation,new ResetDomain("root")),
      Seq(1,19,81),fresh("join-reset"))(_ => """
      left_bits=51; #100000000; left_req=1; wait(left_ack); #300000000;
      if(out_req) $fatal(1,"JOIN_UNPAIRED_OUTPUT");
      reset=1; left_req=0; right_req=0; out_ack=0;
      #1000000000; reset=0; #1000000000;
      fork
        begin left_bits=7; #100000000; left_req=1; wait(left_ack); end
        begin right_bits=9; #200000000; right_req=1; wait(right_ack); end
        begin wait(out_req); #100000000;
          if(out_bits_left !== 8'd7 || out_bits_right !== 8'd9) $fatal(1,"JOIN_RESET_PAIR");
          out_ack=1;
        end
      join
      #1000000000; if(delivered_out != 1) $fatal(1,"JOIN_RESET_COUNT");
      """)
  }
}
