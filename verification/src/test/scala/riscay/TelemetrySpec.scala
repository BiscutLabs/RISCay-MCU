// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class BdTelemetryFixture(p: SocParameters, inject: Boolean) extends MemoryResetFixture(p) {
  val pauseTelemetryCommands = IO(Input(Bool())); val pauseTelemetryReplies = IO(Input(Bool()))
  val telemetryPending = IO(Output(Bool())); val telemetryKind = IO(Output(UInt(2.W)))
  val injected = IO(Input(Bool())); val injectedValue = IO(Input(UInt(32.W)))
  val injectedValid = IO(Input(Bool())); val injectedCalibrated = IO(Input(Bool()))
  val visibleEvents = IO(Output(UInt(6.W))); visibleEvents := BoringUtils.bore(fabric.pending)
  val sampleView = BoringUtils.bore(fabric.hostSamples)
  val sampleSequence = IO(Output(UInt(32.W))); sampleSequence := sampleView(0).sequence
  val sampleValue = IO(Output(UInt(32.W))); sampleValue := sampleView(0).value
  val sampleValid = IO(Output(Bool())); sampleValid := sampleView(0).valid
  val sampleCalibrated = IO(Output(Bool())); sampleCalibrated := sampleView(0).calibrated
  val sampleFault = IO(Output(Bool())); sampleFault := sampleView(0).fault
  val sampleAge = IO(Output(UInt(32.W)))
  sampleAge := sampleView(0).age + BoringUtils.bore(fabric.telemetryInFlight).elapsedUpper + BoringUtils.bore(fabric.telemetryElapsed)
  if(inject) {
    val publication = BoringUtils.drive(fabric.publish)
    publication(0).valid := injected; publication(0).bits.value := injectedValue
    publication(0).bits.valid := injectedValid; publication(0).bits.calibrated := injectedCalibrated
  }
  fabric.telemetryReply.valid := telemetryReplyBridge.out.valid && !pauseTelemetryReplies
  telemetryReplyBridge.out.ready := fabric.telemetryReply.ready && !pauseTelemetryReplies
  telemetryCommandBridge.in.valid := fabric.telemetryCommand.valid && !pauseTelemetryCommands
  fabric.telemetryCommand.ready := telemetryCommandBridge.in.ready && !pauseTelemetryCommands
  telemetryPending := telemetryReplyBridge.out.valid; telemetryKind := telemetryReplyBridge.out.bits.kind
}

