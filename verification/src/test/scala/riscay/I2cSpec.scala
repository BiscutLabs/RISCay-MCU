// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdI2cFixture(p: SocParameters) extends FabricFixture(p) {
  val frameRun=IO(Input(Bool())); val resetContext=IO(Input(Bool()))
  val received=IO(Output(Bool())); val frameReset=IO(Output(Bool()))
  val readStarted=IO(Output(Bool())); readStarted:=host.host.readStart
  val frameLength=IO(Output(UInt(6.W))); val frameByte=IO(Output(UInt(8.W)))
  val frameOverflow=IO(Output(Bool())); val busBusy=IO(Output(Bool()))
  dontTouch(frameRun) // Testbench stalls frame-crossing admission.
  host.host.resetActive:=resetContext
  host.host.readWord:=VecInit((0 until 9).map(i => ((0x89abcdefL ^ (i*0x10203041L)) & 0xffffffffL).U(32.W)))(host.host.wordIndex)
  received:=host.host.frame.valid; frameReset:=host.host.frame.bits.resetActive
  frameLength:=host.host.frame.bits.frame.length; frameByte:=host.host.frame.bits.frame.bytes(0)
  frameOverflow:=host.host.frame.bits.frame.overflow; busBusy:=host.host.busy
}
class ClickI2cFixture(p: SocParameters) extends ClickFabricFixture(p) {
  val frameRun=IO(Input(Bool())); val resetContext=IO(Input(Bool()))
  val received=IO(Output(Bool())); val frameReset=IO(Output(Bool()))
  val readStarted=IO(Output(Bool())); readStarted:=host.host.readStart
  val frameLength=IO(Output(UInt(6.W))); val frameByte=IO(Output(UInt(8.W)))
  val frameOverflow=IO(Output(Bool())); val busBusy=IO(Output(Bool()))
  dontTouch(frameRun) // Testbench stalls frame-crossing admission.
  host.host.resetActive:=resetContext
  host.host.readWord:=VecInit((0 until 9).map(i => ((0x89abcdefL ^ (i*0x10203041L)) & 0xffffffffL).U(32.W)))(host.host.wordIndex)
  received:=host.host.frame.valid; frameReset:=host.host.frame.bits.resetActive
  frameLength:=host.host.frame.bits.frame.length; frameByte:=host.host.frame.bits.frame.bytes(0)
  frameOverflow:=host.host.frame.bits.frame.overflow; busBusy:=host.host.busy
}

