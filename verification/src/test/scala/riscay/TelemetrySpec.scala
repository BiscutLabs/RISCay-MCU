// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdTelemetryFixture(p: SocParameters) extends MemoryResetFixture(p) {
  val pauseTelemetryCommands = IO(Input(Bool())); val pauseTelemetryReplies = IO(Input(Bool()))
  val telemetryPending = IO(Output(Bool())); val telemetryKind = IO(Output(UInt(2.W)))
  val visibleEvents = IO(Output(UInt(6.W))); visibleEvents := BoringUtils.bore(fabric.pending)
  val retainedEvents = IO(Output(UInt(6.W))); retainedEvents := BoringUtils.bore(fabric.pendingView)
  val bankReady=IO(Output(Bool()));bankReady:=fabric.telemetryBankReady
  val bankCaptured=IO(Output(Bool()));bankCaptured:=telemetryReplyBridge.out.fire
  val snapshotCaptured=IO(Output(Bool()));snapshotCaptured:=fabric.io.i2c.readStart
  val nativeClick=IO(Output(Bool()));nativeClick:=false.B
  val sampleView = BoringUtils.bore(fabric.hostSamples)
  val sampleSequence = IO(Output(UInt(32.W))); sampleSequence := sampleView(0).sequence
  val sampleValue = IO(Output(UInt(32.W))); sampleValue := sampleView(0).value
  val sampleValid = IO(Output(Bool())); sampleValid := sampleView(0).valid
  val sampleCalibrated = IO(Output(Bool())); sampleCalibrated := sampleView(0).calibrated
  val sampleFault = IO(Output(Bool())); sampleFault := sampleView(0).fault
  val sampleAge = IO(Output(UInt(32.W)))
  sampleAge := sampleView(0).age

  fabric.telemetryReply.valid := telemetryReplyBridge.out.valid && !pauseTelemetryReplies
  telemetryReplyBridge.out.ready := fabric.telemetryReply.ready && !pauseTelemetryReplies
  telemetryCommandBridge.in.valid := fabric.telemetryCommand.valid && !pauseTelemetryCommands
  fabric.telemetryCommand.ready := telemetryCommandBridge.in.ready && !pauseTelemetryCommands
  telemetryPending := telemetryReplyBridge.out.valid; telemetryKind := telemetryReplyBridge.out.bits.kind
}

class ClickTelemetryFixture(p: SocParameters) extends ClickMemoryResetFixture(p) {
  val pauseTelemetryCommands = IO(Input(Bool())); val pauseTelemetryReplies = IO(Input(Bool()))
  val telemetryPending = IO(Output(Bool())); val telemetryKind = IO(Output(UInt(2.W)))
  val visibleEvents = IO(Output(UInt(6.W))); visibleEvents := BoringUtils.bore(fabric.pending)
  val retainedEvents = IO(Output(UInt(6.W))); retainedEvents := BoringUtils.bore(fabric.pendingView)
  val bankReady=IO(Output(Bool()));bankReady:=fabric.telemetryBankReady
  val bankCaptured=IO(Output(Bool()));bankCaptured:=telemetryReplyBridge.out.fire
  val snapshotCaptured=IO(Output(Bool()));snapshotCaptured:=fabric.io.i2c.readStart
  val nativeClick=IO(Output(Bool()));nativeClick:=true.B
  val sampleView = BoringUtils.bore(fabric.hostSamples)
  val sampleSequence = IO(Output(UInt(32.W))); sampleSequence := sampleView(0).sequence
  val sampleValue = IO(Output(UInt(32.W))); sampleValue := sampleView(0).value
  val sampleValid = IO(Output(Bool())); sampleValid := sampleView(0).valid
  val sampleCalibrated = IO(Output(Bool())); sampleCalibrated := sampleView(0).calibrated
  val sampleFault = IO(Output(Bool())); sampleFault := sampleView(0).fault
  val sampleAge = IO(Output(UInt(32.W)))
  sampleAge := sampleView(0).age

