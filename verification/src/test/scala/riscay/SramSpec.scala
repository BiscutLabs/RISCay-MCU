// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.profiles.Groundlark
import java.nio.file.Files
import java.util.zip.CRC32

class MemoryResetFixture(p: SocParameters) extends FabricFixture(p) {
  val applicationReset = IO(Input(Bool()))
  val observed = withClockAndReset(serviceClock, reset) {
    val first = RegNext(applicationReset, false.B); RegNext(first, false.B)
  }
  fabric.io.cpuReset := systemReset || applicationReset
  fabric.io.cpuResetActive := cpuResetActive || observed
}

class SramSpec extends AnyFunSuite {
  private val p = SocParameters(Groundlark.configuration, watchdogCycles=10000000)
  private val pinTiming = Seq("program_macros_0", "program_macros_1", "ram_macros_0").zipWithIndex.map { case(name, i) =>
    val path=s"dut.fabric_$name"
    s"""
real changed$i=0, accessed$i=0;
always @($path.CEN or $path.GWEN or $path.WEN or $path.A or $path.D) begin
  if(!reset && accessed$i>0 && $$realtime-accessed$i<5) $$fatal(1,"SRAM_INPUT_HOLD_$i");
  changed$i=$$realtime;
end
always @(posedge $path.CLK) if(!reset && !$path.CEN) begin
  if($$realtime-changed$i<5) $$fatal(1,"SRAM_INPUT_SETUP_$i");
  accessed$i=$$realtime;
end
"""
  }.mkString
  private val tasks = pinTiming + """
task issue(input [1:0] op, input [31:0] addr, input [31:0] data, input [3:0] mask);
begin
  @(negedge serviceClock); request_valid=1; request_bits_operation=op;
  request_bits_address=addr; request_bits_data=data; request_bits_mask=mask;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
end endtask
task answer(input [31:0] expected, input error);
reg [32:0] saved; begin
  wait(response_valid); saved={response_bits_error,response_bits_data};
  if(response_bits_error !== error || (!error && response_bits_data !== expected))
    $fatal(1,"SRAM_RESULT actual=%h expected=%h error=%b",response_bits_data,expected,response_bits_error);
  repeat(3) begin @(negedge serviceClock);
    if(!response_valid || {response_bits_error,response_bits_data} !== saved || request_ready)
      $fatal(1,"SRAM_BACKPRESSURE");
  end
  response_ready=1; @(posedge serviceClock); #1; response_ready=0;
end endtask
integer i,m,b,phase,writes=0;
reg [31:0] expected, value;
// Count actual macro writes, independently of the controller state machine.
always @(posedge serviceClock) if(!dut.fabric_ram_macros_0.CEN && !dut.fabric_ram_macros_0.GWEN)
  writes=writes+1;
"""
  test("three physical SRAM macros cover every program/data word, byte mask, boundary and stalled response") {
    val words=(0 until 512).map(i => (0x9e3779b9L * (i+1)) & 0xffffffffL)
    val crc=new CRC32
    words.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b)) & 255).toInt)))
    val dir=ClockedSimulation.run(new FabricFixture(p),"sram-capacity",s"""
      read_words(0,0,0);
      if(snapshot[96+:32] !== 2048 || snapshot[128+:32] !== 1024) $$fatal(1,"SRAM_DISCOVERY");
      issue(1,32'h20000000,0,15); wait(response_valid);
      if(^response_bits_data !== 1'bx) $$fatal(1,"SRAM_HAS_INVENTED_POWER_ON_CLEAR");
      @(negedge serviceClock); response_ready=1; @(posedge serviceClock); #1; response_ready=0;
      for(i=0;i<256;i=i+1) begin
        issue(2,32'h20000000+4*i,32'h13579bdf ^ (i*32'h01020408),15); answer(0,0);
      end
      for(i=255;i>=0;i=i-1) begin
        issue(1,32'h20000000+4*i,0,15); answer(32'h13579bdf ^ (i*32'h01020408),0);
      end
      expected=32'h13579bdf;
      for(m=0;m<16;m=m+1) begin
        value=32'hfedcba98 ^ (m*32'h10204081);
        for(b=0;b<4;b=b+1) if((m>>b)&1) expected[b*8+:8]=value[b*8+:8];
        issue(2,32'h20000000+(m%4),value,m); answer(0,0);
        issue(1,32'h20000000,0,15); answer(expected,0);
      end
      if(writes !== 1056) $$fatal(1,"SRAM_WRITE_REPLAY_OR_MASK count=%0d",writes);
      issue(2,32'h20000400,32'hffffffff,15); answer(0,1);
      issue(1,32'h20000400,0,15); answer(0,1);
      issue(0,32'h20000000,0,15); answer(0,1);
      // High bits and low alignment bits must be checked before metadata is
      // narrowed, otherwise malformed lengths/entries can alias valid values.
      begin_image(32'h80000800,0,0,32'h00010000); expect_error(4);
      begin_image(2048,32'h800007fc,0,32'h00010000); expect_error(4);
      begin_image(2049,0,0,32'h00010000); expect_error(4);
      begin_image(2048,2048,0,32'h00010000); expect_error(4);
      begin_image(2048,1,0,32'h00010000); expect_error(4);
      begin_image(2048,2044,32'h${crc.getValue.toHexString},32'h00010000);
      put_word(32'h80000000,0); expect_error(4);
      put_word(1,0); expect_error(4);
      read_words(1,0,0); if(snapshot[224+:32] !== 0) $$fatal(1,"BAD_OFFSET_ALIASED_ZERO");
      ${words.zipWithIndex.map { case(w,i) => s"put_word(${i*4},32'h${w.toHexString});" }.mkString("\n")}
      read_words(1,0,0); if(snapshot[224+:32] !== 2048) $$fatal(1,"FULL_IMAGE_COUNT_WRAPPED");
      put_word(2048,0); expect_error(4);
      command(3); command(4);
      if(!programmed || !locked) $$fatal(1,"SRAM_PROGRAM_VERIFY");
      ${words.zipWithIndex.map { case(w,i) => s"issue(0,32'h${(MemoryMap.program+4*i).toHexString},0,15); answer(32'h${w.toHexString},0);" }.mkString("\n")}
      issue(2,32'h10000000,0,15); answer(0,1);
      issue(0,32'h10000800,0,15); answer(0,1);
      put_word(0,0); expect_error(2);
      issue(0,32'h10000000,0,15); answer(32'h${words.head.toHexString},0);
      // Complete a WAKE frame while a program fetch is in flight. Independent
      // peripheral commands must remain available even during CPU memory use.
      start_bus(); write_byte(8'h6a); write_byte(8);
      hostLow=1; #1200; scl=1; #1200;
      issue(0,32'h10000000,0,15);
      hostLow=0; #1200; // STOP is decoded before the SRAM fetch completes.
      answer(32'h${words.head.toHexString},0);
      expect_error(0);
      issue(1,32'h3000000c,0,15); wait(response_valid);
      if(!response_bits_data[5]) $$fatal(1,"SRAM_FETCH_BLOCKED_HOST_WAKE");
      value=response_bits_data; answer(value,0);
      issue(1,32'h20000000,0,15); answer(expected,0);
      command(5);
      issue(1,32'h30000000,0,15); answer(32'h100007fc,0);
    """,tasks,deadlineNs=400000000L,processTimeoutSeconds=180,serviceHalfPeriodNs=25)
    val rtl=Files.readString(dir.resolve("FabricFixture.sv"))
    assert("gf180mcu_ocd_ip_sram__sram1024x8m8wm1\\s+fabric_".r.findAllIn(rtl).size == 3)
  }

  test("word indices and loader counts support one-word and non-power-of-two capacities") {
    for(bytes <- Seq(4, 12)) {
      val words=(0 until bytes/4).map(i => 0x12345678L + i)
      val crc=new CRC32
      words.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b)) & 255).toInt)))
      val params=p.copy(config=p.config.copy(programBytes=bytes,workingRamBytes=bytes))
      ClockedSimulation.run(new FabricFixture(params),s"sram-small-$bytes",s"""
        start_bus(); write_byte(8'h6a); write_byte(1);
        write_word($bytes); write_word(${bytes-4}); write_word(32'h${crc.getValue.toHexString}); write_word(32'h00010000);
        write_word($bytes); write_word(0); write_word(0); write_word(32'h12345678); stop_bus();
        ${words.zipWithIndex.map { case(w,i) => s"put_word(${i*4},32'h${w.toHexString});" }.mkString("\n")}
        read_words(1,0,0); if(snapshot[224+:32] !== $bytes) $$fatal(1,"SMALL_COUNT_WRAPPED");
        put_word($bytes,0); expect_error(4);
        command(3); command(6);
        if(!programmed || !locked) $$fatal(1,"SMALL_IMAGE_VERIFY");
        issue(1,32'h30000000,0,15); answer(32'h${(MemoryMap.program+bytes-4).toHexString},0);
        ${words.zipWithIndex.map { case(w,i) => s"issue(0,32'h${(MemoryMap.program+4*i).toHexString},0,15); answer(32'h${w.toHexString},0);" }.mkString("\n")}
        issue(0,32'h${(MemoryMap.program+bytes).toHexString},0,15); answer(0,1);
        issue(2,32'h20000000,32'haabbccdd,15); answer(0,0);
        issue(2,32'h${(MemoryMap.ram+bytes-4).toHexString},32'h10203040,15); answer(0,0);
        issue(2,32'h${(MemoryMap.ram+bytes).toHexString},32'hffffffff,15); answer(0,1);
        issue(1,32'h${(MemoryMap.ram+bytes-4).toHexString},0,15); answer(32'h10203040,0);
        issue(1,32'h20000000,0,15); answer(32'h${if(bytes==4) "10203040" else "aabbccdd"},0);
      """,tasks.stripPrefix(pinTiming))
    }
  }

  test("watchdog at every word phase completes accepted stores and discards responses; POR aborts without replay") {
    ClockedSimulation.run(new MemoryResetFixture(p),"sram-reset","""
      for(phase=0;phase<10;phase=phase+1) begin
        issue(2,32'h200003fc,32'h12345678+phase,15);
        repeat(phase) @(posedge serviceClock);
        #17; applicationReset=1; #2000;
        if(response_valid) $fatal(1,"RESET_RETAINED_CPU_COMPLETION");
        applicationReset=0; #1000;
        issue(1,32'h200003fc,0,15); answer(32'h12345678+phase,0);
      end
      if(writes != 40) $fatal(1,"WATCHDOG_ABORTED_OR_REPLAYED_WRITE");
      for(phase=0;phase<10;phase=phase+1) begin
        issue(1,32'h200003fc,0,15);
        repeat(phase) @(posedge serviceClock);
        #17; applicationReset=1; #2000; applicationReset=0; #1000;
        if(response_valid) $fatal(1,"WATCHDOG_REPLAYED_READ");
      end
      for(phase=0;phase<10;phase=phase+1) begin
        issue(2,32'h20000000,32'h11223344,15); answer(0,0);
        issue(2,32'h20000000,32'haabbccdd,15);
        repeat(phase) @(posedge serviceClock);
        #17; reset=1; #1000;
        // POR may leave a prefix written. Read the independent macro contents
        // after abort and check the controller neither replays nor clears them.
        expected={dut.fabric_ram_macros_0.mem[3],dut.fabric_ram_macros_0.mem[2],
                  dut.fabric_ram_macros_0.mem[1],dut.fabric_ram_macros_0.mem[0]};
        value=writes; reset=0; #1000;
        if(response_valid || writes !== value) $fatal(1,"POR_REPLAYED_WRITE");
        issue(1,32'h20000000,0,15); answer(expected,0);
      end
    """,tasks)
  }

  test("loader accounts only completed SRAM words, survives watchdog, and invalidates partial POR uploads") {
    val word=0x89abcdefL
    val crc=new CRC32; (0 until 4).foreach(b => crc.update(((word >>> (8*b)) & 255).toInt))
    ClockedSimulation.run(new MemoryResetFixture(p),"sram-loader-reset",s"""
      for(m=0;m<2;m=m+1) for(phase=0;phase<10;phase=phase+1) begin
        begin_image(4,0,32'h${crc.getValue.toHexString},32'h00010000);
        fork
          begin put_word(0,32'h89abcdef); end
          begin
            wait(dut.fabric_loaderPending);
            if(dut.fabric_receivedWords !== 0 || programmed) $$fatal(1,"LOADER_COUNTED_BEFORE_SRAM_WRITE");
            repeat(phase) @(posedge serviceClock);
            #17;
            if(m==0) applicationReset=1; else reset=1;
            #2000; applicationReset=0; reset=0;
          end
        join
        #5000;
        if(m==0) begin
          command(3); if(!programmed || dut.fabric_receivedWords !== 1) $$fatal(1,"WATCHDOG_LOST_LOADER_WRITE");
          issue(0,32'h10000000,0,15); answer(32'h89abcdef,0);
        end else begin
          if(programmed || locked || dut.fabric_receivedWords !== 0 || dut.fabric_loaderPending)
            $$fatal(1,"POR_REPLAYED_LOADER_ACCOUNTING");
          command(3); expect_error(6);
        end
      end
      begin_image(4,0,32'h${crc.getValue.toHexString},32'h00010000);
      put_word(0,32'h89abcdef); command(3); command(4);
      issue(0,32'h10000000,0,15); answer(32'h89abcdef,0);
      if(!programmed || !locked) $$fatal(1,"LOADER_DID_NOT_RECOVER");
    """,tasks+"""
always @(posedge serviceClock) if(!reset && dut.fabric_loaderPending && dut.fabric_receivedWords !== 0)
  $fatal(1,"LOADER_PREMATURE_RECEIVED_BYTES");
""",deadlineNs=100000000L)
  }
}