class I2cSpec extends AnyFunSuite {
  private val config=McuConfiguration(16,32,0,Vector.empty,ApplicationProfile(1,1,"i2c",Vector.empty,Vector.empty))
  private def top(click: Boolean,hz: Int): SocTop = {
    val p=SocParameters(config,serviceHz=hz,watchdogCycles=100000,i2cIdleCycles=256)
    if(click) new ClickI2cFixture(p) else new BdI2cFixture(p)
  }
  private val tasks="""
integer frames=0, snapshots=0; reg [23:0] frameOrder=0; reg lastReset=0,lastOverflow=0; reg [5:0] lastLength; reg [7:0] firstByte;
always @(negedge serviceClock) begin
  #1;
  if (dut.ca_child_i2c.localReset_release_1 === 1'b1) begin
    if (dut.ca_child_i2c.ca_child_frame_bridge.out_ready !== 0 ||
        dut.ca_child_i2c.ca_child_snapshot_bridge.out_ready !== 0 || received !== 0 || readStarted !== 0)
      $fatal(1,"I2C_RESET_PUBLICATION");
  end else if (dut.ca_child_i2c.localReset_release_1 === 1'b0) begin
    if (dut.ca_child_i2c.ca_child_frame_bridge.out_ready !== 1 ||
        dut.ca_child_i2c.ca_child_snapshot_bridge.out_ready !== 1) $fatal(1,"I2C_RELEASE_ADMISSION");
  end
end
always @(posedge serviceClock) if(readStarted) snapshots=snapshots+1;
always @(posedge serviceClock) if(received) begin
  frames=frames+1; frameOrder={frameOrder[15:0],frameByte}; lastReset=frameReset; lastLength=frameLength; firstByte=frameByte; lastOverflow=frameOverflow;
end
always @(frameRun) begin
  if(frameRun) release dut.ca_child_i2c.ca_child_frame_bridge.state;
  else force dut.ca_child_i2c.ca_child_frame_bridge.state=2'b0;
end
// 400 kHz, equal 1250 ns phases. SDA changes100 ns after falling SCL,
// exercising separate synchronized samples without violating the wire setup.
reg checkDrive=0;
always @(sdaLow) if(checkDrive && scl && !reset) $fatal(1,"I2C_SDA_CHANGED_WHILE_SCL_HIGH");
task fast_start; begin checkDrive=0; scl=0; hostLow=0; #1250; scl=1; #1250; hostLow=1; #1250; scl=0; end endtask
task fast_stop; begin checkDrive=0; #100; hostLow=1; #1150; scl=1; #1250; hostLow=0; #1250; end endtask
task fast_byte(input [7:0] value,input ackExpected); integer b; begin
  checkDrive=1;
  for(b=7;b>=0;b=b-1) begin #100; hostLow=!value[b]; #1150; scl=1; #1250; scl=0; end
  #100; hostLow=0; #1150;
  if(busSda !== !ackExpected) $fatal(1,"I2C_FAST_ACK byte=%h SDA=%b",value,busSda);
  scl=1; #1250; scl=0;
end endtask
task fast_read(output [7:0] value,input last); integer b; begin
  for(b=7;b>=0;b=b-1) begin #1250; scl=1; #625; value[b]=busSda; #625; scl=0; end
  #100; hostLow=!last; #1150; scl=1; #1250; scl=0; #100; hostLow=0;
end endtask
task fast_word(input [31:0] word); integer b; begin
  for(b=0;b<4;b=b+1) fast_byte(word[8*b+:8],1);
end endtask
integer i,saved; reg [7:0] value; reg [31:0] expected;
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    for(hz <- Seq(3200000,20000000)) test(s"$name I2C wire: 400kHz at $hz service Hz with maximum native delays") {
      ClockedSimulation.run(top(click,hz),name+"-i2c-wire", """
        frameRun=1; #5000;
        fast_start(); fast_byte(8'h6a,1); fast_byte(8'h55,1); fast_stop(); #5000;
        if(frames != 1 || lastLength != 1 || firstByte != 8'h55 || lastOverflow || lastReset) $fatal(1,"I2C_WIRE_FRAME");
        fast_start(); fast_byte(8'h6b,1);
        for(i=0;i<36;i=i+1) begin
          fast_read(value,i==35); expected=32'h89abcdef ^ ((i/4)*32'h10203041);
          if(value !== ((expected >> (8*(i%4))) & 255)) $fatal(1,"I2C_WIRE_READ i=%d got=%h expected=%h",i,value,expected);
        end
        fast_stop(); #5000;
        // A short read's NACK releases activity without requiring a STOP.
        fast_start(); fast_byte(8'h6b,1); fast_read(value,1); #5000;
        if(sdaLow || busBusy) $fatal(1,"I2C_SHORT_NACK"); fast_stop();
        // Address-only probes never publish frames.
        fast_start(); fast_byte(8'h6a,1); fast_stop(); #5000;
        if(frames != 1) $fatal(1,"I2C_PROBE_FRAME");
        // Oversize and incomplete final bytes stay marked invalid.
        fast_start(); fast_byte(8'h6a,1); for(i=0;i<34;i=i+1) fast_byte(i,i<33);
        fast_stop(); #5000; if(frames != 2 || lastLength != 33 || !lastOverflow) $fatal(1,"I2C_OVERFLOW");
        fast_start(); fast_byte(8'h6a,1); fast_byte(8'h33,1);
        repeat(3) begin #100; hostLow=0; #1150; scl=1; #1250; scl=0; end
        fast_stop(); #5000; if(frames != 3 || !lastOverflow) $fatal(1,"I2C_PARTIAL");
      """,tasks,serviceHalfPeriodNs=5.0e8/hz,maximumDelaySubtree=Some("i2c"))
    }
    for(hz <- Seq(3200000,20000000)) test(s"$name I2C loader: earliest 400kHz status reads after VERIFY, BEGIN, WRITE and LOCK at $hz Hz") {
      val p=SocParameters(config,serviceHz=hz,watchdogCycles=100000)
      def fixture: SocTop=if(click) new ClickFabricFixture(p) else new FabricFixture(p)
      val crc=new java.util.zip.CRC32; Seq(0x73,0,0,0).foreach(x => crc.update(x))
      val wireTasks=tasks.substring(tasks.indexOf("// 400 kHz"))
      val earliestRead="""
        // STOP already left SCL high for 1250 ns: complete 1300 ns bus-free,
        // issue START directly, then 600 ns START hold. No helper preamble or poll.
        #50; hostLow=1; #600; scl=0; fast_byte(8'h6b,1);
        for(i=0;i<36;i=i+1) begin
          fast_read(value,i==35);
          if(i<32) snapshot[8*i+:8]=value; else supported[8*(i-32)+:8]=value;
        end
        fast_stop();
      """
      ClockedSimulation.run(fixture,name+"-i2c-earliest-status",s"""
        // SELECT commits on repeated START; the first read must use the new bank.
        fast_start(); fast_byte(8'h6a,1); fast_byte(0,1); fast_byte(1,1); fast_byte(0,1); fast_byte(0,1);
        checkDrive=0; hostLow=0; #1300; scl=1; #650; hostLow=1; #600; scl=0;
        fast_byte(8'h6b,1);
        for(i=0;i<36;i=i+1) begin
          fast_read(value,i==35);
          if(i<32) snapshot[8*i+:8]=value; else supported[8*(i-32)+:8]=value;
        end
        fast_stop();
        if(snapshot[0+:32] !== 0 || snapshot[32+:32] !== 0 || snapshot[96+:32] !== 1 || supported !== 255)
          $$fatal(1,"I2C_REPEATED_START_SELECT");
        fast_start(); fast_byte(8'h6a,1); fast_byte(1,1);
        fast_word(4); fast_word(0); fast_word(32'h${crc.getValue.toHexString}); fast_word(32'h00010000);
        fast_word(32); fast_word(0); fast_word(0); fast_word(32'h12345678); fast_stop();
        fast_start(); fast_byte(8'h6a,1); fast_byte(2,1); fast_word(0); fast_word(32'h00000073); fast_stop();
        // Loader remains selected: no extra SELECT may hide reply latency.
        fast_start(); fast_byte(8'h6a,1); fast_byte(3,1); fast_stop();
        $earliestRead
        if(snapshot[0+:32] !== 2 || snapshot[32+:32] !== 1 || snapshot[160+:32] !== 0 ||
           snapshot[224+:32] !== 4 || supported !== 255) $$fatal(1,"I2C_EARLIEST_VERIFY_STATUS");
        // BEGIN must invalidate the previously ready image before any new PUT.
        fast_start(); fast_byte(8'h6a,1); fast_byte(1,1);
        fast_word(4); fast_word(0); fast_word(32'h${crc.getValue.toHexString}); fast_word(32'h00010000);
        fast_word(32); fast_word(0); fast_word(0); fast_word(32'h12345678); fast_stop();
        $earliestRead
        if(snapshot[0+:32] !== 1 || snapshot[32+:32] !== 0 || snapshot[160+:32] !== 0 ||
           snapshot[224+:32] !== 0 || supported !== 255) $$fatal(1,"I2C_EARLIEST_BEGIN_STATUS");
        fast_start(); fast_byte(8'h6a,1); fast_byte(2,1); fast_word(0); fast_word(32'h00000073); fast_stop();
        $earliestRead
        if(snapshot[0+:32] !== 1 || snapshot[32+:32] !== 0 || snapshot[128+:32] !== 0 ||
           snapshot[160+:32] !== 0 || snapshot[224+:32] !== 4 || supported !== 255)
          $$fatal(1,"I2C_EARLIEST_WRITE_STATUS");
        // VERIFY independently checks the CRC generated by the completed WRITE.
        fast_start(); fast_byte(8'h6a,1); fast_byte(3,1); fast_stop();
        fast_start(); fast_byte(8'h6a,1); fast_byte(4,1); fast_stop();
        $earliestRead
        if(snapshot[0+:32] !== 2 || snapshot[32+:32] !== 1 || snapshot[64+:32] !== 1 ||
           snapshot[160+:32] !== 0 || snapshot[224+:32] !== 4 || supported !== 255)
          $$fatal(1,"I2C_EARLIEST_LOCK_STATUS");
        fast_start(); fast_byte(8'h6a,1); fast_byte(2,1); fast_word(0); fast_word(0); fast_stop();
        $earliestRead
        if(snapshot[0+:32] !== 2 || snapshot[32+:32] !== 1 || snapshot[64+:32] !== 1 ||
           snapshot[160+:32] !== 2 || snapshot[192+:32] !== 32'h12345678 || snapshot[224+:32] !== 4)
          $$fatal(1,"I2C_EARLIEST_LOCK_REJECTION");
      """,wireTasks,serviceHalfPeriodNs=5.0e8/hz,maximumDelaySubtree=Some("i2c"))
    }
    test(s"$name I2C occupied edge ring retains slots through publication backpressure and recovers in order") {
      val fields=Seq("rise","fall","start","stop","timeout","sda","readWord","resetActive","programBusy","resetEpoch")
      val slotBus=(0 until 8).flatMap(i => fields.map(f => s"dut.ca_child_i2c.slots_${i}_$f")).mkString("{",",","}")
      ClockedSimulation.run(top(click,10000000),name+"-i2c-ring",s"""
        frameRun=1; #5000; frameRun=0;
        fast_start(); fast_byte(8'h6a,1); fast_byte(9,1); fast_stop();
        fast_start(); fast_byte(8'h6a,1); fast_byte(10,1); fast_stop(); #2000;
        // Second STOP is backpressured; queue START and the first address bit.
        fast_start(); #100; hostLow=1; #1150; scl=1; #1250; scl=0; #1000;
        occupied=(dut.ca_child_i2c.tail-dut.ca_child_i2c.ca_child_native.observedBits[339:336])&15;
        if(occupied<3 || occupied>8 || frames!=0) $$fatal(1,"I2C_RING_NOT_OCCUPIED");
        heldSlots=$slotBus; heldHead=dut.ca_child_i2c.ca_child_native.observedBits[339:336];
        #1000;
        if(heldSlots !== $slotBus || heldHead !== dut.ca_child_i2c.ca_child_native.observedBits[339:336])
          $$fatal(1,"I2C_OCCUPIED_SLOT_MUTATED");
        frameRun=1; #5000;
        if(frames!=2 || frameOrder[15:0]!==16'h090a) $$fatal(1,"I2C_RING_FRAME_ORDER");
        value=8'h6a;
        for(i=6;i>=0;i=i-1) begin #100; hostLow=!value[i]; #1150; scl=1; #1250; scl=0; end
        #100; hostLow=0; #1150; if(busSda) $$fatal(1,"I2C_RING_ADDRESS_ACK"); scl=1; #1250; scl=0;
        fast_byte(11,1); fast_stop(); #10000;
        if(frames!=3 || frameOrder!==24'h090a0b || lastOverflow) $$fatal(1,"I2C_RING_RECOVERY");
      """,tasks+"\nreg [831:0] heldSlots; reg [3:0] heldHead; integer occupied;\n")
    }
    test(s"$name I2C rejects overflowing a deliberately blocked edge ring") {
      val error=intercept[IllegalArgumentException] {
        ClockedSimulation.run(top(click,10000000),name+"-i2c-ring-overflow", """
          frameRun=1; #5000; frameRun=0;
          fast_start(); fast_byte(8'h6a,1); fast_byte(9,1); fast_stop();
          fast_start(); fast_byte(8'h6a,1); fast_byte(10,1); fast_stop();
          fast_start(); repeat(12) begin #1250; scl=1; #1250; scl=0; end
        """,tasks)
      }
      assert(error.getMessage.contains("I2C_EDGE_RING_OVERFLOW"),error.getMessage)
    }
    test(s"$name I2C POR cancels a held read snapshot and permits a fresh read") {
      ClockedSimulation.run(top(click,10000000),name+"-i2c-snapshot-reset", """
        frameRun=1; #5000;
        force dut.ca_child_i2c.ca_child_snapshot_bridge.state=2'b0;
        fast_start(); fast_byte(8'h6b,1); #5000;
        if(snapshots != 0 || dut.ca_child_i2c.ca_child_snapshot_bridge.in_req ===
            dut.ca_child_i2c.ca_child_snapshot_bridge.in_ack) $fatal(1,"I2C_SNAPSHOT_NOT_HELD");
        reset=1; #5000; release dut.ca_child_i2c.ca_child_snapshot_bridge.state;
        hostLow=0; scl=1; #5000; reset=0; #10000;
        if(snapshots != 0) $fatal(1,"I2C_SNAPSHOT_POR_REPLAY");
        fast_start(); fast_byte(8'h6b,1); fast_read(value,1); fast_stop(); #5000;
        if(snapshots != 1 || value !== 8'hef || busBusy || sdaLow) $fatal(1,"I2C_SNAPSHOT_POR_RECOVERY");
      """,tasks)
    }
    test(s"$name I2C frame crossing retains complete reset episodes and POR cancels held effects") {
      ClockedSimulation.run(top(click,10000000),name+"-i2c-reset", """
        frameRun=1; #5000; frameRun=0;
        fast_start(); fast_byte(8'h6a,1); fast_byte(6,1); fast_stop(); #5000;
        if(frames != 0) $fatal(1,"I2C_STALL_NOT_HELD");
        resetContext=1; #5000; resetContext=0; #5000; resetContext=1; #5000; resetContext=0; #5000;
        frameRun=1; #10000; if(frames != 1 || !lastReset || firstByte != 6) $fatal(1,"I2C_RESET_HISTORY_LOST");
        fast_start(); fast_byte(8'h6a,1); fast_byte(6,1); fast_stop(); #10000;
        if(frames != 2 || lastReset) $fatal(1,"I2C_FRESH_RESET_DEBT");
        frameRun=0; fast_start(); fast_byte(8'h6a,1); fast_byte(6,1); fast_stop(); #5000;
        reset=1; #5000; frameRun=1; #5000; reset=0; #10000;
        if(frames != 2) $fatal(1,"I2C_POR_REPLAY");
        fast_start(); fast_byte(8'h6a,1); fast_byte(6,1); fast_stop(); #10000;
        if(frames != 3 || lastReset) $fatal(1,"I2C_POR_RECOVERY");
      """,tasks)
    }
  }
}
