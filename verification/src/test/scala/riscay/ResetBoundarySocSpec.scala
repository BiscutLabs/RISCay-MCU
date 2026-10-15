// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import java.util.zip.CRC32

class BdResetBoundarySocFixture(p: SocParameters, rawCoreFault: Boolean=false, stallWork: Boolean=false) extends riscay.bd.FourPhaseSoc(p) {
  val applicationReset=IO(Input(Bool()))
  applicationResetRequest:=reset.asBool || watchdog.io.expired || applicationReset
  if(rawCoreFault) { core.reset:=systemReset.asAsyncReset }
  val stopWorkClock=IO(Input(Bool()))
  if(stallWork) {
    require(p.lowPower.isEmpty)
    // Test stimulus changes stopWorkClock only while serviceClock is low.
    workClock:=(serviceClock.asBool && !stopWorkClock).asClock
  }
  val receivingClock=IO(Output(Bool())); receivingClock:=workClock.asBool
  val boundaryClosed=IO(Output(Bool())); boundaryClosed:=resetBoundary.io.closed
  val boundaryRebased=IO(Output(Bool())); boundaryRebased:=resetBoundary.io.rebased
  val boundaryRebaseIdle=IO(Output(Bool())); boundaryRebaseIdle:=resetBoundary.io.rebaseIdle
  private val workBoundaryBridges=applicationBridges.filterNot(_ eq requestBridge).toSeq
  require(workBoundaryBridges.nonEmpty)
  val workClosedAcks=IO(Output(UInt(workBoundaryBridges.size.W)))
  workClosedAcks:=Cat(workBoundaryBridges.map(_.closed))
  val workRebaseAcks=IO(Output(UInt(workBoundaryBridges.size.W)))
  workRebaseAcks:=Cat(workBoundaryBridges.map(_.rebased))
  val ingressRebased=IO(Output(Bool())); ingressRebased:=requestBridge.rebased
  val rebasing=IO(Output(Bool())); rebasing:=resetBoundary.io.rebase
  val coreResetHeld=IO(Output(Bool())); coreResetHeld:=nativeCoreReset
  val wakeDemand=IO(Output(Bool())); wakeDemand:=resetBoundary.io.forceRun
  val cutoff=IO(Output(Bool())); cutoff:=applicationCancel
  val islandReset=IO(Output(Bool())); islandReset:=nativeApplicationReset
  val ingressClosed=IO(Output(Bool())); ingressClosed:=requestBridge.closed
  val serviceClosed=IO(Output(Bool())); serviceClosed:=fabric.io.presentationClosed
  val rawRequest=IO(Output(Bool())); rawRequest:=transactions.serviceRequest.req
  val rawAck=IO(Output(Bool())); rawAck:=transactions.serviceRequest.ack
  val rawPayload=IO(Output(new MemoryRequest)); rawPayload:=transactions.serviceRequest.bits
  val captured=IO(Output(new MemoryRequest)); captured:=requestBridge.out.bits
  val offered=IO(Output(Bool())); offered:=requestBridge.out.valid
  val accepted=IO(Output(Bool())); accepted:=fabric.io.request.fire
  val wordAccepted=IO(Output(Bool())); wordAccepted:=fabric.io.ram.request.fire
  val ramBusy=IO(Output(Bool())); ramBusy:=ramAccess.io.busy
  val holdRamDecision=IO(Input(Bool()))
  ramDecision.in.valid:=fabric.io.ramSource.decision.valid && !holdRamDecision
  fabric.io.ramSource.decision.ready:=ramDecision.in.ready && !holdRamDecision
  val ramGrantWaiting=IO(Output(Bool())); ramGrantWaiting:=ramGrant.out.valid
  val nativeTraceEvent=IO(Output(Bool())); nativeTraceEvent:=core.traceEvent
  val nativeTrace=IO(Output(new Retirement)); nativeTrace:=core.trace
}
class ClickResetBoundarySocFixture(p: SocParameters, rawCoreFault: Boolean=false, stallWork: Boolean=false) extends riscay.click.ClickSoc(p) {
  val applicationReset=IO(Input(Bool()))
  applicationResetRequest:=reset.asBool || watchdog.io.expired || applicationReset
  if(rawCoreFault) { core.reset:=systemReset.asAsyncReset }
  val stopWorkClock=IO(Input(Bool()))
  if(stallWork) {
    require(p.lowPower.isEmpty)
    // Test stimulus changes stopWorkClock only while serviceClock is low.
    workClock:=(serviceClock.asBool && !stopWorkClock).asClock
  }
  val receivingClock=IO(Output(Bool())); receivingClock:=workClock.asBool
  val boundaryClosed=IO(Output(Bool())); boundaryClosed:=resetBoundary.io.closed
  val boundaryRebased=IO(Output(Bool())); boundaryRebased:=resetBoundary.io.rebased
  val boundaryRebaseIdle=IO(Output(Bool())); boundaryRebaseIdle:=resetBoundary.io.rebaseIdle
  private val workBoundaryBridges=applicationBridges.filterNot(_ eq requestBridge).toSeq
  require(workBoundaryBridges.nonEmpty)
  val workClosedAcks=IO(Output(UInt(workBoundaryBridges.size.W)))
  workClosedAcks:=Cat(workBoundaryBridges.map(_.closed))
  val workRebaseAcks=IO(Output(UInt(workBoundaryBridges.size.W)))
  workRebaseAcks:=Cat(workBoundaryBridges.map(_.rebased))
  val ingressRebased=IO(Output(Bool())); ingressRebased:=requestBridge.rebased
  val rebasing=IO(Output(Bool())); rebasing:=resetBoundary.io.rebase
  val coreResetHeld=IO(Output(Bool())); coreResetHeld:=nativeCoreReset
  val wakeDemand=IO(Output(Bool())); wakeDemand:=resetBoundary.io.forceRun
  val cutoff=IO(Output(Bool())); cutoff:=applicationCancel
  val islandReset=IO(Output(Bool())); islandReset:=nativeApplicationReset
  val ingressClosed=IO(Output(Bool())); ingressClosed:=requestBridge.closed
  val serviceClosed=IO(Output(Bool())); serviceClosed:=fabric.io.presentationClosed
  val rawRequest=IO(Output(Bool())); rawRequest:=transactions.serviceRequest.req
  val rawAck=IO(Output(Bool())); rawAck:=transactions.serviceRequest.ack
  val rawPayload=IO(Output(new MemoryRequest)); rawPayload:=transactions.serviceRequest.bits
  val captured=IO(Output(new MemoryRequest)); captured:=requestBridge.out.bits
  val offered=IO(Output(Bool())); offered:=requestBridge.out.valid
  val accepted=IO(Output(Bool())); accepted:=fabric.io.request.fire
  val wordAccepted=IO(Output(Bool())); wordAccepted:=fabric.io.ram.request.fire
  val ramBusy=IO(Output(Bool())); ramBusy:=ramAccess.io.busy
  val holdRamDecision=IO(Input(Bool()))
  ramDecision.in.valid:=fabric.io.ramSource.decision.valid && !holdRamDecision
  fabric.io.ramSource.decision.ready:=ramDecision.in.ready && !holdRamDecision
  val ramGrantWaiting=IO(Output(Bool())); ramGrantWaiting:=ramGrant.out.valid
  val nativeTraceEvent=IO(Output(Bool())); nativeTraceEvent:=core.traceEvent
  val nativeTrace=IO(Output(new Retirement)); nativeTrace:=core.trace
}

