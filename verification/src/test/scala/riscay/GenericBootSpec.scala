// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import java.util.zip.CRC32
import chisel3._
import chisel3.util.experimental.BoringUtils

class BdGenericBootFixture(p: SocParameters) extends riscay.bd.FourPhaseSoc(p) {
  val recovery=IO(Input(Bool()))
  applicationResetRequest := reset.asBool || watchdog.io.expired || recovery
  val spiOwned=IO(Output(Bool())); spiOwned:=fabric.io.spiClaimed
  val adcBusy=IO(Output(Bool())); adcBusy:=fabric.io.adc.busy
  val gpioEvent=IO(Output(Bool())); gpioEvent:=BoringUtils.bore(fabric.gpioActivity)
  val loaderWrite=IO(Output(Bool())); loaderWrite:=BoringUtils.bore(fabric.programLoaderCommit)
  val pauseBootStatus=IO(Input(Bool()));val statusWaiting=IO(Output(Bool()))
  statusWaiting:=requestBridge.out.valid && requestBridge.out.bits.operation===1.U &&
    requestBridge.out.bits.address===(MemoryMap.mmio+76).U &&
    BoringUtils.bore(fabric.controlState.bootSession) && BoringUtils.bore(fabric.controlState.bootIndex)===0.U
  fabric.io.request.valid:=requestBridge.out.valid && !(pauseBootStatus && statusWaiting)
  requestBridge.out.ready:=fabric.io.request.ready && !(pauseBootStatus && statusWaiting)
}
class ClickGenericBootFixture(p: SocParameters) extends riscay.click.ClickSoc(p) {
  val recovery=IO(Input(Bool()))
  applicationResetRequest := reset.asBool || watchdog.io.expired || recovery
  val spiOwned=IO(Output(Bool())); spiOwned:=fabric.io.spiClaimed
  val adcBusy=IO(Output(Bool())); adcBusy:=fabric.io.adc.busy
  val gpioEvent=IO(Output(Bool())); gpioEvent:=BoringUtils.bore(fabric.gpioActivity)
  val loaderWrite=IO(Output(Bool())); loaderWrite:=BoringUtils.bore(fabric.programLoaderCommit)
  val pauseBootStatus=IO(Input(Bool()));val statusWaiting=IO(Output(Bool()))
  statusWaiting:=requestBridge.out.valid && requestBridge.out.bits.operation===1.U &&
    requestBridge.out.bits.address===(MemoryMap.mmio+76).U &&
    BoringUtils.bore(fabric.controlState.bootSession) && BoringUtils.bore(fabric.controlState.bootIndex)===0.U
  fabric.io.request.valid:=requestBridge.out.valid && !(pauseBootStatus && statusWaiting)
  requestBridge.out.ready:=fabric.io.request.ready && !(pauseBootStatus && statusWaiting)
}