  fabric.telemetryReply.valid := telemetryReplyBridge.out.valid && !pauseTelemetryReplies
  telemetryReplyBridge.out.ready := fabric.telemetryReply.ready && !pauseTelemetryReplies
  telemetryCommandBridge.in.valid := fabric.telemetryCommand.valid && !pauseTelemetryCommands
  fabric.telemetryCommand.ready := telemetryCommandBridge.in.ready && !pauseTelemetryCommands
  telemetryPending := telemetryReplyBridge.out.valid; telemetryKind := telemetryReplyBridge.out.bits.kind
}

class TelemetrySpec extends AnyFunSuite {
  private val config=McuConfiguration(16,16,1,Vector(MeasurementChannel(0,"test",1,0)),
    ApplicationProfile(1,1,"telemetry",Vector(HostRegister(0,"A")),Vector.empty))
  private val tasks="""
integer cycles=0, lastGood=0,bankEdge=-1;
always @(posedge reset) bankEdge=-1;
always @(posedge serviceClock) begin
  cycles=cycles+1;
  if(!reset && !nativeClick && bankEdge>=0 && cycles>bankEdge && cycles-bankEdge<5 && bankReady)
    $fatal(1,"SOFTWARE_BANK_READER_REOPENED_BEFORE_FULL_RETURN");
  if(!reset && bankCaptured) bankEdge=cycles;
  if(request_valid && request_ready && request_bits_operation==2 && request_bits_address==32'h3000002c && request_bits_data[0]) lastGood=cycles;
end
task issue(input [31:0] address,input [31:0] value,input bit writing);
begin
  @(negedge serviceClock); request_valid=1; request_bits_operation=writing ? 2 : 1;
  request_bits_address=address; request_bits_data=value; request_bits_mask=15;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0;
end endtask
task answer(input [31:0] expected);
begin
  wait(response_valid);
  if(response_bits_error || response_bits_data !== expected)
    $fatal(1,"TELEMETRY_BUS_RESPONSE actual=%h expected=%h",response_bits_data,expected);
  @(negedge serviceClock); response_ready=1;
  @(posedge serviceClock); #1; response_ready=0;
end endtask
task write_bus(input [31:0] address,input [31:0] value);
begin issue(address,value,1); answer(0); end endtask
task publish_sample(input [31:0] value,input bit valid,input bit calibrated);
begin
  write_bus(32'h30000028,value);
  write_bus(32'h3000002c,{30'b0,calibrated,valid});
end endtask
reg [31:0] captured;
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(hz: Int = 10000000): SocTop = {
      val p=SocParameters(config,serviceHz=hz,watchdogCycles=10000000)
      if(click) new ClickTelemetryFixture(p) else new BdTelemetryFixture(p)
    }
    test(s"$name: accepted software publication survives reset before its native commit dispatch") {
      ClockedSimulation.run(fixture(),name+"-telemetry-accepted-reset","""
        #10000; write_bus(32'h30000028,12345);
        pauseTelemetryCommands=1; #10000;
        issue(32'h3000002c,3,1);
        if(response_valid) $fatal(1,"TELEMETRY_RESPONSE_BEFORE_COMMIT");
        applicationReset=1; #600; applicationReset=0; #1000;
        pauseTelemetryCommands=0; #20000;
        if(response_valid) $fatal(1,"TELEMETRY_STALE_CPU_RESPONSE");
        read_words(2,0,0);
        if(snapshot[0+:32] !== 12345 || snapshot[96+:32] !== 1 || !snapshot[32] || !snapshot[36])
          $fatal(1,"TELEMETRY_ACCEPTED_SAMPLE_LOST");
      """,tasks)
    }
    test(s"$name: host event visibility is independent of stalled CPU telemetry and reset cancels application state") {
      ClockedSimulation.run(fixture(),name+"-telemetry-event-reset","""
        #10000; write_bus(32'h30000018,1); write_bus(32'h3000001c,1);
        write_bus(32'h30000034,99); write_bus(32'h3000000c,63);
        pauseTelemetryReplies=1; issue(32'h30000034,111,1); gpioIn=1; wait(telemetryPending); #1000;
        if(!visibleEvents[2]) $fatal(1,"DISPATCHED_GPIO_EVENT_DISAPPEARED");
        read_words(3,0,5);
        if(!snapshot[2]) $fatal(1,"HOST_DISPATCHED_EVENT_DISAPPEARED");
        // Pulse entirely between clock edges: the raw reset pin must remember it.
        @(negedge serviceClock); captured=retainedEvents; #7; applicationReset=1; #1;
        if(gpioOut !== 0 || gpioOe !== 0 || visibleEvents !== 0) $fatal(1,"RAW_RESET_PROJECTION");
        if(retainedEvents !== captured[5:0]) $fatal(1,"RAW_RESET_CHANGED_POR_EVENT_VIEW");
        #7; applicationReset=0; #10; pauseTelemetryReplies=0; #20000;
        if(gpioOut !== 0 || gpioOe !== 0 || visibleEvents[2]) $fatal(1,"STALE_TELEMETRY_REPLY_RESTORED_APP");
        if(retainedEvents[2]) $fatal(1,"SYNCHRONOUS_CANCELLATION_LOST");
        read_words(3,0,5);
        if(snapshot[2]) $fatal(1,"HOST_STALE_EVENT_AFTER_RESET");
        issue(32'h3000000c,0,0); wait(response_valid); captured=response_bits_data;
        if(captured[2]) $fatal(1,"MMIO_STALE_EVENT_AFTER_RESET"); answer(captured);
        issue(32'h30000034,0,0); answer(0);
      """,tasks)
    }
    test(s"$name: single-writer publications preserve sequence, last good value, latest failure and elapsed age") {
      ClockedSimulation.run(fixture(1000),name+"-telemetry-batches","""
        #10000;
        publish_sample(111,1,1); repeat(3) @(posedge serviceClock);
        publish_sample(222,0,1); repeat(5) @(posedge serviceClock);
        publish_sample(333,1,1); repeat(7) @(posedge serviceClock);
        publish_sample(444,0,1); repeat(11) @(posedge serviceClock);
        wait(sampleSequence == 4); @(negedge serviceClock);
        if(sampleValue !== 333 || sampleValid || !sampleFault || sampleCalibrated)
          $fatal(1,"COMPACTED_SAMPLE_STATUS");
        if(sampleAge !== cycles-lastGood) $fatal(1,"COMPACTED_SAMPLE_AGE actual=%d expected=%d",sampleAge,cycles-lastGood);
        repeat(40) @(negedge serviceClock);
        if(sampleSequence !== 4 || sampleAge !== cycles-lastGood) $fatal(1,"COMPACTED_SAMPLE_DUPLICATED_OR_LOST_TIME");
        // Timestamp projection must not produce transactions or starve writes when every edge ticks.
        write_bus(32'h30000018,1); write_bus(32'h3000001c,1); write_bus(32'h30000034,777);
        issue(32'h30000034,0,0); answer(777);
        if(gpioOut !== 1 || gpioOe !== 1) $fatal(1,"CONTINUOUS_TICK_GPIO");
      """,tasks,deadlineNs=2000000)
    }
    test(s"$name: host snapshot coincident with a software publication captures the whole old record") {
      ClockedSimulation.run(fixture(),name+"-sample-atomic","""
        #10000;publish_sample(32'ha5c35a3c,1,1);read_words(2,0,0);
        write_bus(32'h30000028,32'h5a3ca5c3);pauseTelemetryReplies=1;
        issue(32'h3000002c,1,1);wait(telemetryPending);response_ready=1;
        fork
          begin read_selected();end
          begin wait(snapshotCaptured);pauseTelemetryReplies=0;end
        join
        if(simultaneous!=1 || selected[0+:32]!==32'ha5c35a3c || selected[96+:32]!==1 ||
           selected[64+:32]!==snapshotAge || selected[32] || !selected[36] || selected[35])
          $fatal(1,"SAMPLE_SAME_EDGE_TORN");
        read_selected();
        if(selected[0+:32]!==32'h5a3ca5c3 || selected[96+:32]!==2 ||
           selected[64+:32]!==snapshotAge || !selected[32] || selected[36] || selected[35])
          $fatal(1,"SAMPLE_NEXT_READ_TORN");
      """,tasks+"""
integer simultaneous=0;reg [31:0] snapshotAge;reg [255:0] selected;
always @(posedge serviceClock) if(!reset && snapshotCaptured) begin
  snapshotAge=sampleAge;if(bankCaptured) simultaneous=simultaneous+1;
end
task read_selected;integer b;reg [7:0] value;begin
  start_bus();write_byte(8'h6b);
  for(b=0;b<36;b=b+1) begin read_byte(value,b==35);if(b<32) selected[8*b+:8]=value;end
  stop_bus();
end endtask
""")
    }
    test(s"$name: deadline replacement consumes queued old expiry while preserving new expiry and GPIO") {
      ClockedSimulation.run(fixture(100000),name+"-telemetry-deadlines","""
        #10000; write_bus(32'h30000008,timeNow+2);
        pauseTelemetryCommands=1; #10000; wait(visibleEvents[1]);
        issue(32'h30000008,timeNow+100,1); gpioIn=1;
        #1000; pauseTelemetryCommands=0; answer(0);
        issue(32'h3000000c,0,0); wait(response_valid); captured=response_bits_data;
        if(captured[1] || !captured[2]) $fatal(1,"QUEUED_DEADLINE_REPLACEMENT"); answer(captured);
        pauseTelemetryCommands=1; #10000;
        issue(32'h30000008,timeNow,1); #1000; pauseTelemetryCommands=0; answer(0);
        issue(32'h3000000c,0,0); wait(response_valid); captured=response_bits_data;
        if(!captured[1] || !captured[2]) $fatal(1,"NEW_DEADLINE_EXPIRY_LOST"); answer(captured);
      """,tasks)
    }
    test(s"$name: host snapshots suppress fresh-valid for queued and dispatched publications and age through stalls") {
      ClockedSimulation.run(fixture(),name+"-telemetry-host-stall","""
        #10000; publish_sample(12345,1,1); wait(sampleSequence == 1);
        write_bus(32'h30000028,99999); pauseTelemetryCommands=1;
        issue(32'h3000002c,0,1); #2000000;
        read_words(2,0,0);
        if(snapshot[0+:32] !== 12345 || snapshot[96+:32] !== 1 || snapshot[32] || snapshot[33] || snapshot[64+:32] < 2)
          $fatal(1,"QUEUED_HOST_SAMPLE_FRESH_OR_INCOHERENT");
        pauseTelemetryReplies=1; pauseTelemetryCommands=0; wait(telemetryPending);
        read_words(2,0,0);
        if(snapshot[0+:32] !== 12345 || snapshot[96+:32] !== 1 || snapshot[32] || snapshot[33] || snapshot[64+:32] < 2)
          $fatal(1,"DISPATCHED_HOST_SAMPLE_FRESH_OR_INCOHERENT");
        pauseTelemetryReplies=0; answer(0); wait(sampleSequence == 2); read_words(2,0,0);
        if(snapshot[0+:32] !== 12345 || snapshot[96+:32] !== 2 || snapshot[32] || !snapshot[35])
          $fatal(1,"HOST_FAILURE_COMMIT");
      """,tasks)
    }
  }
}
