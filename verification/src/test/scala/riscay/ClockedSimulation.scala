// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.AsyncModule
import chiselasync.metadata.ExportDesign
import chiselasync.testing.Simulator
import java.nio.file.{Files, Path, Paths}
import java.util.concurrent.TimeUnit
import scala.jdk.CollectionConverters._

/** Clocked SoC harness: public export contract + actual primitive models.
  * AsyncTest remains in use for the clockless core/route randomized campaigns.
  */
object ClockedSimulation {
  def run(gen: => AsyncModule, name: String, body: String, extra: String = ""): Path = {
    val root = Paths.get("build/soc-tests").toAbsolutePath; Files.createDirectories(root)
    val base = Files.createTempDirectory(root, name)
    Simulator().check(base.resolve("simulator"))
    ExportDesign.emit(gen, base)
    val manifest = ujson.read(Files.readString(base.resolve("contract.json")))("manifest")
    def nodes(n: ujson.Value): Seq[ujson.Value] = Seq(n) ++ n("children").arr.flatMap(c => nodes(c("contract")))
    val resources = nodes(manifest("design")).flatMap(_("primitives").arr).map(_("resource").str).distinct
    val models = resources.map { resource =>
      val file = base.resolve(resource.split('/').last)
      val stream = Option(getClass.getResourceAsStream("/" + resource)).getOrElse(sys.error(resource))
      try Files.write(file, stream.readAllBytes()) finally stream.close()
      file.toString
    }
    val ports = ujson.read(Files.readString(base.resolve("ports.json")))("nodes")(0)("ports").arr.toSeq
    def flat(p: ujson.Value) = p("source").str.split('>').last.replace('.', '_').replace('[', '_').replace("]", "")
    val declarations = ports.map(p => s"${if(p("direction").str == "input") "reg" else "wire"} [${p("width").num.toInt-1}:0] ${flat(p)};").mkString("\n")
    val tb = s"""module Testbench;
timeunit 1ns; timeprecision 1ps;
$declarations
reg hostLow=0;
wire busSda = !(hostLow || sdaLow);
always @* sda=busSda;
${manifest("top").str} dut (${ports.map(p => s".${flat(p)}(${flat(p)})").mkString(",")});
reg clockEnabled=1;
initial begin serviceClock=0; forever begin #50; if(clockEnabled) serviceClock=~serviceClock; end end
initial begin watchdogClock=0; forever #163 watchdogClock=~watchdogClock; end
initial begin #100000000; $$fatal(1,"SOC_DEADLINE"); end
$extra
$hostTasks
initial begin
${ports.filter(p => p("direction").str == "input" && !Set("serviceClock", "watchdogClock", "sda").contains(flat(p))).map(p => s"${flat(p)}=0;").mkString("\n")}
reset=1; scl=1; gpioIn=4; adcMiso=0;
#2000; reset=0; #3000;
$body
$$display("RISCAY_SOC_PASS"); $$finish;
end
endmodule
"""
    Files.writeString(base.resolve("testbench.sv"), tb)
    def command(args: Seq[String], log: String): Unit = {
      val file = base.resolve(log).toFile
      val process = new ProcessBuilder(args: _*).directory(base.toFile).redirectErrorStream(true).redirectOutput(file).start()
      if(!process.waitFor(90, TimeUnit.SECONDS)) { process.destroyForcibly(); sys.error(s"Timeout: $base/$log") }
      require(process.exitValue() == 0, s"Simulation failure: $base/$log\n${Files.readString(file.toPath).takeRight(5000)}")
    }
    val sources = Files.readAllLines(base.resolve("filelist.f")).asScala.filter(_.trim.nonEmpty).map(s => base.resolve(s.trim).normalize().toString)
    command(Seq("iverilog", "-g2012", "-s", "Testbench", "-o", "sim.vvp") ++ (sources ++ models).distinct ++ Seq("testbench.sv"), "compile.log")
    command(Seq("vvp", "sim.vvp"), "simulation.log")
    require(Files.readString(base.resolve("simulation.log")).linesIterator.count(_ == "RISCAY_SOC_PASS") == 1, "MISSING_SOC_COMPLETION")
    base
  }

  val hostTasks = """
reg [255:0] snapshot;
reg [31:0] supported;
task start_bus; begin
  scl=0; hostLow=0; #1200; scl=1; #1200; hostLow=1; #1200; scl=0; #1200;
end endtask
task stop_bus; begin
  scl=0; hostLow=1; #1200; scl=1; #1200; hostLow=0; #1200;
end endtask
task write_byte(input [7:0] value); integer b; begin
  for(b=7;b>=0;b=b-1) begin
    hostLow=!value[b]; #1000; scl=1; #1000; scl=0; #1000;
  end
  hostLow=0; #1000; scl=1; #1000;
  if(busSda !== 0) $fatal(1,"I2C_NACK byte=%h",value);
  scl=0; #1000;
end endtask
task read_byte(output [7:0] value, input last); integer b; begin
  hostLow=0;
  for(b=7;b>=0;b=b-1) begin
    #1000; scl=1; #1000; value[b]=busSda; scl=0; #1000;
  end
  hostLow=!last; #1000; scl=1; #1000; scl=0; #1000; hostLow=0;
end endtask
task write_word(input [31:0] value); integer b; begin
  for(b=0;b<4;b=b+1) write_byte(value[8*b+:8]);
end endtask
task command(input [7:0] opcode); begin
  start_bus(); write_byte(8'h6a); write_byte(opcode); stop_bus();
end endtask
task read_words(input [7:0] space, input [7:0] channelno, input [7:0] wordno);
integer b; reg [7:0] value; begin
  start_bus(); write_byte(8'h6a); write_byte(0); write_byte(space); write_byte(channelno); write_byte(wordno);
  start_bus(); write_byte(8'h6b);
  for(b=0;b<36;b=b+1) begin
    read_byte(value,b==35);
    if(b<32) snapshot[8*b+:8]=value; else supported[8*(b-32)+:8]=value;
  end
  stop_bus();
end endtask
task begin_image(input [31:0] length, input [31:0] entry, input [31:0] crc, input [31:0] abi);
begin
  start_bus(); write_byte(8'h6a); write_byte(1);
  write_word(length); write_word(entry); write_word(crc); write_word(abi);
  write_word(32); write_word(0); write_word(0); write_word(32'h12345678); stop_bus();
end endtask
task put_word(input [31:0] offset, input [31:0] value); begin
  start_bus(); write_byte(8'h6a); write_byte(2); write_word(offset); write_word(value); stop_bus();
end endtask
task expect_error(input [31:0] error); begin
  read_words(1,0,0);
  if(snapshot[160+:32] !== error) $fatal(1,"LOADER_ERROR actual=%d expected=%d",snapshot[160+:32],error);
end endtask
"""
}