class GenericBootSpec extends AnyFunSuite {
  import Assembly._
  private val config=McuConfiguration(256,256,7,Vector.empty,
    ApplicationProfile(1,1,"generic-boot",Vector(HostRegister(0,"RESULT")),Vector.empty))
  private val p=SocParameters(config,watchdogCycles=1000000,spiBoot=true)
  private val program=Seq(0x300000b7L,i(0x13,2,0,0,0x123),store(1,2,52,2),breakpoint)
  private def fixture(click: Boolean, params: SocParameters=p): SocTop =
    if(click) new ClickGenericBootFixture(params) else new BdGenericBootFixture(params)
  private def upload(words: Seq[Long], start: Boolean = true): String = {
    val crc=new CRC32; words.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b))&255).toInt)))
    s"begin_image(${words.size*4},0,32'h${crc.getValue.toHexString},32'h00010000);\n" +
      words.zipWithIndex.map { case(w,n) => s"put_word(${n*4},32'h${w.toHexString});" }.mkString("\n") +
      "\ncommand(3); await_ready();" + (if(start) "command(6);" else "")
  }
  private def image(corrupt: Boolean): Vector[Int] = {
    val bytes=program.flatMap(w => (0 until 4).map(b => ((w >>> (8*b))&255).toInt))
    val crc=new CRC32; bytes.foreach(crc.update)
    val words=Seq(0x59435352L,1L,bytes.size.toLong,0L,crc.getValue,0x00010000L,256L,127L,0L,123L)
    val result=(words.flatMap(w => (0 until 4).map(b => ((w >>> (8*b))&255).toInt))++bytes).toVector
    if(corrupt) result.updated(40,result(40)^1) else result
  }
  private def model(data: Vector[Int], click: Boolean): String = s"""
reg [7:0] flash [0:4095]; integer initIndex, phase=0, bits=0, bitIndex=7;
reg [7:0] opcode=0, writeByte=0; reg [23:0] address=0, firstAddress=0;
reg writeEnabled=0, discardWrites=0;
integer written=0, eraseCount=0, commitRecords=0, eraseIndex, polls;
integer readCommands=0, readReturns=0, flashEdges=0, appInstructions=0;
integer romInstructions=0, workEdges=0, serviceEdges=0;
real bootAt=0;
wire flashCsN = !gpioOe[5] || gpioOut[5];
initial begin
  for(initIndex=0;initIndex<4096;initIndex=initIndex+1) flash[initIndex]=255;
  ${data.zipWithIndex.map { case(b,n) => s"flash[$n]=8'h${b.toHexString};" }.mkString("\n")}
end
always @(negedge flashCsN) begin
  phase=0;bits=0;opcode=0;address=0;bitIndex=7;adcMiso=0;written=0;writeByte=0;
end
always @(posedge flashCsN) begin
  if(opcode==3) readReturns=readReturns+1;
  if(opcode==6) writeEnabled=1;
  if(opcode==8'h20 && phase==5) begin
    if(!writeEnabled) $$fatal(1,"FLASH_ERASE_WITHOUT_WREN");
    for(eraseIndex=(address&24'hfff000);eraseIndex<(address&24'hfff000)+4096;eraseIndex=eraseIndex+1)
      if(eraseIndex<4096 && !discardWrites) flash[eraseIndex]=255;
    eraseCount=eraseCount+1;writeEnabled=0;
  end
  if(opcode==2 && phase==4) begin
    if(written>256 || (firstAddress&255)+written>256) $$fatal(1,"FLASH_PAGE_CROSSED");
    if(firstAddress==0 && written==4) commitRecords=commitRecords+1;
    writeEnabled=0;
  end
end
always @(posedge adcSclk) if(!reset && !flashCsN) begin
  flashEdges=flashEdges+1;
  if(!adcCsN) $$fatal(1,"BOOT_SPI_ADC_CONTENTION");
  case(phase)
    0: begin opcode={opcode[6:0],gpioOut[4]};bits=bits+1;
      if(bits==8) begin
        bits=0;
        if(opcode==3) begin phase=1;readCommands=readCommands+1;end
        else if(opcode==2 || opcode==8'h20) phase=1;
        else if(opcode==6) phase=6;
        else if(opcode==5) phase=3;
        else $$fatal(1,"BOOT_SPI_OPCODE %h",opcode);
      end
    end
    1: begin address={address[22:0],gpioOut[4]};bits=bits+1;
      if(bits==24) begin
        phase=opcode==3 ? 2 : (opcode==2 ? 4 : 5);bitIndex=7;firstAddress=address;bits=0;
      end
    end
    2: begin if(bitIndex==0) begin bitIndex=7;address=address+1;end else bitIndex=bitIndex-1;end
    4: begin
      writeByte={writeByte[6:0],gpioOut[4]};bits=bits+1;
      if(bits==8) begin
        if(!writeEnabled || address>=4096) $$fatal(1,"FLASH_PROGRAM_NOT_AUTHORIZED");
        if(!discardWrites) flash[address]=flash[address]&writeByte;
        written=written+1;bits=0;address=(address&24'hffff00)|((address+1)&255);
      end
    end
  endcase
end
always @(negedge adcSclk) if(!flashCsN) begin
  if(phase==2) adcMiso=address<4096 ? flash[address][bitIndex] : 1;
  else adcMiso=0;
end
always @(posedge serviceClock) if(!reset) begin
  serviceEdges=serviceEdges+1;if(!sleeping) workEdges=workEdges+1;
end
always @(${if(click) "" else "posedge "}traceEvent) if(!reset) begin
  if(trace_pc<32'h10000000) romInstructions=romInstructions+1;
  else begin
    appInstructions=appInstructions+1;
    if(appInstructions==1) begin
      bootAt=$$realtime; $$display("GENERIC_FLASH_BOOT_NS,%0.3f",bootAt);
      $$display("GENERIC_BOOT_ACTIVITY,rom=%0d,work=%0d,service=%0d,spi=%0d",romInstructions,workEdges,serviceEdges,flashEdges);
    end
  end
end
"""
  for(click <- Seq(false,true); scenario <- Seq("valid","corrupt","incompatible","blank")) {
    test(s"${if(click) "Click" else "BD"} generic SPI boot $scenario") {
      val bytes=if(scenario=="blank") Vector.empty
        else if(scenario=="incompatible") image(false).updated(20,1) else image(scenario=="corrupt")
      val valid=scenario=="valid"
      ClockedSimulation.run(if(click) new riscay.click.ClickSoc(p) else new riscay.bd.FourPhaseSoc(p),
        "generic-boot-"+scenario, s"""
        wait(readReturns>0);
        ${if(valid) "wait(mode==4);" else "#100000;"}
        if(programmed!==${if(valid) 1 else 0} || locked || readCommands!=1)
          $$fatal(1,"GENERIC_BOOT_VALIDATION programmed=%b mode=%d reads=%d",programmed,mode,readCommands);
        ${if(!valid) upload(program) else ""}
        wait(mode==4);
        read_words(128,0,0);
        if(snapshot[0+:32]!==32'h123 || appInstructions!=4)
          $$fatal(1,"GENERIC_BOOT_EXECUTION result=%h retired=%d",snapshot[0+:32],appInstructions);
        if(!adcCsN || !flashCsN || adcSclk) $$fatal(1,"GENERIC_BOOT_BUS_NOT_RELEASED");
        """,model(bytes,click),deadlineNs=100000000L,processTimeoutSeconds=180)
    }
  }
  for(click <- Seq(false,true)) {
    test(s"${if(click) "Click" else "BD"} rejected host mutation cannot corrupt the ROM owner's progress result") {
      ClockedSimulation.run(fixture(click),"generic-transport-isolation","""
        pauseBootStatus=1;wait(statusWaiting);
        command(4);expect_error(3);
        // This is precisely between BEGIN_OPEN's accepted effect and ROM's
        // status read; the global host error must not substitute for its result.
        pauseBootStatus=0;wait(mode==4);
        if(!programmed || locked || appInstructions!=4 || readCommands!=1)
          $fatal(1,"HOST_ERROR_ABORTED_VALID_FLASH_BOOT");
        """,model(image(false),click),deadlineNs=100000000L,processTimeoutSeconds=240)
    }
    test(s"${if(click) "Click" else "BD"} full-capacity persistence crosses the 256-byte page boundary") {
      val padded=program++Seq.fill(60)(i(0x13,0,0,0,0))
      ClockedSimulation.run(fixture(click),"generic-persist-page",s"""
        wait(readReturns>0);#100000;
        ${upload(padded,start=false)} command(10);wait(commitRecords==1);
        polls=0;read_words(1,0,8);
        while(snapshot[1] && polls<100) begin read_words(1,0,8);polls=polls+1;end
        if(!snapshot[2] || eraseCount!=1 || flash[40]!=8'hb7 || flash[292]!=8'h13)
          $$fatal(1,"FLASH_PAGE_OR_LAST_WORD_LOST");
        reset=1;#2000;reset=0;wait(mode==4);
        if(appInstructions!=4 || !programmed) $$fatal(1,"FULL_CAPACITY_PERSIST_BOOT");
        """,model(Vector.empty,click),deadlineNs=1000000000L,processTimeoutSeconds=480)
    }
    test(s"${if(click) "Click" else "BD"} ENTER_LOADER uses the independent watchdog despite application kicks") {
      val kicking=Seq(0x300000b7L,0x57445137L,i(0x13,2,0,2,-185),store(1,2,32,2),jal(0,-4))
      ClockedSimulation.run(fixture(click,p.copy(watchdogCycles=100000)),"generic-enter-loader",s"""
        wait(readReturns>0);#100000;
        ${upload(kicking,start=false)} command(5);wait(mode==3);#500000;
        command(9);expect_error(0);
        wait(systemReset);wait(!systemReset);wait(!spiOwned);#100000;
        read_words(1,0,8);
        if(!snapshot[0] || !programmed || locked || mode!=2)
          $$fatal(1,"ENTER_LOADER_AUTO_RESTARTED");
        savedInstructions=appInstructions;#200000;
        if(appInstructions!=savedInstructions) $$fatal(1,"ENTER_LOADER_DID_NOT_HOLD");
        read_words(0,0,8);if(snapshot[0+:32]!=1) $$fatal(1,"ENTER_LOADER_CRASH_COUNT");
        command(6);wait(mode==3);await_locked();command(9);expect_error(2);
        read_words(1,0,8);if(snapshot[0]) $$fatal(1,"LOCKED_ENTER_LOADER_EFFECT");
        """,model(Vector.empty,click)+"\ninteger savedInstructions;\n",deadlineNs=150000000L,processTimeoutSeconds=240)
    }
    test(s"${if(click) "Click" else "BD"} explicit write-through, POR boot and lock") {
      ClockedSimulation.run(if(click) new riscay.click.ClickSoc(p) else new riscay.bd.FourPhaseSoc(p),
        "generic-persist",s"""
        wait(readReturns>0);#100000;
        ${upload(program,start=false)}
        command(10);
        command(4);expect_error(3); // Persistence owns the image until read-back completes.
        wait(commitRecords==1);
        polls=0;
        read_words(1,0,8);
        while(snapshot[1] && polls<100) begin read_words(1,0,8);polls=polls+1;end
        if(snapshot[2:0]!==4 || supported!==1 || eraseCount!=1 || appInstructions!=0)
          $$fatal(1,"FLASH_PERSISTENCE_STATUS %h",snapshot);
        command(6);wait(mode==4);
        reset=1;#2000;reset=0;
        wait(appInstructions==8);wait(mode==4);
        if(!programmed || locked || eraseCount!=1) $$fatal(1,"PERSISTED_POR_BOOT");
        read_words(128,0,0);if(snapshot[0+:32]!==32'h123) $$fatal(1,"PERSISTED_APPLICATION_RESULT");
        command(4);await_locked();command(10);expect_error(2);
        if(eraseCount!=1 || commitRecords!=1) $$fatal(1,"LOCKED_FLASH_WRITE");
        """,model(Vector.empty,click),deadlineNs=200000000L,processTimeoutSeconds=240)
    }
    test(s"${if(click) "Click" else "BD"} flash read-back failure never commits") {
      ClockedSimulation.run(fixture(click),"generic-persist-failure",s"""
        wait(readReturns>0);#100000;
        ${upload(program,start=false)}
        discardWrites=1;command(10);
        polls=0;read_words(1,0,8);
        while(snapshot[1] && polls<100) begin read_words(1,0,8);polls=polls+1;end
        if(snapshot[2:1]!==0 || eraseCount!=1 || commitRecords || !programmed)
          $$fatal(1,"FLASH_BAD_READBACK_COMMITTED");
        expect_error(9);command(6);wait(mode==4);
        if(appInstructions!=4) $$fatal(1,"READBACK_FAILURE_LOST_RAM_IMAGE");
        """,model(Vector.empty,click),deadlineNs=200000000L,processTimeoutSeconds=240)
    }
    for(point <- Seq("boot-por","boot-watchdog","persist-por","persist-watchdog")) {
      test(s"${if(click) "Click" else "BD"} recovery at $point") {
        val updating=point.startsWith("persist")
        val por=point.endsWith("por")
        ClockedSimulation.run(fixture(click),"generic-"+point,s"""
          ${if(updating) s"wait(readReturns>0);#100000;${upload(program,start=false)} command(10);wait(eraseCount==1);"
            else "@(posedge serviceClock);while(!loaderWrite) @(posedge serviceClock);#1;"}
          ${if(por) "reset=1;#2000;reset=0;" else "recovery=1;#2000;recovery=0;"}
          ${if(updating && por) s"""
            wait(readReturns>1);#100000;
            if(programmed || appInstructions || commitRecords) $$fatal(1,"INTERRUPTED_UPDATE_ACCEPTED");
            ${upload(program)} wait(mode==4);
          """ else if(updating) """
            wait(commitRecords==1);polls=0;read_words(1,0,8);
            while(snapshot[1] && polls<100) begin read_words(1,0,8);polls=polls+1;end
            if(!snapshot[2] || eraseCount!=2) $fatal(1,"WATCHDOG_PERSIST_RETRY_LOST");
            command(6);wait(mode==4);
          """ else "wait(mode==4);"}
          if(appInstructions!=4 || !programmed) $$fatal(1,"RESET_BOOT_LOST_OR_REPLAYED");
          if(!flashCsN || adcSclk) $$fatal(1,"RESET_FLASH_BUS_STUCK");
          """,model(if(updating) Vector.empty else image(false),click),deadlineNs=250000000L,processTimeoutSeconds=240)
      }
    }
    test(s"${if(click) "Click" else "BD"} shared ADC bus drains, resumes and never raises a GPIO event") {
      val shared=p.copy(config=config.copy(measurements=Vector(MeasurementChannel(0,"sample",1,0))),
        adc=Some(AdcParameters(2,100000)),lowPower=Some(LowPowerParameters()))
      ClockedSimulation.run(fixture(click,shared),"generic-shared-spi","""
        gpioIn=0; wait(readReturns>0);wait(!spiOwned);watchGpio=1;
        wait(conversions>=2);wait(!adcCsN);
        // Recovery requests the bus while the ADC owns it. The entire native
        // transaction must drain before ROM drives shared SCLK.
        recovery=1;#2000;recovery=0;
        wait(spiOwned);if(adcBusy || !adcCsN) $fatal(1,"SPI_CLAIM_BEFORE_DRAIN");
        wait(readReturns>1);wait(!spiOwned);wait(conversions>=4);
        wait(sleeping);#10000;
        if(gpioEvents || !adcCsN) $fatal(1,"SPI_MISO_WOKE_GPIO");
        """,model(Vector.empty,click)+"""
integer conversions=0,gpioEvents=0;reg [15:0] adcShift;reg watchGpio=0;
always @(posedge serviceClock) if(!reset && watchGpio && gpioEvent) gpioEvents=gpioEvents+1;
always @(negedge adcCsN) if(!reset) begin
  if(!flashCsN || spiOwned) $fatal(1,"SHARED_SPI_DOUBLE_OWNER");
  conversions=conversions+1;adcShift=16'h5aaa;adcMiso=adcShift[15];
end
always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1;adcMiso=adcShift[15];end
""",deadlineNs=100000000L,processTimeoutSeconds=240,referenceHalfPeriodNs=1250)
    }
  }
}
