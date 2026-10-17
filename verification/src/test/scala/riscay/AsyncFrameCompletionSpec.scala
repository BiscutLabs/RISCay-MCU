// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.ResetDomain
import chiselasync.metadata.ExportDesign
import chiselasync.testing.Simulator
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import scala.jdk.CollectionConverters._

/** No clock: independently order both owners' acceptance and falling returns. */
class AsyncFrameCompletionSpec extends AnyFunSuite {
  private def fresh(label: String) = {
    val root=Paths.get("build/async-frame-completion-tests");Files.createDirectories(root)
    Files.createTempDirectory(root,label)
  }
  private val ack="{bankAck_3,bankAck_2,bankAck_1,bankAck_0}"
  // This is a raw-pin completion primitive, not an AsyncChannel producer.
  // Compile its public export and original timed models directly, without a
  // dummy channel or periodic clock. Every seed varies all 24 gate delays.
  private def run(label: String,seeds: Seq[Long])(body: => String): Unit = {
    val base=fresh(label).toAbsolutePath
    val export=base.resolve("export")
    ExportDesign.emit(new riscay.bd.FourPhaseFrameCompletion(new ResetDomain("root")),export)
    val node=ujson.read(Files.readString(export.resolve("contract.json")))("manifest")("design")
    val sources=Files.readAllLines(export.resolve("filelist.f")).asScala.filter(_.trim.nonEmpty)
      .map(s => export.resolve(s.trim).normalize.toString).toSeq
    val simulator=Simulator();simulator.check(base.resolve("simulator"))
    for(seed <- seeds) {
      val out=Files.createDirectory(base.resolve(s"seed-$seed"))
      val random=new scala.util.Random(seed)
      val delays=node("primitives").arr.map { p =>
        val path="dut."+p("rtl_path").str.split('.').drop(1).mkString(".")
        val delay=if(seed==1) 1000000L else if(seed==2) 10000000L else (1+random.nextInt(10))*1000000L
        s"defparam $path.DELAY_FS=$delay;"
      }.mkString("\n")
      val ports=Seq("reset","bank","host","commandAck")++(0 until 4).map(i=>s"receiptAck_$i")++
        (0 until 4).map(i=>s"bankAck_$i")
      Files.writeString(out.resolve("testbench.sv"),s"""
        `timescale 1fs/1fs
        module Testbench;
        reg reset=1,host=0,commandAck=0;
        reg [1:0] bank=0;
        ${(0 until 4).map(i=>s"reg receiptAck_$i=0; wire bankAck_$i;").mkString("\n")}
        FourPhaseFrameCompletion dut(${ports.map(p=>s".$p($p)").mkString(",")});
        $delays
        initial begin #100000000000; $$fatal(1,"FRAME_COMPLETION_DEADLINE");end
        initial begin #200000000; reset=0; #200000000;
          $body
          $$display("FRAME_COMPLETION_PASS"); $$finish;
        end
        endmodule
      """)
      def command(args: Seq[String],name: String): Unit = {
        val process=new ProcessBuilder(args:_*).directory(out.toFile).redirectErrorStream(true)
          .redirectOutput(out.resolve(name).toFile).start()
        if(!process.waitFor(60,java.util.concurrent.TimeUnit.SECONDS)) {
          process.destroyForcibly();fail("FRAME_COMPLETION_TIMEOUT: "+out)
        }
        require(process.exitValue()==0,s"FRAME_COMPLETION_FAILED: $out/$name\n"+Files.readString(out.resolve(name)))
      }
      command(Seq(simulator.iverilog,"-g2012","-s","Testbench","-o","sim.vvp")++sources++Seq("testbench.sv"),"compile.log")
      command(Seq(simulator.vvp,"sim.vvp"),"simulation.log")
      require(Files.readString(out.resolve("simulation.log")).contains("FRAME_COMPLETION_PASS"))
    }
  }
  test("BD frame completion retains every bank through both independent returns") {
    run("returns",1L to 24L) {
      (0 until 32).map { n =>
        val b=Seq(0,3,1,2)((n/4)%4);val bit=1<<b;val receipt=s"receiptAck_$b"
        s"""
          bank=$b;host=1;commandAck=0;$receipt=0;#200000000;
          if($ack!==0) $$fatal(1,"FRAME_COMPLETION_IDLE");
          ${if(n%2==0) s"$receipt=1;" else "commandAck=1;"}
          #200000000;if($ack!==0) $$fatal(1,"FRAME_COMPLETION_BEFORE_BOTH");
          ${if(n%2==0) "commandAck=1;" else s"$receipt=1;"}
          #200000000;if($ack!==4'd$bit) $$fatal(1,"FRAME_COMPLETION_SELECTED_CAPTURE");
          ${if((n/2)%2==0) "commandAck=0;" else s"$receipt=0;"}
          #200000000;if($ack!==4'd$bit) $$fatal(1,"FRAME_COMPLETION_EARLY_RETURN");
          ${if((n/2)%2==0) s"$receipt=0;" else "commandAck=0;"}
          #200000000;if($ack!==0) $$fatal(1,"FRAME_COMPLETION_RETURN");
        """
      }.mkString("\n")
    }
  }
  test("BD frame completion masks bank changes and non-Host ACK, and clears only at POR") {
    run("mask-reset",Seq(1L,2L,7L,19L)) {
      s"""
        receiptAck_0=1;receiptAck_1=1;receiptAck_2=1;receiptAck_3=1;
        host=1;commandAck=0;
        repeat(4) begin bank=0;#100000000;bank=3;#100000000;bank=1;#100000000;bank=2;#100000000;
          if($ack!==0) $$fatal(1,"FRAME_COMPLETION_UNOFFERED_BANK");end
        host=0;#200000000;commandAck=1;
        repeat(4) begin bank=0;#100000000;bank=3;#100000000;bank=1;#100000000;bank=2;#100000000;
          if($ack!==0) $$fatal(1,"FRAME_COMPLETION_NON_HOST");end
        commandAck=0;#200000000;host=1;bank=3;#200000000;commandAck=1;
        #200000000;if($ack!==4'b1000) $$fatal(1,"FRAME_COMPLETION_RESET_PRECONDITION");
        reset=1;#200000000;if($ack!==0) $$fatal(1,"FRAME_COMPLETION_POR");
        commandAck=0;host=0;receiptAck_0=0;receiptAck_1=0;receiptAck_2=0;receiptAck_3=0;
        #200000000;reset=0;#200000000;
        if($ack!==0) $$fatal(1,"FRAME_COMPLETION_POR_RELEASE");
        // Old receipt return may trail both tag retirement and a newer command.
        bank=1;host=1;receiptAck_1=1;#200000000;commandAck=1;#200000000;
        if($ack!==4'b0010) $$fatal(1,"FRAME_COMPLETION_OLD_ACCEPT");
        commandAck=0;#200000000;bank=2;#200000000;
        if($ack!==4'b0010) $$fatal(1,"FRAME_COMPLETION_OLD_SELECTOR_HOLD");
        receiptAck_2=1;commandAck=1;#200000000;
        if($ack!==4'b0110) $$fatal(1,"FRAME_COMPLETION_OVERLAP_ACCEPT");
        receiptAck_1=0;#200000000;
        if($ack!==4'b0100) $$fatal(1,"FRAME_COMPLETION_OLD_INDEPENDENT_RETURN");
        receiptAck_2=0;#200000000;
        if($ack!==4'b0100) $$fatal(1,"FRAME_COMPLETION_NEW_RETURN_HOLD");
        commandAck=0;#200000000;
        if($ack!==0) $$fatal(1,"FRAME_COMPLETION_OVERLAP_DRAIN");
      """
    }
  }
}
