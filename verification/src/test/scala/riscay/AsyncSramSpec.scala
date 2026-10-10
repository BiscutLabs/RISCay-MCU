// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Clockless oracle: byte endpoints respond only after observing the actual
  * native command. Expected memory bytes are maintained independently in Scala.
  */
class AsyncSramSpec extends AnyFunSuite {
  private case class Tx(address: Long, write: Boolean, data: Long, mask: Int, result: Long)
  private val txs = {
    val memory = collection.mutable.Map.empty[Long, Long].withDefaultValue(0L)
    val result = collection.mutable.ArrayBuffer.empty[Tx]
    for(i <- 0 until 32) {
      val address = Seq(0x3fcL,0x400L,0x7fcL)(i%3)
      val value = (0xdeadbeefL ^ (i*0x10204081L)) & 0xffffffffL
      val mask = i%16
      for(b <- 0 until 4 if (mask & (1<<b)) != 0) memory(address+b) = (value >> (8*b)) & 255
      result += Tx(address+(i%4),true,value,mask,0)
      val expected = (0 until 4).map(b => memory(address+b) << (8*b)).reduce(_ | _)
      result += Tx(address,false,0,15,expected)
    }
    result.toSeq
  }
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickSram(new ResetDomain("root"))
    else new riscay.bd.FourPhaseSram(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-sram-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def phase(click: Boolean,n: Int) = if(click) (n+1)%2 else 1
  private def source(click: Boolean, ts: Seq[Tx]) = ts.zipWithIndex.map { case(t,n) =>
    val p=phase(click,n)
    s"""
      request_bits_address=32'h${t.address.toHexString}; request_bits_write=${if(t.write) 1 else 0};
      request_bits_data=32'h${t.data.toHexString}; request_bits_mask=${t.mask};
      #1000000; request_req=$p; wait(request_ack == $p); #2000000;
      ${if(click) "" else "request_req=0; wait(!request_ack); #1000000;"}
    """
  }.mkString
  private def bytes(click: Boolean, ts: Seq[Tx], lane: Int, stop: Int = -1) = ts.zipWithIndex.map { case(t,n) =>
    val p=phase(click,n); val r=s"byteRequest_$lane"; val s=s"byteResponse_$lane"
    val value=(t.data >> (lane*8)) & 255; val answer=(t.result >> (lane*8)) & 255
    s"""
      wait(${r}_req == $p); #2000000;
      if(${r}_bits_address !== 32'h${((t.address & ~3L)+lane).toHexString} ||
         ${r}_bits_data !== 8'h${value.toHexString} || ${r}_bits_write !== ${if(t.write) 1 else 0} ||
         ${r}_bits_enable !== ${if(!t.write || (t.mask & (1<<lane)) != 0) 1 else 0})
        $$fatal(1,"SRAM_NATIVE_BYTE_${n}_$lane");
      ${if(stop == lane) "wait(reset);" else s"""
        #${(n%5+1)*31000000L}; ${r}_ack=$p;
        ${s}_bits=8'h${answer.toHexString}; #${(n%7+1)*37000000L}; ${s}_req=$p;
        fork
          begin wait(${s}_ack == $p); #17000000;
            ${if(click) "" else s"${s}_req=0; wait(!${s}_ack);"}
            #2000000; ${s}_bits=8'h5a;
          end
          begin ${if(click) "#1000000;" else s"wait(!${r}_req); #53000000; ${r}_ack=0;"} end
        join
      """}
    """
  }.mkString
  private def sink(click: Boolean, ts: Seq[Tx]) = "begin integer base0,base1,base2,base3; base0=delivered_byteRequest_0; base1=delivered_byteRequest_1; base2=delivered_byteRequest_2; base3=delivered_byteRequest_3; " + ts.zipWithIndex.map { case(t,n) =>
    val p=phase(click,n)
    s"""
      wait(response_req == $p); #2000000;
      repeat(10) begin #91000000;
        if(response_bits !== 32'h${t.result.toHexString}) $$fatal(1,"SRAM_NATIVE_RESULT_$n");
        ${(0 until 4).map(l => s"if(delivered_byteRequest_$l != base$l + ${n+1}) $$fatal(1,\"SRAM_WORD_OVERTAKE_${n}_$l\");").mkString("\n")}
      end
      response_ack=$p;
      ${if(click) "#2000000;" else "wait(!response_req); #73000000; response_ack=0; #2000000;"}
    """
  }.mkString + " end"
  private def campaign(click: Boolean, ts: Seq[Tx]) = s"""
    fork
      begin ${source(click,ts)} end
      begin ${sink(click,ts)} end
      ${(0 until 4).map(l => s"begin ${bytes(click,ts,l)} end").mkString("\n")}
    join
    #1000000000;
    ${(Seq("request","response") ++ (0 until 4).flatMap(l => Seq(s"byteRequest_$l",s"byteResponse_$l"))).map { p =>
      if(click) s"if(${p}_req !== ${p}_ack) $$fatal(1,\"SRAM_NATIVE_NOT_IDLE_$p\");"
      else s"if(${p}_req || ${p}_ack) $$fatal(1,\"SRAM_NATIVE_NOT_IDLE_$p\");"
    }.mkString("\n")}
  """
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native SRAM: all masks, bank boundaries, early next requests and independently stalled byte/word replies") {
      AsyncTest.run(top(click),1L to 16L,fresh(name+"-ordering")) { _ =>
        s"""${if(click) "start=1;" else ""}
          ${campaign(click,txs)}
          if(delivered_response != ${txs.size}) $$fatal(1,"SRAM_NATIVE_COMPLETION_COUNT");
        """
      }
    }
    test(s"$name native SRAM: POR at every byte and held word reply cancels ownership without replay") {
      for(abort <- 0 to 4; writing <- Seq(false,true)) {
        val tx=Seq(Tx(0x400,writing,0x12345678,15,if(writing) 0 else 0x89abcdefL))
        AsyncTest.run(top(click),Seq(1L,2L,19L),fresh(name+s"-por-$abort-$writing")) { _ =>
          s"""
            ${if(click) "start=1;" else ""}
            fork
              begin ${source(click,tx)} end
              ${(0 until 4).map(l => s"begin ${bytes(click,tx,l,abort)} end").mkString("\n")}
            join_none
            ${if(abort<4) s"wait(byteRequest_${abort}_req);" else "wait(response_req);"}
            #23000000; reset=1; disable fork;
            request_req=0; response_ack=0; ${if(click) "start=0;" else ""}
            ${(0 until 4).map(l => s"byteRequest_${l}_ack=0; byteResponse_${l}_req=0;").mkString("\n")}
            #1000000000; reset=0; #1000000000;
            if(response_req || request_ack) $$fatal(1,"SRAM_POR_STALE_WORD");
            ${(0 until 4).map(l => s"if(byteRequest_${l}_req || byteResponse_${l}_ack) $$fatal(1,\"SRAM_POR_REPLAY_$l\");").mkString("\n")}
            ${if(click) "start=1;" else ""}
            ${campaign(click,tx)}
          """
        }
      }
    }
  }
}
