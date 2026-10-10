// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import riscay.profiles._

class BdSpiAgeFixture(p: SocParameters) extends riscay.bd.FourPhaseSoc(p,x => new GroundlarkBoard(x,PowerPolicy(enabled=true))) {
  val pauseConsumers=IO(Input(Bool()))
  val (boardCommand,boardReply)=supervisorBridges.get
  boardCommand.in.valid:=fabric.boardCommand.valid && !pauseConsumers
  fabric.boardCommand.ready:=boardCommand.in.ready && !pauseConsumers
  telemetryCommandBridge.in.valid:=fabric.telemetryCommand.valid && !pauseConsumers
  fabric.telemetryCommand.ready:=telemetryCommandBridge.in.ready && !pauseConsumers
  val queued=IO(Output(new SupervisorCommand)); queued:=fabric.boardCommand.bits
  val hostCapture=IO(Output(new TelemetryCapture)); hostCapture:=fabric.telemetryCommand.bits.captures.get(0)
  val nativeState=IO(Output(new SupervisorState)); nativeState:=boardReply.out.bits
  val hostSample=IO(Output(new Sample)); hostSample:=BoringUtils.bore(fabric.hostSamples(0))
  val publication=IO(Output(Bool())); publication:=fabric.io.adc.result.valid
  val publicationAge=IO(Output(UInt(32.W))); publicationAge:=fabric.io.adc.age
  val adcBusy=IO(Output(Bool())); adcBusy:=fabric.io.adc.busy
  watchdog.io.heartbeat:=false.B
}
class ClickSpiAgeFixture(p: SocParameters) extends riscay.click.ClickSoc(p,x => new GroundlarkBoard(x,PowerPolicy(enabled=true))) {
  val pauseConsumers=IO(Input(Bool()))
  val (boardCommand,boardReply)=supervisorBridges.get
  boardCommand.in.valid:=fabric.boardCommand.valid && !pauseConsumers
  fabric.boardCommand.ready:=boardCommand.in.ready && !pauseConsumers
  telemetryCommandBridge.in.valid:=fabric.telemetryCommand.valid && !pauseConsumers
  fabric.telemetryCommand.ready:=telemetryCommandBridge.in.ready && !pauseConsumers
  val queued=IO(Output(new SupervisorCommand)); queued:=fabric.boardCommand.bits
  val hostCapture=IO(Output(new TelemetryCapture)); hostCapture:=fabric.telemetryCommand.bits.captures.get(0)
  val nativeState=IO(Output(new SupervisorState)); nativeState:=boardReply.out.bits
  val hostSample=IO(Output(new Sample)); hostSample:=BoringUtils.bore(fabric.hostSamples(0))
  val publication=IO(Output(Bool())); publication:=fabric.io.adc.result.valid
  val publicationAge=IO(Output(UInt(32.W))); publicationAge:=fabric.io.adc.age
  val adcBusy=IO(Output(Bool())); adcBusy:=fabric.io.adc.busy
  watchdog.io.heartbeat:=false.B
}

