// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Production owners and senders; only the stall/gated-clock controls are test logic. */
class BdCommandBorrowFixture(p: SocParameters, fault: String = "") extends BdHousekeepingFixture(p) {
  val applicationReset=IO(Input(Bool()))
  applicationResetRequest:=reset.asBool || watchdog.io.expired || applicationReset
  val stopWorkClock=IO(Input(Bool()))
  val enabled=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(!stopWorkClock,false.B) }
  workClock:=(serviceClock.asBool && enabled).asClock
  fabric.io.clockRunning:=enabled; host.frameAcceptEnable:=enabled
  val workRunning=IO(Output(Bool())); workRunning:=enabled
  val pauseNative=IO(Input(UInt(2.W))); val pauseReturn=IO(Input(UInt(2.W)))
  // Retain the known idle phase before inserting a stall. The actual signal is
  // direct whenever the stall is disabled; this is not a production crossing.
  val nativeRequests=Seq(telemetry.command.req,housekeeping.command.req)
  val nativeAcks=Seq(telemetry.command.ack,housekeeping.command.ack)
  val senderRequests=Seq(telemetryCommandBridge.out.req,housekeepingCommandBridge.out.req)
  val senderAcks=Seq(telemetryCommandBridge.out.ack,housekeepingCommandBridge.out.ack)
  for(i <- 0 until 2) {
    val oldRequest=withClockAndReset(serviceClock,reset) {
      val value=RegInit(false.B); when(!pauseNative(i)) { value:=senderRequests(i) }; value
    }
    val oldAck=withClockAndReset(serviceClock,reset) {
      val value=RegInit(false.B); when(!pauseReturn(i)) { value:=nativeAcks(i) }; value
    }
    nativeRequests(i):=Mux(pauseNative(i),oldRequest,senderRequests(i))
    senderAcks(i):=Mux(pauseReturn(i),oldAck,nativeAcks(i))
  }
  if(fault=="house-live") { housekeeping.command.bits:=fabric.housekeepingCommand.bits }
  if(fault=="telemetry-live") {
    telemetry.command.bits.data:=Mux(telemetryCommandBridge.out.bits.kind === TelemetryKind.Commit.U,
      fabric.telemetryCommand.bits.data,0.U)
  }
  val houseNative=IO(Output(new HousekeepingCommand)); houseNative:=housekeeping.command.bits
  val houseBorrow=IO(Output(new HousekeepingCommand)); houseBorrow:=fabric.io.housekeepingPayload
  val houseSenderIdle=IO(Output(Bool())); houseSenderIdle:=housekeepingCommandBridge.in.ready
  val houseNativeRequest=IO(Output(Bool())); houseNativeRequest:=housekeeping.command.req
  val houseNativeAck=IO(Output(Bool())); houseNativeAck:=housekeeping.command.ack
  val periodWaiting=IO(Output(Bool())); periodWaiting:=fabric.io.controlReply.valid && fabric.io.controlReply.bits.periodUpdate
  val periodAccepted=IO(Output(Bool())); periodAccepted:=periodWaiting && fabric.io.controlReply.ready
  val telemetryAccepted=IO(Output(Bool())); telemetryAccepted:=fabric.telemetryCommand.fire
  val telemetryCommandView=IO(Output(new TelemetryCommand(p.softwareSampleChannels.size))); telemetryCommandView:=fabric.telemetryCommand.bits
  val telemetryNative=IO(Output(new TelemetryCommand(p.softwareSampleChannels.size))); telemetryNative:=telemetry.command.bits
  val telemetrySenderIdle=IO(Output(Bool())); telemetrySenderIdle:=telemetryCommandBridge.in.ready
  val telemetryNativeRequest=IO(Output(Bool())); telemetryNativeRequest:=telemetry.command.req
  val telemetryNativeAck=IO(Output(Bool())); telemetryNativeAck:=telemetry.command.ack
  val samples=BoringUtils.bore(fabric.hostSamples); val sample=samples(0)
  val observedSampleValue=IO(Output(UInt(32.W))); observedSampleValue:=sample.value
  val observedSampleSequence=IO(Output(UInt(32.W))); observedSampleSequence:=sample.sequence
  val nativeClick=IO(Output(Bool())); nativeClick:=false.B
}
/** Production owners and senders; only the stall/gated-clock controls are test logic. */
class ClickCommandBorrowFixture(p: SocParameters, fault: String = "") extends ClickHousekeepingFixture(p) {
  val applicationReset=IO(Input(Bool()))
  applicationResetRequest:=reset.asBool || watchdog.io.expired || applicationReset
  val stopWorkClock=IO(Input(Bool()))
  val enabled=withClockAndReset((!serviceClock.asBool).asClock,reset) { RegNext(!stopWorkClock,false.B) }
  workClock:=(serviceClock.asBool && enabled).asClock
  fabric.io.clockRunning:=enabled; host.frameAcceptEnable:=enabled
  val workRunning=IO(Output(Bool())); workRunning:=enabled
  val pauseNative=IO(Input(UInt(2.W))); val pauseReturn=IO(Input(UInt(2.W)))
  // Retain the known idle phase before inserting a stall. The actual signal is
  // direct whenever the stall is disabled; this is not a production crossing.
  val nativeRequests=Seq(telemetry.command.req,housekeeping.command.req)
  val nativeAcks=Seq(telemetry.command.ack,housekeeping.command.ack)
  val senderRequests=Seq(telemetryCommandBridge.out.req,housekeepingCommandBridge.out.req)
  val senderAcks=Seq(telemetryCommandBridge.out.ack,housekeepingCommandBridge.out.ack)
  for(i <- 0 until 2) {
    val oldRequest=withClockAndReset(serviceClock,reset) {
      val value=RegInit(false.B); when(!pauseNative(i)) { value:=senderRequests(i) }; value
    }
    val oldAck=withClockAndReset(serviceClock,reset) {
      val value=RegInit(false.B); when(!pauseReturn(i)) { value:=nativeAcks(i) }; value
    }
    nativeRequests(i):=Mux(pauseNative(i),oldRequest,senderRequests(i))
    senderAcks(i):=Mux(pauseReturn(i),oldAck,nativeAcks(i))
  }
  if(fault=="house-live") { housekeeping.command.bits:=fabric.housekeepingCommand.bits }
  if(fault=="telemetry-live") {
    telemetry.command.bits.data:=Mux(telemetryCommandBridge.out.bits.kind === TelemetryKind.Commit.U,
      fabric.telemetryCommand.bits.data,0.U)
  }
  val houseNative=IO(Output(new HousekeepingCommand)); houseNative:=housekeeping.command.bits
  val houseBorrow=IO(Output(new HousekeepingCommand)); houseBorrow:=fabric.io.housekeepingPayload
  val houseSenderIdle=IO(Output(Bool())); houseSenderIdle:=housekeepingCommandBridge.in.ready
  val houseNativeRequest=IO(Output(Bool())); houseNativeRequest:=housekeeping.command.req
  val houseNativeAck=IO(Output(Bool())); houseNativeAck:=housekeeping.command.ack
  val periodWaiting=IO(Output(Bool())); periodWaiting:=fabric.io.controlReply.valid && fabric.io.controlReply.bits.periodUpdate
  val periodAccepted=IO(Output(Bool())); periodAccepted:=periodWaiting && fabric.io.controlReply.ready
  val telemetryAccepted=IO(Output(Bool())); telemetryAccepted:=fabric.telemetryCommand.fire
  val telemetryCommandView=IO(Output(new TelemetryCommand(p.softwareSampleChannels.size))); telemetryCommandView:=fabric.telemetryCommand.bits
  val telemetryNative=IO(Output(new TelemetryCommand(p.softwareSampleChannels.size))); telemetryNative:=telemetry.command.bits
  val telemetrySenderIdle=IO(Output(Bool())); telemetrySenderIdle:=telemetryCommandBridge.in.ready
  val telemetryNativeRequest=IO(Output(Bool())); telemetryNativeRequest:=telemetry.command.req
  val telemetryNativeAck=IO(Output(Bool())); telemetryNativeAck:=telemetry.command.ack
  val samples=BoringUtils.bore(fabric.hostSamples); val sample=samples(0)
  val observedSampleValue=IO(Output(UInt(32.W))); observedSampleValue:=sample.value
  val observedSampleSequence=IO(Output(UInt(32.W))); observedSampleSequence:=sample.sequence
  val nativeClick=IO(Output(Bool())); nativeClick:=true.B
}

