// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.bd.FourPhaseSoc
import riscay.click.ClickSoc
import riscay.profiles.Groundlark
import java.nio.file.{Files, Paths}
import java.util.concurrent.TimeUnit
import java.util.zip.CRC32

/** Real compiler output is uploaded through I2C, never preloaded into MCU RAM.
  * Expectations use integer arithmetic independent of the C implementation.
  */
class FirmwareSpec extends AnyFunSuite {
  private lazy val built = {
    val root=Paths.get("").toAbsolutePath
    Files.createDirectories(root.resolve("build"))
    val log=root.resolve("build/firmware-build.log")
    val python=if(System.getProperty("os.name").toLowerCase.contains("windows")) "python" else "python3"
    val process=new ProcessBuilder(python,"tools/build_firmware.py").directory(root.toFile)
      .redirectErrorStream(true).redirectOutput(log.toFile).start()
    if(!process.waitFor(120,TimeUnit.SECONDS)) { process.destroyForcibly(); fail("Firmware compiler timed out") }
    assert(process.exitValue()==0, Files.readString(log))
    root.resolve("build/firmware")
  }
  private def hex(n: Long): String = s"32'h${(n & 0xffffffffL).toHexString}"
  private def expected(seed: Long, salt: Long): Long = {
    // Independent unsigned arithmetic and reduction, not a copy of C divide().
    val lanes=(0L until 8L).map(i => ((seed ^ (salt+i)) + 256*i) & 0xffffffffL)
    (seed / salt) ^ lanes.reduce(_ ^ _)
  }
  private val results=Vector(17L,0x1234L,0x80000001L,0xdeadbeefL)
    .zip(Vector(3L,7L,11L,13L)).map { case (a,b) => expected(a,b) }

  for(click <- Seq(false,true); app <- Seq("event_loop","runtime_stress")) {
    val name=if(click) "click" else "four-phase"
    test(s"$name compiled $app fits on-chip memory and its observed stack bound") {
      val base=built.resolve(app)
      val report=ujson.read(Files.readString(base.resolve("report.json")))
      val image=Files.readAllBytes(base.resolve("firmware.bin"))
      val budget=ujson.read(Files.readString(Paths.get("firmware/memory.json")))
      val production=Groundlark.configuration
      assert(production.programBytes==budget("program_bytes").num.toInt)
      assert(production.workingRamBytes==budget("working_ram_bytes").num.toInt)
      assert(image.length==report("image_bytes").num.toInt && image.length <= production.programBytes)
      val stackBound=report("static_stack_bound_bytes").num.toInt
      val stackTop=0x20000000L+production.workingRamBytes
      val guardEnd=report("symbols")("__guard_end").num.toLong
      val crc=new CRC32; crc.update(image)
      assert(crc.getValue==report("crc32").num.toLong)
      val words=image.grouped(4).map(bytes => bytes.zipWithIndex.map { case (b,i) => (b.toLong & 255L) << (8*i) }.sum).toVector
      val profile=ApplicationProfile(0x53495a45L,1,"sizing-fixture",(0 until 8).map(i => HostRegister(i,s"WORD_$i")).toVector,Vector.empty)
      val config=production.copy(application=profile,measurements=Vector.empty)
      val p=SocParameters(config,staleMs=3000,watchdogCycles=32,watchdogHoldCycles=2,
        lowPower=Some(LowPowerParameters.gf180Slow))
      val top=if(click) () => new ClickSoc(p) else () => new FourPhaseSoc(p)
      val check=if(app=="event_loop") """
        if(snapshot[32+:32] !== 4 || !snapshot[65] || snapshot[96+:32] !== 4 ||
           snapshot[128+:32] !== 1 || snapshot[192+:32] !== 32'h600d600d) $fatal(1,"COMPILED_EVENT_RESULT");
        watermark=snapshot[160+:32];
      """ else s"""
        if(snapshot[32+:32] !== ${hex(results.reduce(_ ^ _))} || snapshot[192+:32] !== 1) $$fatal(1,"COMPILED_STRESS_RESULT");
        ${results.zipWithIndex.map { case (n,i) => s"if(snapshot[${32*(i+2)}+:32] !== ${hex(n)}) $$fatal(1,\"COMPILED_DIVIDE_RESULT_$i\");" }.mkString("\n")}
        watermark=snapshot[224+:32];
      """
      val directory=ClockedSimulation.run(top(),s"$name-firmware-$app",s"""
        #3000000;
        start_bus(); write_byte(8'h6a); write_byte(1);
        write_word(${image.length}); write_word(0); write_word(${hex(crc.getValue)}); write_word(32'h00010000);
        write_word(${production.workingRamBytes}); write_word(0); write_word(0); write_word(32'h53495a45);
        ${words.zipWithIndex.map { case(w,i) => s"start_bus(); write_byte(8'h6a); write_byte(2); write_word(${i*4}); write_word(${hex(w)});" }.mkString("\n")}
        start_bus(); write_byte(8'h6a); write_byte(3); stop_bus();
        if(!programmed) $$fatal(1,"COMPILED_VERIFY");
        $$display("FIRMWARE_UPLOADED:$app");
        command(6);
        wait(mode==4); #1000;
        if(!programmed || !locked || resetReason || traps !== 1 || retired < 100 || sleepEntries < 2)
          $$fatal(1,"COMPILED_EXECUTION_OR_RETENTION");
        read_words(128,0,0);
        if(supported !== 255 || snapshot[0+:32] !== 32'h43525431) $$fatal(1,"CRT_DATA_BSS_INIT");
        $check
        if(minSp !== ${hex(stackTop-stackBound)} || watermark !== $stackBound)
          $$fatal(1,"STACK_BOUND actual=%d watermark=%d expected=$stackBound",${hex(stackTop)}-minSp,watermark);
        $$display("FIRMWARE_MEMORY_PASS:$app:${image.length}:%0d:%0d",${hex(stackTop)}-minSp,watermark);
      """,s"""
        reg seen=0; reg [31:0] minSp=${hex(stackTop)}, watermark;
        integer retired=0, traps=0;
        initial begin
          wait(!systemReset);
          forever begin
            ${if(click) "wait(traceEvent != seen); seen=traceEvent;" else "wait(traceEvent);"}
            if(trace_valid && trace_pc >= 32'h10000000) begin
              retired=retired+1;
              if(trace_writeRegister && trace_rd==2) begin
                if(trace_data < ${hex(guardEnd)} || trace_data > ${hex(stackTop)} || trace_data[1:0] !== 0)
                  $$fatal(1,"STACK_OUT_OF_BOUNDS pc=%h sp=%h",trace_pc,trace_data);
                if(trace_data < minSp) minSp=trace_data;
              end
              if(trace_trap) begin
                traps=traps+1;
                if(trace_cause !== 3 || trace_instruction !== 32'h00100073) $$fatal(1,"COMPILED_ISA_FAULT pc=%h cause=%d",trace_pc,trace_cause);
              end
            end
            ${if(click) "#1;" else "wait(!traceEvent);"}
          end
        end
      """,referenceHalfPeriodNs=1000000,onChipOscillator=true,chipParameters=p.lowPower.get,
        serviceStartupNs=100000,deadlineNs=400000000,processTimeoutSeconds=300)
      val log=Files.readString(directory.resolve("simulation.log"))
      assert(log.contains(s"FIRMWARE_MEMORY_PASS:$app:${image.length}:$stackBound:$stackBound"))
      Files.writeString(base.resolve(s"$name-simulation.txt"),s"$directory\n$log")
    }
  }
}