class SpiAdcFixture(click: Boolean) extends FabricFixture(SocParameters(McuConfiguration(
    8,8,0,Vector.empty,ApplicationProfile(1,1,"spi-wire",Vector.empty,Vector.empty)),
    watchdogCycles=64,watchdogHoldCycles=32)) {
  val conversionStart=IO(Input(Bool())); val ageStep=IO(Input(UInt(32.W)))
  val conversionBusy=IO(Output(Bool())); val conversionDone=IO(Output(Bool()))
  val sampleValid=IO(Output(Bool())); val value=IO(Output(UInt(32.W))); val age=IO(Output(UInt(32.W)))
  val calibrated=IO(Output(Bool()))
  watchdog.io.heartbeat := false.B
  private val pAdc=AdcParameters(2,100,25300,4095,offset = -100,calibrated=true)
  if(click) {
    val adc=asyncChild("tested_spi_adc")(d => new riscay.click.SpiAdc(pAdc,false,d))
    adc.clock:=serviceClock; adc.io.start:=conversionStart; adc.io.ageStep:=ageStep; adc.miso:=adcMiso
    conversionBusy:=adc.io.busy; conversionDone:=adc.io.done; sampleValid:=adc.io.result.valid
    value:=adc.io.result.bits.value; age:=adc.io.age; calibrated:=adc.io.result.bits.calibrated
    adcCsN:=adc.csN; adcSclk:=adc.sclk
  } else {
    val adc=asyncChild("tested_spi_adc")(d => new riscay.bd.SpiAdc(pAdc,false,d))
    adc.clock:=serviceClock; adc.io.start:=conversionStart; adc.io.ageStep:=ageStep; adc.miso:=adcMiso
    conversionBusy:=adc.io.busy; conversionDone:=adc.io.done; sampleValid:=adc.io.result.valid
    value:=adc.io.result.bits.value; age:=adc.io.age; calibrated:=adc.io.result.bits.calibrated
    adcCsN:=adc.csN; adcSclk:=adc.sclk
  }
}
class SpiAdcSpec extends AnyFunSuite {
  private val monitor="""
reg [15:0] wireWord=16'hfabc, shift;
integer edges=0,frames=0,replies=0,resets=0,savedFrames,savedReplies,savedResets,n,campaign;
reg tracking=0,expectBusy=0;
reg [31:0] savedAge,wanted;
real edgeAt,frameAt,admitted,latestIdle=0;
always @(posedge systemReset) if(!reset) resets=resets+1;
always @(posedge serviceClock) if(!reset) begin
  if(expectBusy && !conversionBusy) $fatal(1,"SPI_BUSY_DROPPED");
  if(conversionDone) begin
    if(!conversionBusy) $fatal(1,"SPI_PUBLICATION_IDLE");
    replies=replies+1;
  end
end
always @(negedge conversionBusy) latestIdle=$realtime;
always @(posedge adcSclk) if(!reset && adcCsN) $fatal(1,"SPI_CLOCK_WITH_CS_HIGH");
always @(negedge adcCsN) if(!reset) begin
  if(tracking || adcSclk || !conversionBusy) $fatal(1,"SPI_FRAME_START");
  if($realtime-latestIdle < 50) $fatal(1,"SPI_MISSING_QUIET_PHASE");
  tracking=1; edges=0; frames=frames+1; frameAt=$realtime; edgeAt=$realtime;
  shift=wireWord; adcMiso=shift[15];
  fork begin #3200.01;
    if(!reset && tracking && $realtime-frameAt>3200) $fatal(1,"SPI_FRAME_TOO_LONG");
  end join_none
end
always @(adcSclk) if(!reset && tracking) begin
  if($realtime-edgeAt != 100) $fatal(1,"SPI_HALF_PHASE edges=%d elapsed=%f",edges,$realtime-edgeAt);
  if(adcSclk !== (edges%2 == 0)) $fatal(1,"SPI_EDGE_ORDER");
  edgeAt=$realtime; edges=edges+1;
  if(!adcSclk) begin shift=shift<<1; adcMiso=shift[15]; end
end
always @(posedge adcCsN) if(!reset && tracking) begin
  #0.001;
  if(edges != 32 || adcSclk || $realtime-frameAt < 3200 || $realtime-frameAt > 3200.002)
    $fatal(1,"SPI_FRAME_LENGTH edges=%d duration=%f",edges,$realtime-frameAt);
  tracking=0;
end
always @(posedge reset) begin tracking=0; expectBusy=0; end
task launch(input [15:0] word); begin
  wait(!conversionBusy); @(negedge serviceClock); wireWord=word; conversionStart=1;
  admitted=$realtime+25;
  @(negedge serviceClock); conversionStart=0; expectBusy=1;
end endtask
task retire(input bit valid); begin
  wait(conversionDone); #1;
  wanted=(wireWord & 4095)*25300/4095-100;
  if(sampleValid !== valid || value !== wanted || !calibrated || !conversionBusy)
    $fatal(1,"SPI_WIRE_RESULT word=%h value=%h valid=%b",wireWord,value,sampleValid);
  @(posedge serviceClock); #1; expectBusy=0;
  if(conversionDone || sampleValid) $fatal(1,"SPI_DUPLICATED_PUBLICATION");
  wait(!conversionBusy);
end endtask
"""
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name SPI admission: independent command/capture stalls ignore busy starts and retain each frame") {
      val heldState=if(click) 2 else 3
      ClockedSimulation.run(new SpiAdcFixture(click),name+"-spi-admission",s"""
        launch(16'hf123); retire(0);
        savedFrames=frames; savedReplies=replies;
        launch(16'ha987);
        // Backpressure only the actual producer bridge's idle admission. Its
        // payload/request registers and native consumers remain unforced.
        force dut.ca_child_tested_spi_adc.ca_child_command_bridge.state=$heldState;
        repeat(4) begin conversionStart=1; #1000; conversionStart=0; #1000; end
        if(frames!=savedFrames || replies!=savedReplies || !conversionBusy)
          $$fatal(1,"SPI_COMMAND_ADMISSION_STALL");
        release dut.ca_child_tested_spi_adc.ca_child_command_bridge.state;
        retire(1);
        if(frames!=savedFrames+1 || replies!=savedReplies+1) $$fatal(1,"SPI_COMMAND_REPLAY");
        savedFrames=frames; savedReplies=replies;
        launch(16'h5abc);
        force dut.ca_child_tested_spi_adc.ca_child_capture_bridge.state=$heldState;
        wait(!adcCsN); wait(adcCsN); #1;
        retainedTrace=dut.ca_child_tested_spi_adc.samples;
        repeat(4) begin
          conversionStart=1; adcMiso=1; #1000; conversionStart=0; adcMiso=0; #1000;
          if(dut.ca_child_tested_spi_adc.samples!==retainedTrace || !conversionBusy ||
             frames!=savedFrames+1 || replies!=savedReplies) $$fatal(1,"SPI_CAPTURE_ADMISSION_STALL");
        end
        release dut.ca_child_tested_spi_adc.ca_child_capture_bridge.state;
        retire(1);
        if(frames!=savedFrames+1 || replies!=savedReplies+1) $$fatal(1,"SPI_CAPTURE_REPLAY");
        #5000;
        if(frames!=savedFrames+1 || replies!=savedReplies+1 || conversionBusy) $$fatal(1,"SPI_LATE_REPLAY");
      """,monitor+"\nreg [31:0] retainedTrace;\n",referenceHalfPeriodNs=250,serviceHalfPeriodNs=25,
        maximumDelaySubtree=Some("tested_spi_adc"))
    }
    test(s"$name SPI age: admission excludes preceding elapsed time and publication includes its coincident tick once") {
      ClockedSimulation.run(new SpiAdcFixture(click),name+"-spi-age-edges","""
        launch(16'hf123); retire(0);
        wait(!conversionBusy); @(negedge serviceClock);
        wireWord=16'hacde; conversionStart=1; ageStep=77;
        @(negedge serviceClock); conversionStart=0; ageStep=0; expectBusy=1; #1;
        if(age!==0) $fatal(1,"SPI_AGE_INCLUDES_PRE_ADMISSION_TICK");
        force dut.ca_child_tested_spi_adc.ca_child_reply_bridge.state=0;
        wait(!adcCsN); wait(adcCsN); #2000;
        @(negedge serviceClock); ageStep=13;
        @(negedge serviceClock); ageStep=0; #1;
        if(age!==13) $fatal(1,"SPI_AGE_ACCUMULATION");
        release dut.ca_child_tested_spi_adc.ca_child_reply_bridge.state;
        wait(conversionDone); @(negedge serviceClock); ageStep=17; #1;
        if(!conversionDone || !sampleValid || age!==30) $fatal(1,"SPI_COINCIDENT_PUBLICATION_AGE");
        @(posedge serviceClock); #1; ageStep=0; expectBusy=0; #1;
        if(age!==30 || conversionDone) $fatal(1,"SPI_PUBLICATION_AGE_COUNTED_TWICE");
        wait(!conversionBusy);
      """,monitor,referenceHalfPeriodNs=250,serviceHalfPeriodNs=25,
        maximumDelaySubtree=Some("tested_spi_adc"))
    }
    test(s"$name SPI freshness: delayed physical capture stays old through host and supervisor batching") {
      val p=SocParameters(Groundlark.configuration.copy(programBytes=16,workingRamBytes=16),
        serviceHz=1000,staleMs=500,watchdogCycles=64,watchdogHoldCycles=32,
        adc=Some(AdcParameters(2,100)))
      ClockedSimulation.run(if(click) new ClickSpiAgeFixture(p) else new BdSpiAgeFixture(p),name+"-spi-age","""
        pauseConsumers=1;
        wait(!adcBusy);
        force dut.ca_child_spi_adc.ca_child_reply_bridge.state=0;
        wait(!adcCsN); wait(adcCsN); #50000;
        if(publication || !adcBusy) $fatal(1,"SPI_AGE_STALL_PRECONDITION");
        release dut.ca_child_spi_adc.ca_child_reply_bridge.state;
        wait(publication); oldAge=publicationAge;
        if(oldAge<500) $fatal(1,"SPI_BUFFERED_AGE_NOT_OLD");
        @(posedge serviceClock); #1;
        if(queued_capture_tailAge !== oldAge || hostCapture_tailAge !== oldAge)
          $fatal(1,"SPI_PUBLICATION_AGE_NOT_CAPTURED");
        // Keep the consumer paused for the next fresh frame. The stale gap
        // must survive compaction, even though the latest tail is fresh.
        wait(!publication); wait(publication); freshAge=publicationAge;
        if(freshAge>=500) $fatal(1,"SPI_FRESH_FRAME_PRECONDITION");
        @(posedge serviceClock); #1;
        if(queued_capture_count!==2 || queued_capture_maximumGap<500 ||
           queued_capture_tailAge!==freshAge || hostCapture_tailAge!==freshAge)
          $fatal(1,"SPI_STALE_GAP_ERASED");
        wait(!adcBusy);
        force dut.ca_child_spi_adc.ca_child_wave_bridge.state=0;
        pauseConsumers=0;
        wait(hostSample_sequence==2 && nativeState_sample_sequence==2); #1;
        if(hostSample_value!==13592 || nativeState_sample_value!==13592 ||
           hostSample_age<freshAge || nativeState_sample_age<freshAge || gpioOut[0])
          $fatal(1,"SPI_FRESHNESS_HOST_OR_SUPERVISOR");
        #50000;
        if(hostSample_valid && hostSample_age<500) $fatal(1,"SPI_HOST_AGE_STOPPED");
        if(gpioOut[0] || resets<2) $fatal(1,"SPI_SUPERVISOR_STALE_OR_RESET_COVERAGE");
        release dut.ca_child_spi_adc.ca_child_wave_bridge.state;
      ""","""
reg [15:0] shift; reg [31:0] oldAge,freshAge; integer resets=0;
always @(posedge systemReset) if(!reset) resets=resets+1;
always @(negedge adcCsN) begin shift={4'hf,12'd2200}; adcMiso=shift[15]; end
always @(negedge adcSclk) if(!adcCsN) begin shift=shift<<1; adcMiso=shift[15]; end
""",referenceHalfPeriodNs=250,serviceHalfPeriodNs=25,maximumDelaySubtree=Some("spi_adc"))
    }
    test(s"$name SPI wire: exact fastest waveform and complete maximum-delay conversion budget") {
      ClockedSimulation.run(new SpiAdcFixture(click),name+"-spi-wave","""
        for(campaign=0;campaign<2;campaign=campaign+1) begin
          for(n=0;n<28;n=n+1) begin
            launch(n<16 ? (n<<12) | (n%2 ? 12'haaa : 12'h555) : 16'hf000 | (1<<(n-16)));
            retire(n!=0);
            if($realtime-admitted > 6800) $fatal(1,"SPI_DIGITAL_BUDGET elapsed=%f",$realtime-admitted);
          end
          reset=1; #2000; reset=0; #5000;
        end
        if(frames != 56 || replies != 56 || resets<2) $fatal(1,"SPI_WIRE_COVERAGE");
      """,monitor,referenceHalfPeriodNs=250,serviceHalfPeriodNs=25,
        maximumDelaySubtree=Some("tested_spi_adc"))
    }
    test(s"$name SPI wire: buffered waveform/reply stalls retain age and priming across complete watchdog episodes") {
      ClockedSimulation.run(new SpiAdcFixture(click),name+"-spi-stalls","""
        launch(16'hf123); retire(0);
        savedFrames=frames; savedReplies=replies; savedResets=resets;
        // Hold real bridge admission registers; no derived endpoint is forced.
        force dut.ca_child_tested_spi_adc.ca_child_wave_bridge.state=0;
        force dut.ca_child_tested_spi_adc.ca_child_reply_bridge.state=0;
        launch(16'haabc);
        @(negedge serviceClock); ageStep=7;
        @(negedge serviceClock); ageStep=0;
        repeat(4) begin
          conversionStart=1; #1000; conversionStart=0; #1000;
        end
        if(frames!=savedFrames || replies!=savedReplies || age!=7 || !conversionBusy)
          $fatal(1,"SPI_WAVE_STALL_LOST");
        release dut.ca_child_tested_spi_adc.ca_child_wave_bridge.state;
        wait(frames==savedFrames+1); wait(adcCsN); #5000;
        if(replies!=savedReplies || !conversionBusy || tracking) $fatal(1,"SPI_REPLY_STALL_LOST");
        // The physical transfer is finished; both phases of application reset
        // must pass without replay, reprime, lost observations or lost age.
        #150000;
        if(resets-savedResets<2 || frames!=savedFrames+1 || replies!=savedReplies || age!=7)
          $fatal(1,"SPI_WATCHDOG_RETENTION");
        @(negedge serviceClock); ageStep=32'hfffffffd;
        @(negedge serviceClock); ageStep=0;
        if(age!==32'hffffffff) $fatal(1,"SPI_AGE_WRAP");
        release dut.ca_child_tested_spi_adc.ca_child_reply_bridge.state;
        retire(1);
        if(age!==32'hffffffff || replies!=savedReplies+1) $fatal(1,"SPI_OLD_FRAME_BECAME_FRESH");
        launch(16'h5fff); retire(1);
        if(age!==0) $fatal(1,"SPI_NEW_FRAME_AGE");
      """,monitor,referenceHalfPeriodNs=250,serviceHalfPeriodNs=25,
        maximumDelaySubtree=Some("tested_spi_adc"))
    }
    test(s"$name SPI wire: POR cancels every waveform phase and held publication then reprimes") {
      ClockedSimulation.run(new SpiAdcFixture(click),name+"-spi-por","""
        for(campaign=0;campaign<33;campaign=campaign+1) begin
          launch(16'hf987); retire(0);
          force dut.ca_child_tested_spi_adc.ca_child_reply_bridge.state=0;
          launch(16'h5123);
          wait(!adcCsN);
          if(campaign<32) begin wait(edges==campaign); #17; end
          else begin wait(adcCsN); #2000; end
          reset=1; expectBusy=0;
          release dut.ca_child_tested_spi_adc.ca_child_reply_bridge.state;
          #2000;
          if(!adcCsN || adcSclk || conversionDone || sampleValid) $fatal(1,"SPI_POR_PINS");
          savedReplies=replies; reset=0; #5000;
          if(replies!=savedReplies || conversionDone) $fatal(1,"SPI_POR_REPLAY");
          launch(16'hacde); retire(0); launch(16'h5edc); retire(1);
          reset=1; #2000; reset=0; #5000;
        end
      """,monitor,referenceHalfPeriodNs=250,serviceHalfPeriodNs=25,
        maximumDelaySubtree=Some("tested_spi_adc"))
    }
  }
}