class CommandBorrowSpec extends AnyFunSuite {
  private val config=McuConfiguration(16,16,1,Vector(MeasurementChannel(0,"sample",1,0)),
    ApplicationProfile(1,1,"command-borrow",Vector(HostRegister(0,"A"),HostRegister(17,"B")),Vector.empty))
  private val parameters=SocParameters(config,staleMs=100,watchdogCycles=1000000,
    lowPower=Some(LowPowerParameters()),adc=Some(AdcParameters(halfPeriodCycles=2,intervalCycles=100000)))
  private val monitor="""
integer houseLoans=0,telemetryLoans=0,houseCaptures=0,telemetryCaptures=0,periodEffects=0,observations=0;
integer savedHouse,savedTelemetry,savedCaptures,houseRecoveryLoans=0,savedRecoveries;
reg [31:0] savedSampleSequence;
reg houseActive=0,telemetryActive=0;
reg [47:0] heldTelemetry;
reg [15:0] adcShift;
always @(negedge adcCsN) begin adcShift={4'hf,12'd2200};adcMiso=adcShift[15];end
always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1;adcMiso=adcShift[15];end
task acquire;begin
  wait(!adcActive);@(negedge serviceClock);injectSample=1;
  @(posedge serviceClock);#1;injectSample=0;wait(adcActive);wait(!adcActive);
end endtask
wire [$bits({houseCommand_recovery,houseCommand_timeValid,houseCommand_target,
  houseCommand_elapsed,houseCommand_elapsedOverflow,
  houseCommand_resetApplication,houseCommand_started,houseCommand_parked,houseCommand_adcBusy,houseCommand_discard,
  houseCommand_write,houseCommand_offset,houseCommand_data,houseCommand_waitAccepted,houseCommand_periodUpdate,
  houseCommand_period,houseCommand_cpuCompletion})-1:0] packedHouseCommand={houseCommand_recovery,houseCommand_timeValid,houseCommand_target,
  houseCommand_elapsed,houseCommand_elapsedOverflow,
  houseCommand_resetApplication,houseCommand_started,houseCommand_parked,houseCommand_adcBusy,houseCommand_discard,
  houseCommand_write,houseCommand_offset,houseCommand_data,houseCommand_waitAccepted,houseCommand_periodUpdate,
  houseCommand_period,houseCommand_cpuCompletion};
wire [$bits({houseNative_recovery,houseNative_timeValid,houseNative_target,
  houseNative_elapsed,houseNative_elapsedOverflow,
  houseNative_resetApplication,houseNative_started,houseNative_parked,houseNative_adcBusy,houseNative_discard,
  houseNative_write,houseNative_offset,houseNative_data,houseNative_waitAccepted,houseNative_periodUpdate,
  houseNative_period,houseNative_cpuCompletion})-1:0] packedHouseNative={houseNative_recovery,houseNative_timeValid,houseNative_target,
  houseNative_elapsed,houseNative_elapsedOverflow,
  houseNative_resetApplication,houseNative_started,houseNative_parked,houseNative_adcBusy,houseNative_discard,
  houseNative_write,houseNative_offset,houseNative_data,houseNative_waitAccepted,houseNative_periodUpdate,
  houseNative_period,houseNative_cpuCompletion};
wire [47:0] packedTelemetryCommand={telemetryCommandView_recovery,telemetryCommandView_kind,
  telemetryCommandView_offset,telemetryCommandView_data,telemetryCommandView_appIndex};
wire [47:0] packedTelemetryNative={telemetryNative_recovery,telemetryNative_kind,
  telemetryNative_offset,telemetryNative_data,telemetryNative_appIndex};
// Icarus resolves $bits of a forward-declared net as zero. Declare the saved
// payload after the complete packed wire, and check both sides cover its width.
reg [$bits(packedHouseCommand)-1:0] heldHouse;
initial if($bits(heldHouse)!=$bits(packedHouseCommand) ||
  $bits(heldHouse)!=$bits(packedHouseNative)) $fatal(1,"HOUSEKEEPING_MONITOR_WIDTH");
always @(posedge observedWorkClock) if(!reset) begin
  if(houseAccepted) begin
    heldHouse=packedHouseCommand;houseActive=1;houseLoans=houseLoans+1;
    if(houseCommand_recovery) houseRecoveryLoans=houseRecoveryLoans+1;
  end
  if(telemetryAccepted) begin heldTelemetry=packedTelemetryCommand;telemetryActive=1;telemetryLoans=telemetryLoans+1;end
  if(periodAccepted) periodEffects=periodEffects+1;
end
// Check the complete native command throughout the sender's full lifetime,
// including settling, capture, reply publication and delayed return.
always begin #2; if(!reset) begin
  if(houseActive) begin
    if(packedHouseNative!==heldHouse) $fatal(1,"HOUSEKEEPING_BORROW_CHANGED");
    if(houseNative_recovery && houseBorrow_recovery!==0) $fatal(1,"HOUSEKEEPING_RECOVERY_ROLE_COPIED");
    if(houseSenderIdle) houseActive=0;
  end
  if(telemetryActive) begin
    if(packedTelemetryNative!==heldTelemetry) $fatal(1,"TELEMETRY_BORROW_CHANGED");
    if(telemetrySenderIdle) telemetryActive=0;
  end
  if(telemetryNative_kind!=1 && {telemetryNative_offset,telemetryNative_data,telemetryNative_appIndex}!==0)
    $fatal(1,"TELEMETRY_NONCOMMIT_NOT_MASKED");
end end
always @(houseNativeAck) if(!reset && (nativeClick || houseNativeAck)) begin
  #0.001; if(houseActive && packedHouseNative!==heldHouse) $fatal(1,"HOUSEKEEPING_CAPTURE_IDENTITY");
  houseCaptures=houseCaptures+1;
end
always @(telemetryNativeAck) if(!reset && (nativeClick || telemetryNativeAck)) begin
  #0.001; if(telemetryActive && packedTelemetryNative!==heldTelemetry) $fatal(1,"TELEMETRY_CAPTURE_IDENTITY");
  telemetryCaptures=telemetryCaptures+1;
  if(telemetryNative_kind==0) observations=observations+1;
end
task issue(input [31:0] address,input [31:0] value); begin
  @(negedge serviceClock); request_valid=1;request_bits_operation=2;
  request_bits_address=address;request_bits_data=value;request_bits_mask=15;
  @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);
  #1;request_valid=0;
end endtask
task answer; begin
  wait(response_valid);if(response_bits_error) $fatal(1,"BORROW_BUS_ERROR");
  @(negedge serviceClock);response_ready=1;@(posedge serviceClock);#1;response_ready=0;
end endtask
task advance(input [31:0] target,input [31:0] amount); begin
  @(negedge serviceClock);injectTime=1;injectTarget=target;injectElapsed=amount;injectUpper=amount;
  @(posedge serviceClock);#1;injectTime=0;
end endtask
"""
  private val houseScenario="""
manualTime=1;referenceEnabled=0;wait(idle);#1000;
if(houseRecoveryLoans<1) $fatal(1,"HOUSEKEEPING_RECOVERY_ROLE_NOT_EXERCISED");
@(negedge serviceClock);pauseNative=2;pauseReturn=2;savedHouse=houseLoans;savedCaptures=houseCaptures;
advance(1,17);wait(houseLoans==savedHouse+1);#500;
advance(2,5);#1000;
if(consumed || timeNow || houseSenderIdle || houseCaptures!=savedCaptures || projectedTime!=22)
  $fatal(1,"HOUSEKEEPING_BORROW_STALLED_NATIVE");
start_bus();write_byte(8'h6a);write_byte(7);write_word(20);stop_bus();wait(periodWaiting);#1000;
if(periodEffects || houseNative_elapsed!=17 || houseNative_target!=1)
  $fatal(1,"HOUSEKEEPING_PERIOD_OVERWROTE_BORROW");
stopWorkClock=1;wait(!workRunning);#500;pauseNative=0;wait(houseCaptures>savedCaptures);#1000;
if(consumed || timeNow || periodEffects || houseSenderIdle) $fatal(1,"BORROW_STOPPED_CONSUMER_CAPTURED");
stopWorkClock=0;wait(workRunning);wait(consumed==1);#1000;
if(timeNow!=17 || periodEffects || !periodWaiting || houseSenderIdle)
  $fatal(1,"HOUSEKEEPING_PUBLICATION_REUSED_LIVE_BANK");
pauseReturn=0;wait(periodEffects==1);wait(consumed==3);wait(idle);#1000;
if(timeNow!=22 || projectedTime!=22 || periodEffects!=1 || houseState_nextPeriod!=20)
  $fatal(1,"HOUSEKEEPING_BORROW_FINAL_STATE");
issue(32'h30000038,4);answer;wait(idle);
if(visibleMask!=4) $fatal(1,"HOUSEKEEPING_ORDERED_BORROW");
"""
  private val houseResetScenario="""
manualTime=1;referenceEnabled=0;wait(idle);#1000;
if(houseRecoveryLoans<1) $fatal(1,"HOUSEKEEPING_RECOVERY_ROLE_NOT_EXERCISED");
@(negedge serviceClock);pauseNative=2;pauseReturn=2;savedHouse=houseLoans;savedCaptures=houseCaptures;
advance(1,17);wait(houseLoans==savedHouse+1);#500;
savedRecoveries=houseRecoveryLoans;stopWorkClock=1;wait(!workRunning);#500;applicationReset=1;#17;applicationReset=0;#1000;
if(consumed || timeNow || houseSenderIdle || houseNative_resetApplication)
  $fatal(1,"RESET_DISCARDED_HOUSEKEEPING_BORROW");
pauseNative=0;wait(houseCaptures>savedCaptures);#1000;
if(consumed || timeNow || houseSenderIdle) $fatal(1,"HOUSEKEEPING_RESET_EARLY_PUBLICATION");
stopWorkClock=0;wait(workRunning);wait(consumed==1);#1000;
if(timeNow!=17 || houseSenderIdle || houseNative_resetApplication)
  $fatal(1,"HOUSEKEEPING_RESET_REWROTE_RETAINED_PAYLOAD");
pauseReturn=0;wait(idle);#1000;
if(timeNow!=17 || projectedTime!=17 || consumed!=1 || response_valid || visibleMask!=15 || houseRecoveryLoans<=savedRecoveries)
  $fatal(1,"HOUSEKEEPING_RESET_LOST_PERSISTENT_TIME");
issue(32'h30000038,4);answer;wait(idle);
if(visibleMask!=4) $fatal(1,"HOUSEKEEPING_RESET_BORROW_RECOVERY");
"""
  private val telemetryScenario="""
manualTime=1;referenceEnabled=0;wait(idle);#1000;
if(houseRecoveryLoans<1) $fatal(1,"HOUSEKEEPING_RECOVERY_ROLE_NOT_EXERCISED");
acquire;savedSampleSequence=observedSampleSequence; // ADC owns its publication sequence.
@(negedge serviceClock);pauseNative=1;pauseReturn=1;savedTelemetry=telemetryLoans;savedCaptures=telemetryCaptures;
issue(32'h30000018,1);wait(telemetryLoans==savedTelemetry+1);#1000;
if(telemetryNative_kind!=1 || telemetryNative_data!=1 || telemetrySenderIdle || telemetryCaptures!=savedCaptures)
  $fatal(1,"TELEMETRY_BORROW_STALLED_NATIVE");
acquire;wait(observedSampleSequence==savedSampleSequence+1);
savedRecoveries=houseRecoveryLoans;stopWorkClock=1;wait(!workRunning);#500;applicationReset=1;#17;applicationReset=0;#1000;
if(telemetryNative_data!=1 || telemetrySenderIdle) $fatal(1,"RESET_DISCARDED_TELEMETRY_BORROW");
pauseNative=0;wait(telemetryCaptures>savedCaptures);#1000;
if(response_valid || telemetrySenderIdle) $fatal(1,"TELEMETRY_STOPPED_CONSUMER_CAPTURED");
stopWorkClock=0;wait(workRunning);#3000;
if(gpioOut!=0 || response_valid || telemetrySenderIdle) $fatal(1,"TELEMETRY_RESET_RESTORED_COMMIT");
pauseReturn=0;wait(idle);#1000;
if(gpioOut!=0 || response_valid || observedSampleValue!=13592 || observedSampleSequence!=savedSampleSequence+1)
  $fatal(1,"TELEMETRY_BORROW_LOST_PERSISTENT_OBSERVATION");
issue(32'h30000018,1);answer;wait(idle);
if(gpioOut!=1) $fatal(1,"TELEMETRY_BORROW_RECOVERY_PROGRESS");
"""
  private val indexedCommitScenario="""
manualTime=1;referenceEnabled=0;wait(idle);#1000;
issue(32'h30000030,17);answer;wait(idle);
@(negedge serviceClock);pauseNative=1;pauseReturn=1;savedTelemetry=telemetryLoans;savedCaptures=telemetryCaptures;
issue(32'h30000034,32'h12345678);wait(telemetryLoans==savedTelemetry+1);#1000;
if(telemetryNative_appIndex!=17 || telemetryNative_data!=32'h12345678) $fatal(1,"BORROW_APP_INDEX");

// Host traffic may run while the CPU's architectural update is held.
start_bus();write_byte(8'h6a);write_byte(7);write_word(20);stop_bus();#1000;
applicationReset=1;#17;applicationReset=0;#1000;
if(telemetryNative_appIndex!=17 || telemetryNative_data!=32'h12345678) $fatal(1,"RESET_CHANGED_BORROWED_APP_INDEX");
pauseNative=0;wait(telemetryCaptures>savedCaptures);#1000;pauseReturn=0;wait(idle);
if(response_valid) $fatal(1,"INDEXED_COMMIT_STALE_REPLY");
read_words(128,0,17);if(snapshot[0+:32]!==0) $fatal(1,"INDEXED_RESET_REVOCATION");
issue(32'h30000030,17);answer;issue(32'h30000034,32'h89abcdef);answer;wait(idle);
@(negedge serviceClock);request_bits_operation=1;request_bits_address=32'h30000034;request_bits_mask=15;request_valid=1;
@(posedge serviceClock);while(!request_ready) @(posedge serviceClock);#1;request_valid=0;
wait(response_valid);if(response_bits_data!==32'h89abcdef) $fatal(1,"INDEXED_COMMIT_RECOVERY");answer;
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(fault: String=""): SocTop=if(click) new ClickCommandBorrowFixture(parameters,fault) else new BdCommandBorrowFixture(parameters,fault)
    test(s"$name housekeeping borrowed bank retains queued observations, publication and full-return ordering") {
      ClockedSimulation.run(fixture(),name+"-housekeeping-borrow",houseScenario,monitor,
        referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
    test(s"$name housekeeping borrowed command survives reset without publishing or overwriting early") {
      ClockedSimulation.run(fixture(),name+"-housekeeping-borrow-reset",houseResetScenario,monitor,
        referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
    test(s"$name telemetry borrowed commit survives a stopped work clock and application reset") {
      ClockedSimulation.run(fixture(),name+"-telemetry-borrow",telemetryScenario,monitor,
        referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
    test(s"$name borrowed sparse application index survives host traffic and application cancellation") {
      ClockedSimulation.run(fixture(),name+"-indexed-telemetry-borrow",indexedCommitScenario,monitor,
        referenceHalfPeriodNs=10000000,deadlineNs=2000000)
    }
    for((fault,scenario,diagnostic) <- Seq(
      ("house-live",houseScenario,"HOUSEKEEPING_BORROW_CHANGED"),
      ("telemetry-live",telemetryScenario,"TELEMETRY_BORROW_CHANGED"))) {
      test(s"$name borrowed command rejects live-source substitution: $fault") {
        val failure=intercept[IllegalArgumentException] {
          ClockedSimulation.run(fixture(fault),name+"-borrow-fault-"+fault,scenario,monitor,
            referenceHalfPeriodNs=10000000,deadlineNs=2000000)
        }
        val fatals="(?m)^FATAL: testbench\\.sv:[0-9]+: ([A-Z_]+)".r.findAllMatchIn(failure.getMessage).map(_.group(1)).toSeq
        assert(fatals==Seq(diagnostic),failure.getMessage)
        assert(!failure.getMessage.contains("ERROR:"),failure.getMessage)
        assert(!failure.getMessage.contains("SOC_DEADLINE"),failure.getMessage)
      }
    }
  }
}