class ClickTelemetryFixture(p: SocParameters, inject: Boolean) extends ClickMemoryResetFixture(p) {
  val pauseTelemetryCommands = IO(Input(Bool())); val pauseTelemetryReplies = IO(Input(Bool()))
  val telemetryPending = IO(Output(Bool())); val telemetryKind = IO(Output(UInt(2.W)))
  val injected = IO(Input(Bool())); val injectedValue = IO(Input(UInt(32.W)))
  val injectedValid = IO(Input(Bool())); val injectedCalibrated = IO(Input(Bool()))
  val visibleEvents = IO(Output(UInt(6.W))); visibleEvents := BoringUtils.bore(fabric.pending)
  val sampleView = BoringUtils.bore(fabric.hostSamples)
  val sampleSequence = IO(Output(UInt(32.W))); sampleSequence := sampleView(0).sequence
  val sampleValue = IO(Output(UInt(32.W))); sampleValue := sampleView(0).value
  val sampleValid = IO(Output(Bool())); sampleValid := sampleView(0).valid
  val sampleCalibrated = IO(Output(Bool())); sampleCalibrated := sampleView(0).calibrated
  val sampleFault = IO(Output(Bool())); sampleFault := sampleView(0).fault
  val sampleAge = IO(Output(UInt(32.W)))
  sampleAge := sampleView(0).age + BoringUtils.bore(fabric.telemetryInFlight).elapsedUpper + BoringUtils.bore(fabric.telemetryElapsed)
  if(inject) {
    val publication = BoringUtils.drive(fabric.publish)
    publication(0).valid := injected; publication(0).bits.value := injectedValue
    publication(0).bits.valid := injectedValid; publication(0).bits.calibrated := injectedCalibrated
  }
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
integer cycles=0, lastGood=0;
always @(posedge serviceClock) begin
  cycles=cycles+1; if(injected && injectedValid) lastGood=cycles;
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
  @(negedge serviceClock); injected=1; injectedValue=value; injectedValid=valid; injectedCalibrated=calibrated;
  @(posedge serviceClock); #1; injected=0;
end endtask
reg [31:0] captured;
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(hz: Int = 10000000, inject: Boolean = false): SocTop = {
      val p=SocParameters(config,serviceHz=hz,watchdogCycles=10000000)
      if(click) new ClickTelemetryFixture(p,inject) else new BdTelemetryFixture(p,inject)
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
    test(s"$name: host event visibility survives stalled Observe replies and raw reset cancels dispatched events") {
      ClockedSimulation.run(fixture(),name+"-telemetry-event-reset","""
        #10000; write_bus(32'h30000018,1); write_bus(32'h3000001c,1);
        write_bus(32'h30000034,99); write_bus(32'h3000000c,63);
        pauseTelemetryReplies=1; gpioIn=1; wait(telemetryPending); #1000;
        if(!visibleEvents[2]) $fatal(1,"DISPATCHED_GPIO_EVENT_DISAPPEARED");
        read_words(3,0,5);
        if(!snapshot[2]) $fatal(1,"HOST_DISPATCHED_EVENT_DISAPPEARED");
        // Pulse entirely between clock edges: the raw reset pin must remember it.
        @(negedge serviceClock); #7; applicationReset=1; #1;
        if(gpioOut !== 0 || gpioOe !== 0 || visibleEvents !== 0) $fatal(1,"RAW_RESET_PROJECTION");
        #7; applicationReset=0; #10; pauseTelemetryReplies=0; #20000;
        if(gpioOut !== 0 || gpioOe !== 0 || visibleEvents[2]) $fatal(1,"STALE_TELEMETRY_REPLY_RESTORED_APP");
        issue(32'h30000034,0,0); answer(0);
      """,tasks)
    }
    test(s"$name: stalled acquisition batches preserve sequence, last good value, latest failure and elapsed age") {
      ClockedSimulation.run(fixture(1000,inject=true),name+"-telemetry-batches","""
        #10000; pauseTelemetryReplies=1; wait(telemetryPending);
        publish_sample(111,1,1); repeat(3) @(posedge serviceClock);
        publish_sample(222,0,1); repeat(5) @(posedge serviceClock);
        publish_sample(333,1,1); repeat(7) @(posedge serviceClock);
        publish_sample(444,0,1); repeat(11) @(posedge serviceClock);
        pauseTelemetryReplies=0; wait(sampleSequence == 4); @(negedge serviceClock);
        if(sampleValue !== 333 || sampleValid || !sampleFault || sampleCalibrated)
          $fatal(1,"COMPACTED_SAMPLE_STATUS");
        if(sampleAge !== cycles-lastGood) $fatal(1,"COMPACTED_SAMPLE_AGE actual=%d expected=%d",sampleAge,cycles-lastGood);
        repeat(40) @(negedge serviceClock);
        if(sampleSequence !== 4 || sampleAge !== cycles-lastGood) $fatal(1,"COMPACTED_SAMPLE_DUPLICATED_OR_LOST_TIME");
        // Pending observations must not starve these writes when every edge ticks.
        write_bus(32'h30000018,1); write_bus(32'h3000001c,1); write_bus(32'h30000034,777);
        issue(32'h30000034,0,0); answer(777);
        if(gpioOut !== 1 || gpioOe !== 1) $fatal(1,"CONTINUOUS_TICK_GPIO");
      """,tasks,deadlineNs=2000000)
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
      ClockedSimulation.run(fixture(inject=true),name+"-telemetry-host-stall","""
        #10000; publish_sample(12345,1,1); wait(sampleSequence == 1);
        pauseTelemetryReplies=1; gpioIn=1; wait(telemetryPending);
        publish_sample(99999,0,0); #2000000;
        read_words(2,0,0);
        if(snapshot[0+:32] !== 12345 || snapshot[96+:32] !== 1 || snapshot[32] || snapshot[33] || snapshot[64+:32] < 2)
          $fatal(1,"QUEUED_HOST_SAMPLE_FRESH_OR_INCOHERENT");
        pauseTelemetryReplies=0; wait(!telemetryPending);
        @(negedge serviceClock); pauseTelemetryReplies=1; wait(telemetryPending);
        read_words(2,0,0);
        if(snapshot[0+:32] !== 12345 || snapshot[96+:32] !== 1 || snapshot[32] || snapshot[33] || snapshot[64+:32] < 2)
          $fatal(1,"DISPATCHED_HOST_SAMPLE_FRESH_OR_INCOHERENT");
        pauseTelemetryReplies=0; wait(sampleSequence == 2); read_words(2,0,0);
        if(snapshot[0+:32] !== 12345 || snapshot[96+:32] !== 2 || snapshot[32] || !snapshot[35])
          $fatal(1,"HOST_FAILURE_COMMIT");
      """,tasks)
    }
  }
}