/** Actual Core/Fabric/Services path. Acceptance and SRAM effects are independent
  * observations; no offered packet or reset request is counted as acceptance.
  */
class ResetBoundarySocSpec extends AnyFunSuite {
  // The shared wire loader declares 32 bytes of required working RAM.
  private val p=SocParameters(McuConfiguration(64,32,1,Vector.empty,
    ApplicationProfile(1,1,"reset-boundary",Vector.empty,Vector.empty)),watchdogCycles=10000000)
  private def upload(prefix: Int): String = {
    val program=Seq.fill(prefix)(Assembly.i(0x13,0,0,0,0)) ++
      Seq(0x200000b7L,Assembly.i(0x13,2,0,0,0x5a3),Assembly.store(1,2,0,2),Assembly.breakpoint)
    val crc=new CRC32
    program.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b)) & 255).toInt)))
    s"""
    begin_image(${program.size*4},0,32'h${crc.getValue.toHexString},32'h00010000);
    ${program.zipWithIndex.map { case(w,i) => s"put_word(${i*4},32'h${w.toHexString});" }.mkString("\n")}
    command(3); await_ready(); command(6);
  """
  }
  private val monitors="""
integer stores=0,writes=0,totalAccepted=0,acceptedStores=0;
reg checkClose=0;
always @(posedge serviceClock) if(!reset) begin
  if(accepted) totalAccepted=totalAccepted+1;
  if(accepted && captured_operation == 2 && captured_address == 32'h20000000) begin
    acceptedStores=acceptedStores+1;
    if(!wordAccepted) $fatal(1,"SOC_BOUNDARY_DROPPED_ACCEPTED_STORE");
  end
  if(cutoff && accepted) $fatal(1,"SOC_BOUNDARY_ACCEPTED_AFTER_CUTOFF");
  if(wordAccepted) begin
    stores=stores+1;
    if(!accepted || captured_operation !== 2 || captured_address !== 32'h20000000 ||
        captured_data !== 32'h5a3 || captured_mask !== 15)
      $fatal(1,"SOC_BOUNDARY_CORRUPT_ACCEPTED_PACKET");
  end
  if(!dut.fabric_ram_macros_0.CEN && !dut.fabric_ram_macros_0.GWEN) writes=writes+1;
end
always @(posedge islandReset) if(checkClose && !reset && (!cutoff || !ingressClosed || !serviceClosed))
  $fatal(1,"SOC_BOUNDARY_DESTROYED_BEFORE_RECEIVERS_CLOSED");
task pulse_reset; begin
  #1; applicationReset=1; #7; applicationReset=0;
end endtask
task settled; begin
  #100000;
  if(systemReset || cutoff || islandReset || ramBusy || !programmed || !locked || mode !== 2)
    $fatal(1,"SOC_BOUNDARY_DID_NOT_RECOVER");
  if(acceptedStores !== stores || writes !== 4*acceptedStores || acceptedStores > 1)
    $fatal(1,"SOC_BOUNDARY_ACCEPTED_EFFECT_COUNT accepted=%0d stores=%0d writes=%0d",acceptedStores,stores,writes);
  if(stores && {dut.fabric_ram_macros_0.mem[3],dut.fabric_ram_macros_0.mem[2],
      dut.fabric_ram_macros_0.mem[1],dut.fabric_ram_macros_0.mem[0]} !== 32'h5a3)
    $fatal(1,"SOC_BOUNDARY_ACCEPTED_EFFECT_DATA");
end endtask
"""
  // These composed cases count acceptance and effects on the actual receiving
  // clock. Sampling fire on the still-running service clock would manufacture
  // transactions while the work clock is stopped.
  private def workClockMonitors(click: Boolean): String = s"""
integer serviceEdges=0,workEdges=0,acceptedWork=0,wordIssues=0,byteWrites=0,visibleBoot=0;
integer savedServiceEdges=0,savedWorkEdges=0;
reg checkBoundary=0;
reg savedRequest,savedAck;
reg [31:0] savedAddress,savedData,savedOperation,savedMask;
reg [31:0] savedCapturedAddress,savedCapturedData,savedCapturedOperation,savedCapturedMask;
always @(posedge serviceClock) if(!reset) serviceEdges=serviceEdges+1;
always @(posedge receivingClock) if(!reset) begin
  workEdges=workEdges+1;
  if(accepted) acceptedWork=acceptedWork+1;
  if(wordAccepted) wordIssues=wordIssues+1;
  if(!dut.fabric_ram_macros_0.CEN && !dut.fabric_ram_macros_0.GWEN) byteWrites=byteWrites+1;
  if(cutoff && accepted) $$fatal(1,"SOC_BOUNDARY_WORK_ACCEPTED_AFTER_CUTOFF");
end
always @(posedge islandReset) if(checkBoundary && !reset) begin
  #0.001;
  if(!cutoff || !boundaryClosed || !ingressClosed || !serviceClosed)
    $$fatal(1,"SOC_BOUNDARY_WORK_DESTROYED_BEFORE_CLOSURE");
end
always @(traceEvent) begin
  // Resolve the public event/valid isolation assignments before classifying a
  // Click phase change; forcing the event low during reset is not a retirement.
  #0.001;
  if(checkBoundary && !reset && trace_valid && ${if(click) "1" else "traceEvent"}) begin
    if(cutoff || coreResetHeld || trace_pc !== 0 || trace_instruction !== 32'h300000b7)
      $$fatal(1,"SOC_BOUNDARY_WORK_BAD_VISIBLE_BOOT");
    visibleBoot=visibleBoot+1;
  end
end
task pause_receivers; begin
  @(negedge serviceClock); #1; stopWorkClock=1;
end endtask
task one_receiving_edge; begin
  @(negedge serviceClock); #1; stopWorkClock=0;
  @(posedge receivingClock);
  @(negedge serviceClock); #1; stopWorkClock=1;
end endtask
task no_work_effects; begin
  if(acceptedWork || wordIssues || byteWrites)
    $$fatal(1,"SOC_BOUNDARY_WORK_UNEXPECTED_EFFECT accepted=%0d words=%0d bytes=%0d",acceptedWork,wordIssues,byteWrites);
end endtask
"""
  // Inject a stall only into the first input synchronizers. The production
  // drain guard, falling-edge gate register, clock and ready logic still run.
  // The companion graph control binds every observed predicate below to the
  // complete RAM-store ready cone; matching this mirror alone is insufficient.
  private def receiptGateMonitors(click: Boolean): String = s"""
wire [16:0] gatePredicates = {
  dut.fabric_completionAvailable, ~dut.applicationCancel, ~dut.fabric_resetRecovery,
  dut._ca_child_admission_grant_bridge_out_valid, ~dut.fabric_bootWait, ~dut.fabric_eventWait,
  ~dut.fabric_memoryBusy, ~dut.fabric_loaderWrite, ~dut.fabric_telemetryBarrier,
  ~dut.fabric_housekeepingBarrierBusy, ~dut.telemetryBoundary_io_debt,
  ~dut.housekeepingBoundary_io_debt, ~dut.fabric_controlBusy,
  dut._ca_child_ram_grant_bridge_out_valid, dut.fabric_io_ramSource_decision_ready,
  ~dut.ramServiceDebt, dut._ca_child_ram_access_io_request_ready};
wire gateOtherReady = &gatePredicates;
wire gateWithoutDecision = &{gatePredicates[16:3],gatePredicates[1:0]};
wire gateStoreBranch = dut.fabric_ramOperation && !dut.fabric_nativeMmio && !dut.fabric_programCpuOperation;
wire gateEligibleWrite = dut.ca_child_ram_source.eligible && dut.ca_child_ram_grant_bridge.out_bits;
wire [69:0] gateSource = {rawPayload_operation,rawPayload_address,rawPayload_data,rawPayload_mask};
wire [69:0] gateCapture = {captured_operation,captured_address,captured_data,captured_mask};
localparam [69:0] gateExpected = {2'd2,32'h20000000,32'h000005a3,4'hf};
reg gateArmed=0,gateAwaitAck=0,gateClosedWindow=0,gateRestartWindow=0;
reg gateSavedRequest,gateSavedAck,gateReturnSeen=0;
reg [69:0] gateSavedPayload;
reg [3:0] gateWrittenBytes=0;
integer gateWorkEdges=0,gateSavedWorkEdges=0,gateServiceEdges=0,gateSavedServiceEdges=0;
integer gateCaptures=0,gateWords=0,gateWrites=0,gateAcks=0,gateRestartEdges=0,gateFalls=0,gateWait=0;
time gateLastWorkEdge=0;
always @(negedge dut.gate_enabled) if(gateArmed) begin
  if(serviceClock !== 0) $$fatal(1,"SOC_GATE_NONFALLING_CLOSURE");
  gateFalls=gateFalls+1;
end
always @(posedge serviceClock) if(!reset) begin
  gateServiceEdges=gateServiceEdges+1;
  // ACK's exact-fatal oracle runs first after the receipt's NBA update.
  #0.002;
  if(gateClosedWindow && (gateOtherReady !== 1 || gateStoreBranch !== 1 || gateEligibleWrite !== 1 ||
      offered !== 1 || gateSource !== gateSavedPayload || rawRequest !== gateSavedRequest ||
      cutoff || coreResetHeld || islandReset || rebasing || applicationReset))
    $$fatal(1,"SOC_GATE_CLOSED_COFACTOR_OR_RETENTION");
end
always @(gateSource or rawRequest) if(gateArmed && gateAwaitAck && rawAck === gateSavedAck &&
    (gateSource !== gateSavedPayload || rawRequest !== gateSavedRequest))
  $$fatal(1,"SOC_GATE_SOURCE_CHANGED_BEFORE_ACK");
always @(posedge receivingClock) if(!reset && gateArmed) begin
  gateWorkEdges=gateWorkEdges+1; gateLastWorkEdge=$$time;
  if(gateRestartWindow) gateRestartEdges=gateRestartEdges+1;
  if(accepted && captured_operation == 2 && captured_address == 32'h20000000) begin
    if(!gateRestartWindow || gateRestartEdges !== 1 || gateCaptures || gateCapture !== gateSavedPayload ||
        gateCapture !== gateExpected || gateOtherReady !== 1 || !wordAccepted || !gateEligibleWrite ||
        !dut.fabric_io_ramSource_grant_ready || !dut.ca_child_ram_decision_bridge.in_valid ||
        !dut.fabric_io_ramSource_decision_ready || !dut.ca_child_ram_decision_bridge.in_bits)
      $$fatal(1,"SOC_GATE_NONATOMIC_REAL_CAPTURE");
    gateCaptures=gateCaptures+1;
  end
  if(wordAccepted) begin
    if(!accepted || gateCapture !== gateExpected) $$fatal(1,"SOC_GATE_WORD_WITHOUT_MATCHING_CAPTURE");
    gateWords=gateWords+1;
  end
end
always @(rawAck) if(gateArmed && gateAwaitAck && rawAck !== gateSavedAck) begin
  #0.001;
  if(gateCaptures !== 1 || gateLastWorkEdge !== $$time || gateWords !== 1)
    $$fatal(1,"SOC_GATE_ACK_WITHOUT_REAL_CAPTURE");
  gateAcks=gateAcks+1; gateAwaitAck=0;
  // Payload may legally change after this ACK. Retention assertions end here.
end
always @(rawRequest or rawAck) if(gateArmed && gateAcks == 1 && !rawRequest && !rawAck)
  gateReturnSeen=1;
always @(posedge dut.fabric_ram_macros_0.CLK) if(!reset && gateArmed &&
    !dut.fabric_ram_macros_0.CEN && !dut.fabric_ram_macros_0.GWEN) begin
  if(gateCaptures !== 1 || gateWords !== 1 || dut.fabric_ram_macros_0.WEN !== 0 ||
      dut.fabric_ram_macros_0.A > 3 || gateWrittenBytes[dut.fabric_ram_macros_0.A] ||
      dut.fabric_ram_macros_0.D !== ((32'h000005a3 >> (8*dut.fabric_ram_macros_0.A)) & 255))
    $$fatal(1,"SOC_GATE_MACRO_EFFECT_IDENTITY");
  gateWrittenBytes[dut.fabric_ram_macros_0.A]=1; gateWrites=gateWrites+1;
end
"""

  private val receiptGateBody="""
    // Hold only the existing reservation decision input while the real source
    // and grant settle. No phase, payload, ready or clock override is used.
    for(gateWait=0; gateWait<400 && !(offered === 1 && gateSource === gateExpected &&
        ramGrantWaiting === 1 && gateWithoutDecision === 1 && gateEligibleWrite === 1 &&
        gateStoreBranch === 1); gateWait=gateWait+1) begin @(negedge serviceClock); #1; end
    if(gateWait == 400 || rawRequest === rawAck || !dut.gate_enabled ||
        cutoff || coreResetHeld || islandReset || rebasing || applicationReset ||
        !serviceClockEnable || stopWorkClock || dut.fabric_io_ramSource_decision_ready)
      $fatal(1,"SOC_GATE_NO_HELD_ELIGIBLE_STORE");
    @(negedge serviceClock); #1;
    gateSavedPayload=gateSource; gateSavedRequest=rawRequest; gateSavedAck=rawAck;
    gateArmed=1; gateAwaitAck=1;
    $display("SOC_GATE_REQUEST_PHASE:%0d",rawRequest);
    force dut.gate_demandFirst=1'b0;
    force dut.gate_drainFirst=1'b0;
    repeat(12) @(negedge serviceClock); #1;
    if(dut.gate_enabled !== 0 || dut.gate_needClock !== 0 || dut.gate_drain !== 0 ||
        dut.gate_grace !== 0 || receivingClock !== 0 || !sleeping || gateFalls !== 1 ||
        gateCaptures || gateWords || gateWrites || gateAcks ||
        gateSource !== gateSavedPayload || rawRequest !== gateSavedRequest || rawAck !== gateSavedAck)
      $fatal(1,"SOC_GATE_DID_NOT_CLOSE_WITH_HELD_STORE");
    gateSavedWorkEdges=gateWorkEdges; gateSavedServiceEdges=gateServiceEdges;
    // Release the decision at a low service phase. Every other real admission
    // predicate must now be true, while the actual consumer remains stopped.
    holdRamDecision=0; #1;
    if(gateOtherReady !== 1 || gateStoreBranch !== 1 || gateEligibleWrite !== 1 || offered !== 1)
      $fatal(1,"SOC_GATE_NOT_OTHERWISE_READY");
    gateClosedWindow=1;
    repeat(4) @(negedge serviceClock); #1;
    if(gateServiceEdges < gateSavedServiceEdges+4 || gateWorkEdges !== gateSavedWorkEdges ||
        gateCaptures || gateWords || gateWrites || gateAcks || rawAck !== gateSavedAck ||
        dut.fabric_io_request_ready !== 0 || receivingClock !== 0 || dut.gate_enabled !== 0)
      $fatal(1,"SOC_GATE_CLOSED_EFFECT");
    gateClosedWindow=0; gateRestartWindow=1;
    release dut.gate_demandFirst;
    release dut.gate_drainFirst;
    repeat(8) @(negedge serviceClock); #1;
    if(gateCaptures !== 1 || gateWords !== 1 || gateAcks !== 1 || gateAwaitAck ||
        gateWorkEdges <= gateSavedWorkEdges || !dut.gate_enabled)
      $fatal(1,"SOC_GATE_RESTART_DID_NOT_CAPTURE");
    gateRestartWindow=0;
    #100000;
    if(gateCaptures !== 1 || gateWords !== 1 || gateAcks !== 1 || gateWrites !== 4 ||
        gateWrittenBytes !== 4'hf || ramBusy || !programmed || !locked || mode !== 4 ||
        {dut.fabric_ram_macros_0.mem[3],dut.fabric_ram_macros_0.mem[2],
         dut.fabric_ram_macros_0.mem[1],dut.fabric_ram_macros_0.mem[0]} !== 32'h000005a3)
      $fatal(1,"SOC_GATE_FINAL_STORE_EFFECT");
    $display("SOC_GATE_CAPTURE_COUNTS:%0d:%0d:%0d:%0d",gateCaptures,gateWords,gateAcks,gateWrites);
  """

  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    def fixture(fault: Boolean=false): SocTop=if(click) new ClickResetBoundarySocFixture(p,fault) else new BdResetBoundarySocFixture(p,fault)
    for(halfPeriod <- Seq(25,50,500)) {
      test(s"$name production restart publishes the first clockless boot retirement at half-period $halfPeriod") {
        ClockedSimulation.run(fixture(),name+s"-soc-reset-boot-$halfPeriod","""
          // Bounded by receiving edges at every tested service frequency.
          // The reset pulse itself and all retirement/effect oracles are unchanged.
          repeat(180) @(negedge serviceClock);
          if(cutoff || coreResetHeld || nativeRetirements !== 1 || publicRetirements !== 1)
            $fatal(1,"SOC_BOUNDARY_LOST_BOOT_RETIREMENT native=%0d public=%0d",nativeRetirements,publicRetirements);
        """,s"""
          integer nativeRetirements=0,publicRetirements=0;
          always @(nativeTraceEvent) if(!reset && nativeTrace_valid && ${if(click) "1" else "nativeTraceEvent"}) begin
            if(cutoff || nativeTrace_pc !== 0 || nativeTrace_instruction !== 32'h300000b7)
              $$fatal(1,"SOC_BOUNDARY_BOOT_BEFORE_REOPEN");
            nativeRetirements=nativeRetirements+1;
          end
          always @(traceEvent) if(!reset && trace_valid && ${if(click) "1" else "traceEvent"}) begin
            if(trace_pc !== 0 || trace_instruction !== 32'h300000b7) $$fatal(1,"SOC_BOUNDARY_BAD_PUBLIC_BOOT");
            publicRetirements=publicRetirements+1;
          end
        """,serviceHalfPeriodNs=halfPeriod)
      }
    }
    for(stage <- 0 until 7) {
      test(s"$name production reset retains request payload at capture stage $stage in both request parities") {
        val phases=(0 to (if(click) 1 else 0)).map { prefix =>
        val output=ClockedSimulation.run(fixture(),name+s"-soc-reset-capture-$stage-$prefix",upload(prefix)+s"""
          checkClose=1;
          wait(rawRequest != rawAck && rawPayload_address == 32'h20000000 && rawPayload_operation == 2);
          $$display("SOC_BOUNDARY_REQUEST_PHASE:%0d",rawRequest);
          repeat($stage) @(negedge serviceClock);
          pulse_reset; settled;
          // Restart the preserved locked image; its first store is fresh work.
          command(5); wait(mode == 4); #100000;
          if(acceptedStores !== stores || stores < 1 || stores > 2 || writes != 4*acceptedStores)
            $$fatal(1,"SOC_BOUNDARY_FRESH_RESTART_EFFECTS");
        """,monitors,serviceHalfPeriodNs=25)
        val log=java.nio.file.Files.readString(output.resolve("simulation.log"))
        "SOC_BOUNDARY_REQUEST_PHASE:([01])".r.findAllMatchIn(log).map(_.group(1)).toSeq
        }.flatten.toSet
        assert(phases == (if(click) Set("0","1") else Set("1")),"MISSING_PRODUCTION_REQUEST_PHASE")
      }
    }
    for(halfPeriod <- Seq(25,500)) {
      test(s"$name production reset retrigger on reopening cancels only the isolated generation at half-period $halfPeriod") {
        ClockedSimulation.run(fixture(),name+s"-soc-reset-reopening-$halfPeriod",s"""
          checkClose=1;
          applicationReset=1; visibleBoot=0; #7; applicationReset=0;
          wait(islandReset);
          @(negedge islandReset); #${halfPeriod/5}; applicationReset=1;
          #7; applicationReset=0;
          repeat(180) @(negedge serviceClock);
          if(systemReset || cutoff || islandReset || mode !== 0 || stores || writes || visibleBoot !== 1)
            $$fatal(1,"SOC_BOUNDARY_RETRIGGER_RECOVERY");
        """,monitors+s"""
          integer visibleBoot=0;
          always @(traceEvent) if(!reset && trace_valid && ${if(click) "1" else "traceEvent"}) begin
            if(cutoff || trace_pc !== 0 || trace_instruction !== 32'h300000b7)
              $$fatal(1,"SOC_BOUNDARY_RETRIGGER_VISIBLE_CANCELLED_GENERATION");
            visibleBoot=visibleBoot+1;
          end
        """,serviceHalfPeriodNs=halfPeriod)
      }
    }
    for(offset <- Seq(1,24,26,49)) {
      test(s"$name production reset counts a held grant at offset $offset solely by actual fire") {
        ClockedSimulation.run(fixture(),name+s"-soc-reset-held-$offset","holdRamDecision=1;"+upload(0)+s"""
          checkClose=1; wait(ramGrantWaiting);
          @(negedge serviceClock); #$offset; applicationReset=1; holdRamDecision=0;
          #7; applicationReset=0; settled;
        """,monitors,serviceHalfPeriodNs=25)
      }
    }
    test(s"$name production reset waits for real receiving edges with the work clock stopped") {
      def stalled: SocTop=if(click) new ClickResetBoundarySocFixture(p,stallWork=true)
        else new BdResetBoundarySocFixture(p,stallWork=true)
      ClockedSimulation.run(stalled,name+"-soc-reset-work-stopped","""
        wait(offered && rawPayload_address == 32'h30000000);
        pause_receivers;
        savedRequest=rawRequest; savedAck=rawAck;
        savedAddress=rawPayload_address; savedData=rawPayload_data;
        savedOperation=rawPayload_operation; savedMask=rawPayload_mask;
        savedCapturedAddress=captured_address; savedCapturedData=captured_data;
        savedCapturedOperation=captured_operation; savedCapturedMask=captured_mask;
        savedServiceEdges=serviceEdges; savedWorkEdges=workEdges; checkBoundary=1;
        #1; applicationReset=1; #7; applicationReset=0;
        repeat(20) @(posedge serviceClock); #1;
        if(serviceEdges < savedServiceEdges+20 || workEdges !== savedWorkEdges || !cutoff || !wakeDemand ||
            boundaryClosed || !ingressClosed || serviceClosed || (|workClosedAcks) ||
            islandReset || coreResetHeld || rebasing)
          $fatal(1,"SOC_BOUNDARY_WORK_CLOSE_ADVANCED_WITHOUT_EDGE");
        if(rawRequest !== savedRequest || rawAck !== savedAck || rawRequest === rawAck ||
            rawPayload_address !== savedAddress || rawPayload_data !== savedData ||
            rawPayload_operation !== savedOperation || rawPayload_mask !== savedMask)
          $fatal(1,"SOC_BOUNDARY_WORK_SOURCE_CHANGED_BEFORE_CLOSURE");
        // The native source remains retained above. The closed ingress has no
        // valid payload: its direct-bus receipt must mask unrelated consumers.
        if(offered || captured_address !== 0 || captured_data !== 0 ||
            captured_operation !== 0 || captured_mask !== 0)
          $fatal(1,"SOC_BOUNDARY_CLOSED_INGRESS_OUTPUT_NOT_MASKED");
        no_work_effects;
        // The service-clock ingress has closed, but the work-clock receivers
        // need a genuine edge. That edge cannot also receive rebase, which is
        // issued later by the live service coordinator.
        one_receiving_edge;
        wait(islandReset); #1; savedWorkEdges=workEdges;
        repeat(20) @(posedge serviceClock); #1;
        if(workEdges !== savedWorkEdges || !boundaryClosed || !cutoff || !islandReset ||
            !(&workClosedAcks) || !coreResetHeld || !rebasing || !ingressRebased ||
            (|workRebaseAcks) || boundaryRebased || boundaryRebaseIdle || visibleBoot)
          $fatal(1,"SOC_BOUNDARY_WORK_REBASE_ADVANCED_WITHOUT_EDGE");
        no_work_effects;
        // A second work edge accepts rebase. Holding time can now elapse on
        // the service clock, but reopening still needs a real rebase-idle edge.
        one_receiving_edge; savedWorkEdges=workEdges;
        repeat(80) @(posedge serviceClock); #1;
        // The live ingress has already cleared its rebase acknowledgment; the
        // stopped work receivers retain theirs. Neither aggregate can be true.
        if(workEdges !== savedWorkEdges || ingressRebased || !(&workRebaseAcks) ||
            boundaryRebased || boundaryRebaseIdle ||
            !cutoff || islandReset || !coreResetHeld || rebasing || visibleBoot)
          $fatal(1,"SOC_BOUNDARY_WORK_REOPENED_WITHOUT_IDLE_EDGE");
        no_work_effects;
        @(negedge serviceClock); #1; stopWorkClock=0;
        #100000;
        if(systemReset || cutoff || islandReset || coreResetHeld || rebasing || boundaryRebased ||
            ingressRebased || (|workRebaseAcks) || !boundaryRebaseIdle ||
            mode !== 0 || programmed || locked || visibleBoot !== 1)
          $fatal(1,"SOC_BOUNDARY_WORK_RESUME_RECOVERY");
        no_work_effects;
      """,workClockMonitors(click),serviceHalfPeriodNs=25)
    }
    test(s"$name production reset wakes the retained work gate and service wake frontier") {
      val sleepingParameters=p.copy(lowPower=Some(LowPowerParameters(stopServiceClock=true)))
      def gated: SocTop=if(click) new ClickResetBoundarySocFixture(sleepingParameters)
        else new BdResetBoundarySocFixture(sleepingParameters)
      ClockedSimulation.run(gated,name+"-soc-reset-work-gate","""
        // Keep the external service source live while observing the production
        // request to stop it. No LF tick or host event supplies a competing wake.
        wait(sleeping && !serviceClockEnable);
        @(negedge serviceClock); #1;
        savedServiceEdges=serviceEdges; savedWorkEdges=workEdges;
        repeat(4) @(posedge serviceClock); #1;
        if(serviceEdges < savedServiceEdges+4 || workEdges !== savedWorkEdges ||
            !sleeping || receivingClock || cutoff || wakeDemand || islandReset)
          $fatal(1,"SOC_BOUNDARY_GATE_DID_NOT_STOP_WORK");
        no_work_effects;
        @(negedge serviceClock); #1; checkBoundary=1; applicationReset=1;
        #1;
        if(!serviceClockEnable) $fatal(1,"SOC_BOUNDARY_RESET_DID_NOT_WAKE_SERVICE_SOURCE");
        #6; applicationReset=0;
        wait(cutoff); #0.001;
        if(!wakeDemand) $fatal(1,"SOC_BOUNDARY_RESET_LOST_GATE_DEMAND");
        repeat(8) @(posedge serviceClock); #1;
        if(workEdges <= savedWorkEdges || !boundaryClosed || !islandReset || !coreResetHeld)
          $fatal(1,"SOC_BOUNDARY_RESET_DID_NOT_REOPEN_WORK_GATE");
        #100000;
        if(systemReset || cutoff || islandReset || coreResetHeld || mode !== 0 ||
            programmed || locked || visibleBoot !== 1 || !sleeping || serviceClockEnable)
          $fatal(1,"SOC_BOUNDARY_GATE_RESET_RECOVERY");
        no_work_effects;
        savedWorkEdges=workEdges;
        repeat(4) @(posedge serviceClock); #1;
        if(workEdges !== savedWorkEdges || !sleeping || receivingClock)
          $fatal(1,"SOC_BOUNDARY_GATE_DID_NOT_RESLEEP");
      """,workClockMonitors(click),referenceHalfPeriodNs=1000000,serviceHalfPeriodNs=25)
    }
    test(s"$name production receipt waits for actual retained-gate capture of an otherwise eligible store") {
      val gateParameters=p.copy(lowPower=Some(LowPowerParameters(stopServiceClock=false)))
      val phases=(0 to (if(click) 1 else 0)).map { prefix =>
        def gated: SocTop=if(click) new ClickResetBoundarySocFixture(gateParameters)
          else new BdResetBoundarySocFixture(gateParameters)
        val output=ClockedSimulation.run(gated,name+s"-soc-receipt-real-gate-$prefix",
          "holdRamDecision=1;"+upload(prefix)+receiptGateBody+
          (if(click) "" else "if(!gateReturnSeen) $fatal(1,\"SOC_GATE_MISSING_BD_RETURN\");"),
          receiptGateMonitors(click),referenceHalfPeriodNs=1000000,serviceHalfPeriodNs=25)
        val log=java.nio.file.Files.readString(output.resolve("simulation.log"))
        assert(log.linesIterator.count(_ == "SOC_GATE_CAPTURE_COUNTS:1:1:1:4") == 1,
          "MISSING_REAL_GATE_CAPTURE_ACTIVITY")
        "SOC_GATE_REQUEST_PHASE:([01])".r.findAllMatchIn(log).map(_.group(1)).toSeq
      }.flatten.toSet
      assert(phases == (if(click) Set("0","1") else Set("1")),"MISSING_REAL_GATE_REQUEST_PHASE")
    }
    for(fault <- Seq(false,true)) {
      test(s"$name production stopped-clock reset retains native source until capture closure (raw fault=$fault)") {
        def run()=ClockedSimulation.run(fixture(fault),name+s"-soc-reset-stopped-$fault","""
          wait(offered && rawPayload_address == 32'h30000000);
          @(negedge serviceClock); #1; clockEnabled=0; checkClose=1;
          applicationReset=1;
          #7; applicationReset=0;
          #100;
          if(islandReset || cutoff || rawPayload_address !== 32'h30000000 || rawPayload_operation !== 1 ||
              rawRequest === rawAck || captured_address !== 32'h30000000)
            $fatal(1,"SOC_BOUNDARY_SOURCE_CHANGED_BEFORE_CAPTURE_CLOSE");
          #1000; clockEnabled=1;
          #100000;
          if(systemReset || islandReset || cutoff || mode !== 0 || stores || writes)
            $fatal(1,"SOC_BOUNDARY_STOPPED_CLOCK_RECOVERY");
          wait(offered && rawPayload_address == 32'h30000000);
        """,monitors,serviceHalfPeriodNs=25)
        if(fault) {
          val error=intercept[IllegalArgumentException](run())
          assert(error.getMessage.contains("FATAL: testbench.sv:") &&
            error.getMessage.contains("SOC_BOUNDARY_SOURCE_CHANGED_BEFORE_CAPTURE_CLOSE"))
        } else run()
      }
    }
  }
}
