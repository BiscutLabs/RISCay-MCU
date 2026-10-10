// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc.AdcParameters

/** Clockless conversion oracle. Each edge observation is packed independently
  * of the implementation's shift register and field extraction expression.
  */
class AsyncSpiAdcSpec extends AnyFunSuite {
  private val p=AdcParameters(2,100,25300,4095,offset = -100,calibrated=true)
  private case class Frame(word: Int,complete: Boolean = true)
  private val frames=Seq(Frame(0xaabc,false),Frame(0xffff,false),Frame(0xf000)) ++
    (0 until 16).map(n => Frame((n<<12) | Seq(0,4095,0xaaa,0x555)(n%4))) ++
    (0 until 12).flatMap(b => Seq(Frame(0xa000 | (1<<b)),Frame(0x5000 | (4095 ^ (1<<b))))) ++
    Seq(Frame(0xc321,false),Frame(0xf678))
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickSpiAdc(p,new ResetDomain("root"))
    else new riscay.bd.FourPhaseSpiAdc(p,new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-spi-adc-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def phase(click: Boolean,n: Int) = if(click) (n+1)%2 else 1
  private def trace(f: Frame,n: Int): Long = (0 until 32).foldLeft(0L) { (v,edge) =>
    val bit=if(edge%2==0) (f.word >> (15-edge/2)) & 1 else (n+edge/2)%2
    v | (bit.toLong << edge)
  }
  private def source(click: Boolean,fs: Seq[Frame]) = fs.indices.map { n =>
    val q=phase(click,n)
    s"""command_bits=1; #1000000; command_req=$q; wait(command_ack == $q); #2000000;
      ${if(click) "" else "command_req=0; wait(!command_ack); #2000000;"}
    """
  }.mkString
  private def wire(click: Boolean,fs: Seq[Frame]) = fs.zipWithIndex.map { case(f,n) =>
    val q=phase(click,n)
    s"""
      wait(wave_req == $q); #${(n%7+1)*19000000L};
      if(!wave_bits || program_initialCsN || program_initialSclk ||
         program_occupied !== 32'hffffffff || program_csN !== 32'h80000000 || program_sclk !== 32'h55555555)
        $$fatal(1,"SPI_NATIVE_RECIPE_$n");
      wave_ack=$q;
      capture_bits_samples=32'h${trace(f,n).toHexString}; capture_bits_complete=${if(f.complete) 1 else 0};
      #${(n%5+1)*31000000L}; capture_req=$q;
      fork
        begin wait(capture_ack == $q); #41000000;
          ${if(click) "" else "capture_req=0; wait(!capture_ack);"}
          #2000000; capture_bits_samples=32'hdeadbeef; capture_bits_complete=0;
        end
        begin ${if(click) "#2000000;" else "wait(!wave_req); #73000000; wave_ack=0;"} end
      join
    """
  }.mkString
  private def sink(click: Boolean,fs: Seq[Frame]) = {
    var primed=false
    "begin integer base; base=delivered_wave; " + fs.zipWithIndex.map { case(f,n) =>
      val q=phase(click,n); val publish=primed && f.complete; primed ||= f.complete
      val value=(BigInt(f.word & 4095)*p.numerator/p.denominator+p.offset) & BigInt("ffffffff",16)
      s"""
        wait(reply_req == $q);
        repeat(10) begin #97000000;
          if(reply_bits_value !== 32'h${value.toString(16)} || reply_bits_publish !== ${if(publish) 1 else 0} ||
             reply_bits_nextPrimed !== ${if(primed) 1 else 0}) $$fatal(1,"SPI_NATIVE_RESULT_$n");
          if(delivered_wave != base+${n+1}) $$fatal(1,"SPI_NATIVE_OVERTAKE_$n");
        end
        reply_ack=$q;
        ${if(click) "#2000000;" else "wait(!reply_req); #61000000; reply_ack=0; #2000000;"}
      """
    }.mkString + " end"
  }
  private def campaign(click: Boolean,fs: Seq[Frame]) = s"""
    fork begin ${source(click,fs)} end begin ${wire(click,fs)} end begin ${sink(click,fs)} end join
    #1000000000;
    ${Seq("command","wave","capture","reply").map(c => if(click)
      s"if(${c}_req !== ${c}_ack) $$fatal(1,\"SPI_NATIVE_IDLE_$c\");" else
      s"if(${c}_req || ${c}_ack) $$fatal(1,\"SPI_NATIVE_IDLE_$c\");").mkString("\n")}
  """
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native SPI: clockless frame assembly, priming, arithmetic and independent channel stalls") {
      AsyncTest.run(top(click),1L to 16L,fresh(name+"-frames")) { _ => s"""
        ${if(click) "start=1;" else ""}
        ${campaign(click,frames)}
        if(delivered_reply != ${frames.size} || delivered_wave != ${frames.size}) $$fatal(1,"SPI_NATIVE_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native SPI: POR at wave, captured frame, arithmetic and held reply cancels and reprimes") {
      for(abort <- 0 until 4) {
        AsyncTest.run(top(click),Seq(1L,7L,19L),fresh(name+s"-por-$abort")) { _ => s"""
          ${if(click) "start=1;" else ""}
          fork
            begin ${source(click,Seq(Frame(0xffff)))} end
            begin ${if(abort==0) "wait(wave_req);" else wire(click,Seq(Frame(0xffff)))} end
          join_none
          ${Seq("wait(wave_req);", "wait(dut.ca_child_captured.out_req);",
            "wait(dut.ca_child_scale.command_req);", "wait(reply_req);")(abort)}
          #1; reset=1; disable fork;
          command_req=0; wave_ack=0; capture_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
          #1000000000; reset=0; #1000000000;
          if(wave_req || reply_req || command_ack || capture_ack) $$fatal(1,"SPI_NATIVE_POR_REPLAY");
          ${if(click) "start=1;" else ""}
          ${campaign(click,Seq(Frame(0xaaaa,false),Frame(0xffff),Frame(0x1234)))}
        """ }
      }
    }
  }
}
