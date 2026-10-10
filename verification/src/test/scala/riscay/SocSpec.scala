// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.bd.FourPhaseSoc
import riscay.click.ClickSoc
import riscay.profiles._
import java.util.zip.CRC32

class SocSpec extends AnyFunSuite {
  import Assembly._
  private val config = McuConfiguration(256, 32, 3,
    Vector(MeasurementChannel(0, "test", MeasurementUnit.Count, 0)),
    ApplicationProfile(0x54455354L, 1, "test", Vector(HostRegister(0,"RESULT"), HostRegister(1,"SECOND")), Vector.empty))
  private val p = SocParameters(config, watchdogCycles = 100000, staleMs = 2)
  private def top(click: Boolean, params: SocParameters = p, board: SocParameters => BoardProfile = x => new GenericBoard(x)): SocTop =
    if(click) new ClickSoc(params, board) else new FourPhaseSoc(params, board)
  private def hex(word: Long): String = "32'h" + java.lang.Long.toHexString(word & 0xffffffffL)
  private def checksum(program: Seq[Long]): Long = {
    val crc = new CRC32
    program.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b)) & 255).toInt)))
    crc.getValue
  }
  private def upload(program: Seq[Long], start: Int = 6): String = s"""
    begin_image(${program.size * 4},0,${hex(checksum(program))},32'h00010000);
    ${program.zipWithIndex.map { case(word, i) => s"put_word(${i*4},${hex(word)});" }.mkString("\n")}
    command(3);
    if(!programmed || mode != 2) $$fatal(1,"VERIFY_NOT_READY");
    ${if(start >= 0) s"command($start);" else ""}
  """

  for(click <- Seq(false, true)) {
    val name = if(click) "click" else "four-phase"
    test(s"$name SoC: I2C loader validation, RAM lanes, telemetry, lock, CPU protection and full reset") {
      val program = Seq(
        0x200000b7L, // x1 = working RAM
        0x30000137L, // x2 = MMIO
        i(0x13,3,0,0,0x123), store(1,3,0,2), store(1,3,28,2),
        i(0x13,4,0,0,0x56), store(1,4,1,0), // byte write, leaves other lanes
        i(0x03,5,2,1,0), store(2,5,52,2), // host RESULT = 00005623
        store(2,3,40,2), i(0x13,4,0,0,3), store(2,4,44,2), // sample 291, calibrated
        i(0x13,4,0,0,1), store(2,4,48,2), i(0x03,5,2,1,28), store(2,5,52,2),
        0x10000337L, store(6,0,0,2)) // protected code store -> access trap
      // Native byte crossings lengthen fetches. Check architectural retirement
      // instead of assuming this program finishes in a fixed 100 us window.
      val protectionTrace = s"""
reg checkProtection=1, protectedTrap=0, protectionSeen=0;
integer protectionRetired=0;
initial forever begin
  ${if(click) "wait(traceEvent != protectionSeen); protectionSeen=traceEvent;" else "wait(traceEvent);"}
  #1;
  if(checkProtection && trace_valid && trace_pc >= 32'h10000000) begin
    case(protectionRetired)
      ${program.zipWithIndex.map { case(word,index) =>
        s"$index: if(trace_pc !== ${hex(MemoryMap.program+4*index)} || trace_instruction !== ${hex(word)}) $$fatal(1,\"PROTECTION_RETIREMENT_$index\");"
      }.mkString("\n")}
      default: $$fatal(1,"PROTECTION_EXTRA_RETIREMENT");
    endcase
    if(protectionRetired == ${program.size-2} &&
       (trace_writeRegister !== 1'b1 || trace_rd !== 4'd6 || trace_data !== 32'h10000000))
      $$fatal(1,"PROTECTION_WRONG_BASE_REGISTER");
    if(protectionRetired == ${program.size-1}) begin
      if(trace_trap !== 1'b1 || trace_cause !== 4'd7 || trace_writeRegister !== 1'b0)
        $$fatal(1,"PROTECTION_WRONG_STORE_FAULT");
    end else if(trace_trap !== 1'b0) $$fatal(1,"PROTECTION_EARLY_TRAP");
    protectionRetired=protectionRetired+1;
    if(protectionRetired == ${program.size}) protectedTrap=1;
  end
  ${if(click) "#1;" else "wait(!traceEvent);"}
end
"""
      ClockedSimulation.run(top(click), name, s"""
        read_words(0,0,0);
        if(snapshot[0+:32] !== 32'h00010000 || snapshot[96+:32] !== 256 || supported !== 255) $$fatal(1,"BAD_DEVICE_ABI");
        read_words(2,1,0); if(supported !== 0) $$fatal(1,"ABSENT_CHANNEL_ALIASED");
        read_words(0,0,255); if(supported !== 0) $$fatal(1,"WORD_ADDRESS_WRAPPED");
        read_words(1,0,0);
        if(snapshot[0+:32] !== 0 || snapshot[32+:32] !== 0 || snapshot[96+:32] !== 1) $$fatal(1,"BAD_BOOT_STATE %h",snapshot);
        command(6); expect_error(6);
        begin_image(0,0,0,32'h00010000); expect_error(4);
        begin_image(260,0,0,32'h00010000); expect_error(4);
        begin_image(4,0,0,32'h00020000); expect_error(5);
        begin_image(4,0,0,32'h00010000); command(3); expect_error(7);
        put_word(4,0); expect_error(4);
        put_word(0,0); command(3); expect_error(8);
        if(programmed) $$fatal(1,"CORRUPT_IMAGE_VALID");
        start_bus(); write_byte(8'h6a); write_byte(2); write_word(0); stop_bus(); expect_error(1);
        ${upload(program)}
        wait(protectedTrap); wait(mode == 4); checkProtection=0;
        if(protectionRetired !== ${program.size}) $$fatal(1,"PROTECTION_RETIREMENT_COUNT");
        if({dut.fabric_program_macros_0.mem[3],dut.fabric_program_macros_0.mem[2],
            dut.fabric_program_macros_0.mem[1],dut.fabric_program_macros_0.mem[0]} !== ${hex(program.head)})
          $$fatal(1,"PROTECTED_STORE_MODIFIED_CODE");
        if(!locked || !programmed || mode != 4) $$fatal(1,"PROTECTED_STORE_DID_NOT_TRAP mode=%d",mode);
        read_words(128,0,0);
        if(snapshot[0+:32] !== 32'h00005623 || snapshot[32+:32] !== 32'h123) $$fatal(1,"RAM_LANES_OR_BOUNDARY %h",snapshot[63:0]);
        read_words(2,0,0);
        if(snapshot[0+:32] !== 291 || snapshot[96+:32] !== 1 || !snapshot[36]) $$fatal(1,"MEASUREMENT_NOT_PUBLISHED %h",snapshot);
        put_word(0,0); expect_error(2);
        begin_image(4,0,0,32'h00010000); expect_error(2);
        command(4); expect_error(0);
        // Bus recovery and host rail restart affect no MCU reset signal.
        repeat(9) begin scl=0; #1200; scl=1; #1200; end
        stop_bus();
        if(!locked || !programmed) $$fatal(1,"BUS_UNLOCKED_PROGRAM");
        reset=1; #2000; reset=0; #5000;
        if(locked || programmed || mode != 0) $$fatal(1,"FULL_RESET_FLAGS");
        read_words(1,0,0);
        if(snapshot[64+:32] !== 0) $$fatal(1,"STALE_HOST_STATUS");
        ${upload(Seq(breakpoint), start = -1)}
        put_word(0,0); expect_error(6);
        if(!programmed || mode != 2) $$fatal(1,"READY_IMAGE_MUTATED");
        begin_image(4,0,${hex(checksum(Seq(breakpoint)))},32'h00010000);
        if(programmed || mode != 1) $$fatal(1,"BEGIN_DID_NOT_INVALIDATE");
        put_word(0,${hex(breakpoint)}); command(3); command(5); #50000;
        if(locked || !programmed || mode != 4) $$fatal(1,"UNLOCKED_START_FAILED");
        begin_image(4,0,0,32'h00010000); expect_error(3);
        command(4);
        if(!locked) $$fatal(1,"EXPLICIT_LOCK_FAILED");
      """, protectionTrace)
    }
    test(s"$name SoC: independent watchdog resets a stalled application and stopped service clock") {
      val program = Seq(0x300000b7L, i(0x13,2,0,0,-1), store(1,2,12,2), i(0x03,3,2,1,16), jal(0,-8)) // clear/wait, never kicks
      ClockedSimulation.run(top(click, p.copy(watchdogCycles = 5000)), name + "-watchdog", s"""
        ${upload(program)}
        wait(systemReset); #5000;
        if(!resetReason || !locked || !programmed || mode != 2) $$fatal(1,"WATCHDOG_RESET_FAILED");
        read_words(0,0,7);
        if(snapshot[0+:32] !== 2) $$fatal(1,"WATCHDOG_REASON");
        begin_image(4,0,0,32'h00010000); expect_error(2);
        command(5); #10000;
        if(!locked || !programmed || mode != 3) $$fatal(1,"LOCKED_IMAGE_RESTART_FAILED");
        reset=1; #2000; reset=0; #5000;
        clockEnabled=0;
        wait(resetReason); #1000;
        if(!systemReset) $$fatal(1,"STOPPED_CLOCK_NOT_RESET");
        clockEnabled=1; #10000;
        if(systemReset || programmed) $$fatal(1,"STOPPED_CLOCK_RECOVERY");
      """)
    }
    test(s"$name Groundlark: unprogrammed cold start, SPI sensing, protected outputs, shutdown ACK and timeout latch") {
      val params = SocParameters(Groundlark.configuration, serviceHz = 1000, staleMs = 500,
        watchdogCycles = 100000, adc = Some(AdcParameters(2,100)))
      val program = Seq(0x300000b7L, store(1,0,24,2), store(1,0,28,2), breakpoint)
      val adcModel = """
reg [11:0] adcCode=2200;
reg [15:0] adcShift;
always @(negedge adcCsN) begin adcShift={4'b0,adcCode}; adcMiso=adcShift[15]; end
always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1; adcMiso=adcShift[15]; end
"""
      ClockedSimulation.run(top(click, params, x => new GroundlarkBoard(x, PowerPolicy(enabled=true))),
        name + "-groundlark", s"""
        if(gpioOut[0] || programmed) $$fatal(1,"UNQUALIFIED_BOOT");
        gpioIn=0;
        #3100000;
        if(gpioOut[0]) $$fatal(1,"STALE_ACK_ALLOWED_BOOT");
        gpioIn=4; #150000;
        if(!gpioOut[0] || gpioOut[1] || programmed || gpioOe !== 3) begin
          read_words(2,0,0); $$display("BOOT_SAMPLE %h out=%h oe=%h",snapshot,gpioOut,gpioOe);
          read_words(128,0,0); $$fatal(1,"CIRCULAR_BOOT state=%h",snapshot);
        end
        read_words(2,0,0);
        if(snapshot[0+:32] !== 13592 || !snapshot[32] || snapshot[36] || snapshot[128+:32] !== 1 ||
          snapshot[160+:32] !== 32'hfffffffd || supported !== 63) $$fatal(1,"ADC_TELEMETRY %h",snapshot);
        ${upload(program)}
        #50000;
        if(!gpioOut[0] || gpioOe !== 3 || !locked) $$fatal(1,"HANDOFF_OR_GPIO_OVERRIDE");
        adcCode=1500;
        wait(gpioOut[1]);
        if(!gpioOut[0]) $$fatal(1,"EARLY_POWER_CUT");
        gpioIn=0; #10000;
        if(gpioOut[0] || gpioOut[1]) $$fatal(1,"ACK_NOT_HONORED");
        gpioIn=4; adcCode=2200;
        #2000000; if(gpioOut[0]) $$fatal(1,"MINIMUM_OFF_IGNORED");
        wait(gpioOut[0]);
        // Three unacknowledged requests cause bounded forced-off then latch.
        repeat(3) begin
          adcCode=1500; wait(gpioOut[1]); wait(!gpioOut[0]);
          adcCode=2200;
          #3200000;
        end
        if(gpioOut[0]) $$fatal(1,"TIMEOUTS_DID_NOT_LATCH");
        read_words(128,0,0);
        if(snapshot[0+:32] !== 3 || snapshot[160+:32] !== 3 || snapshot[128+:32] !== 4) $$fatal(1,"BAD_LATCH_TELEMETRY %h",snapshot);
        read_words(2,0,0);
        if(!snapshot[32] || snapshot[96+:32] < 20) $$fatal(1,"LOCK_STOPPED_SAMPLING");
        reset=1; #1000;
        if(gpioOut[0] || programmed || locked) $$fatal(1,"RESET_NOT_FAIL_OFF");
      """, adcModel)
    }
  }
  test("SoC harness rejects a deliberately wrong host ABI expectation") {
    val failure = intercept[IllegalArgumentException] {
      ClockedSimulation.run(top(click=false), "negative-control", """
        read_words(0,0,0);
        if(snapshot[0+:32] !== 32'h99999999) $fatal(1,"DELIBERATE_BAD_ABI");
      """)
    }
    assert(failure.getMessage.contains("DELIBERATE_BAD_ABI"))
  }
}
