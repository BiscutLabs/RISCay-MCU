// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import java.util.zip.CRC32
import chisel3._
import chisel3.util.experimental.BoringUtils

class BdGenericBootFixture(p: SocParameters, preserveHierarchy: Boolean = false)
    extends riscay.bd.FourPhaseSoc(p,preserveHierarchy=preserveHierarchy) {
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
  protected def preserveHierarchy: Boolean = false
  import Assembly._
  private val config=McuConfiguration(256,256,7,Vector.empty,
    ApplicationProfile(1,1,"generic-boot",Vector(HostRegister(0,"RESULT")),Vector.empty))
  private val p=SocParameters(config,watchdogCycles=1000000,spiBoot=true)
  private val program=Seq(0x300000b7L,i(0x13,2,0,0,0x123),store(1,2,52,2),breakpoint)
  private def fixture(click: Boolean, params: SocParameters=p): SocTop =
    if(click) new ClickGenericBootFixture(params) else new BdGenericBootFixture(params,preserveHierarchy)
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
  private def model(data: Vector[Int], click: Boolean): String = {
    val flashBytes=math.max(4096,data.size)
    s"""
reg [7:0] flash [0:${flashBytes-1}]; integer initIndex, phase=0, bits=0, bitIndex=7;
reg [7:0] opcode=0, writeByte=0; reg [23:0] address=0, firstAddress=0;
reg writeEnabled=0, discardWrites=0;
reg protectFactory=0;
integer protectedFieldBase=-1;
integer written=0, eraseCount=0, commitRecords=0, eraseIndex, polls;
integer lastEraseBase=0;
integer readCommands=0, readReturns=0, flashEdges=0, appInstructions=0;
integer romInstructions=0, workEdges=0, serviceEdges=0;
integer bootWorkEdges=0,bootServiceEdges=0,bootFlashEdges=0;
real bootAt=0;
wire flashCsN = !gpioOe[5] || gpioOut[5];
initial begin
  for(initIndex=0;initIndex<$flashBytes;initIndex=initIndex+1) flash[initIndex]=255;
  ${data.zipWithIndex.filter(_._1!=255).map { case(b,n) => s"flash[$n]=8'h${b.toHexString};" }.mkString("\n")}
end
always @(negedge flashCsN) begin
  phase=0;bits=0;opcode=0;address=0;bitIndex=7;adcMiso=0;written=0;writeByte=0;
end
always @(posedge flashCsN) begin
  if(opcode==3) readReturns=readReturns+1;
  if(opcode==6) writeEnabled=1;
  if(opcode==8'h20 && phase==5) begin
    if(!writeEnabled) $$fatal(1,"FLASH_ERASE_WITHOUT_WREN");
    if(protectFactory && address<8192) $$fatal(1,"FACTORY_OR_GOLDEN_ERASED");
    if(protectedFieldBase>=0 && address>=protectedFieldBase && address<protectedFieldBase+4096)
      $$fatal(1,"PREVIOUS_BOOTABLE_FIELD_ERASED");
    lastEraseBase=address&24'hfff000;
    for(eraseIndex=(address&24'hfff000);eraseIndex<(address&24'hfff000)+4096;eraseIndex=eraseIndex+1)
      if(eraseIndex<$flashBytes && !discardWrites) flash[eraseIndex]=255;
    eraseCount=eraseCount+1;writeEnabled=0;
  end
  if(opcode==2 && phase==4) begin
    if(written>256 || (firstAddress&255)+written>256) $$fatal(1,"FLASH_PAGE_CROSSED");
    if((firstAddress&4095)==0 && written==4) commitRecords=commitRecords+1;
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
        if(!writeEnabled || address>=$flashBytes) $$fatal(1,"FLASH_PROGRAM_NOT_AUTHORIZED");
        if(protectFactory && address<8192) $$fatal(1,"FACTORY_OR_GOLDEN_PROGRAMMED");
        if(protectedFieldBase>=0 && address>=protectedFieldBase && address<protectedFieldBase+4096)
          $$fatal(1,"PREVIOUS_BOOTABLE_FIELD_PROGRAMMED");
        if(!discardWrites) flash[address]=flash[address]&writeByte;
        written=written+1;bits=0;address=(address&24'hffff00)|((address+1)&255);
      end
    end
  endcase
end
always @(negedge adcSclk) if(!flashCsN) begin
  if(phase==2) adcMiso=address<$flashBytes ? flash[address][bitIndex] : 1;
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
      bootWorkEdges=workEdges;bootServiceEdges=serviceEdges;bootFlashEdges=flashEdges;
      $$display("GENERIC_BOOT_ACTIVITY,rom=%0d,work=%0d,service=%0d,spi=%0d",romInstructions,workEdges,serviceEdges,flashEdges);
    end
  end
end
"""
  }

  private def little(words: Seq[Long]): Vector[Int] =
    words.flatMap(w => (0 until 4).map(b => ((w >>> (8*b))&255).toInt)).toVector
  private def crc(bytes: Seq[Int]): Long = {val c=new CRC32;bytes.foreach(c.update);c.getValue}
  private def slot(words: Seq[Long],generation: Long,requiredRam: Long=256): Vector[Int] = {
    val body=little(words)
    val header=little(Seq(0x59435352L,2L,body.size.toLong,0L,crc(body),0x10000L,requiredRam,127L,0L,7L,generation))
    header++little(Seq(crc(header)))++body
  }
  private def factory(a: Vector[Int],b: Vector[Int],golden: Vector[Int]): Vector[Int] = {
    val h=little(Seq(0x32425352L,2L,4096L,16384L,8192L,12288L,4096L))
    val data=Array.fill(16384)(255)
    Seq(0->(h++little(Seq(crc(h)))),8192->a,12288->b,4096->golden).foreach {case(base,bytes) =>
      bytes.zipWithIndex.foreach {case(value,index) => data(base+index)=value}
    }
    data.toVector
  }
  private def resultProgram(value: Int): Seq[Long] = Seq(0x300000b7L,i(0x13,2,0,0,value),store(1,2,52,2),breakpoint)
  private def badBody(bytes: Vector[Int]): Vector[Int] = bytes.updated(bytes.size-1,bytes.last^1)

  test("generic ROM capacity literal changes only generic build metadata") {
    val small=GenericBootRom.wordsFor(256);val large=GenericBootRom.wordsFor(2048)
    assert(small.last==256 && large.last==2048 && small.init==large.init)
    assert(GenericBootRom.words.last==0xc0dec0deL)
  }
  for(click <- Seq(false,true); scenario <- Seq("newest","newer-corrupt","newer-header-corrupt","both-corrupt","blank-fields","incompatible-newer","bad-directory","all-corrupt")) {
    test(s"${if(click) "Click" else "BD"} A/B external boot $scenario") {
      val aa=slot(resultProgram(0x111),1)
      val bb=slot(resultProgram(0x222),2,if(scenario=="incompatible-newer") 257 else 256)
      val gg=slot(resultProgram(0x333),0)
      val a=if(scenario=="blank-fields") Vector.empty else if(Set("both-corrupt","all-corrupt")(scenario)) badBody(aa) else aa
      val b=if(scenario=="blank-fields") Vector.empty else if(scenario=="newer-header-corrupt") bb.updated(40,bb(40)^1)
        else if(Set("newer-corrupt","both-corrupt","all-corrupt")(scenario)) badBody(bb) else bb
      val bytes=factory(a,b,if(scenario=="all-corrupt") badBody(gg) else gg)
      val data=if(scenario=="bad-directory") bytes.updated(28,bytes(28)^1) else bytes
      val fallback=Set("bad-directory","all-corrupt")(scenario)
      val expected=if(fallback) 0x123 else if(Set("both-corrupt","blank-fields")(scenario)) 0x333
        else if(Set("newer-corrupt","newer-header-corrupt","incompatible-newer")(scenario)) 0x111 else 0x222
      ClockedSimulation.run(fixture(click),"generic-ab-"+scenario,s"""
        protectFactory=1;wait(readReturns>0);wait(!spiOwned);
        ${if(fallback) s"if(programmed) $$fatal(1,\"AB_INVALID_IMAGE_STARTED\");${upload(program)}" else ""}
        wait(mode==4);read_words(128,0,0);
        if(snapshot[0+:32]!==32'h${expected.toHexString} || appInstructions!=4 || eraseCount)
          $$fatal(1,"AB_SELECTION result=%h retired=%d",snapshot[0+:32],appInstructions);
        """,model(data,click),deadlineNs=1000000000L,processTimeoutSeconds=480)
    }
  }
  for(click <- Seq(false,true); cut <- Seq("commit","erase-por","header-watchdog","incompatible-erase-por","oversized-erase-por","newer-b-erase-por")) {
    test(s"${if(click) "Click" else "BD"} A/B persistence $cut preserves the previous bootable image") {
      val previous=slot(resultProgram(0x111),1)
      val invalidNewer=if(cut=="incompatible-erase-por") slot(resultProgram(0x555),9,257)
        else if(cut=="oversized-erase-por") slot(resultProgram(0x555)++Seq.fill(124)(i(0x13,0,0,0,0)),9) else Vector.empty
      val preserveB=cut=="newer-b-erase-por"
      val previousBase=if(preserveB) 12288 else 8192
      val destinationBase=if(preserveB) 8192 else 12288
      val retainedValue=if(preserveB) "444" else "111"
      val data=factory(previous,if(preserveB) slot(resultProgram(0x444),2) else invalidNewer,slot(resultProgram(0x333),0))
      val por=cut.endsWith("por")
      // Exercise the real LF watchdog, with the existing recovery fixture's
      // shorter interval so ENTER_LOADER does not dominate simulation time.
      ClockedSimulation.run(fixture(click,p.copy(watchdogCycles=100000)),"generic-ab-persist-"+cut,s"""
        protectFactory=1;protectedFieldBase=$previousBase;wait(mode==4);command(9);expect_error(0);
        wait(systemReset);wait(!systemReset);wait(!spiOwned);#100000;
        ${upload(resultProgram(0x222),start=false)} command(10);wait(eraseCount==1);
        if(lastEraseBase!=$destinationBase) $$fatal(1,"AB_ERASED_ONLY_COMPATIBLE_FIELD_IMAGE");
        ${if(por) "reset=1;#2000;reset=0;" else if(cut=="header-watchdog") "wait(opcode==2 && phase==4 && written>=20);recovery=1;#2000;recovery=0;" else ""}
        ${if(!por) """
          wait(commitRecords==1);polls=0;read_words(1,0,8);
          while(snapshot[1] && polls<100) begin read_words(1,0,8);polls=polls+1;end
          if(!snapshot[2]) $fatal(1,"AB_PERSIST_DID_NOT_COMPLETE");
          reset=1;#2000;reset=0;
        """ else ""}
        wait(appInstructions==8);wait(mode==4);read_words(128,0,0);
        if(snapshot[0+:32]!==32'h${if(por) retainedValue else "222"}) $$fatal(1,"AB_RECOVERY_SELECTED_WRONG_IMAGE");
        if(flash[$previousBase]!=8'h52 || flash[4096]!=8'h52 || flash[0]!=8'h52) $$fatal(1,"AB_FALLBACK_STORAGE_LOST");
        ${if(!por) """
          command(4);await_locked();command(10);expect_error(2);
          if(commitRecords!=1) $fatal(1,"AB_LOCKED_FLASH_WRITE");
        """ else "if(commitRecords) $fatal(1,\"AB_PREMATURE_COMMIT\");"}
        """,model(data,click),deadlineNs=1500000000L,processTimeoutSeconds=600)
    }
  }
  for(click <- Seq(false,true); invalidDirectory <- Seq(false,true)) {
    test(s"${if(click) "Click" else "BD"} A/B refuses persistence with ${if(invalidDirectory) "invalid directory" else "exhausted generation"}") {
      val original=factory(slot(resultProgram(0x111),0xffffffffL),Vector.empty,slot(resultProgram(0x333),0))
      val data=if(invalidDirectory) original.updated(28,original(28)^1) else original
      ClockedSimulation.run(fixture(click,p.copy(watchdogCycles=100000)),"generic-ab-refuse-"+invalidDirectory,s"""
        protectFactory=1;protectedFieldBase=8192;
        ${if(invalidDirectory) "wait(readReturns>0);wait(!spiOwned);#100000;" else """
          wait(mode==4);command(9);expect_error(0);
          wait(systemReset);wait(!systemReset);wait(!spiOwned);#100000;
        """}
        ${upload(resultProgram(0x222),start=false)} command(10);
        polls=0;read_words(1,0,8);
        while(snapshot[1] && polls<100) begin read_words(1,0,8);polls=polls+1;end
        if(snapshot[2:1]!==0 || eraseCount || commitRecords || !programmed)
          $$fatal(1,"AB_UNSAFE_METADATA_AUTHORIZED_WRITE");
        expect_error(9);command(6);wait(mode==4);read_words(128,0,0);
        if(snapshot[0+:32]!==32'h222) $$fatal(1,"AB_REFUSAL_LOST_RAM_IMAGE");
        """,model(data,click),deadlineNs=1500000000L,processTimeoutSeconds=600)
    }
  }
  for(click <- Seq(false,true); fallback <- Seq(false,true)) {
    test(s"${if(click) "Click" else "BD"} production full-capacity A/B boot ${if(fallback) "golden fallback" else "primary"}") {
      val full=p.copy(config=config.copy(programBytes=2048,workingRamBytes=1024))
      def padded(value: Int)=resultProgram(value)++Seq.fill(508)(i(0x13,0,0,0,0))
      val a=slot(padded(0x111),1);val b=slot(padded(0x222),2);val g=slot(padded(0x333),0)
      val data=factory(if(fallback) badBody(a) else a,if(fallback) badBody(b) else b,g)
      ClockedSimulation.run(fixture(click,full),"generic-ab-full-"+fallback,s"""
        protectFactory=1;wait(mode==4);read_words(128,0,0);
        if(snapshot[0+:32]!==32'h${if(fallback) "333" else "222"} || appInstructions!=4 || eraseCount)
          $$fatal(1,"AB_FULL_CAPACITY_BOOT_FAILED");
        $$display("FULL_CAPACITY_BOOT,bytes=2048,fallback=${if(fallback) 1 else 0},ns=%0.3f,work=%0d,service=%0d,spi=%0d",bootAt,bootWorkEdges,bootServiceEdges,bootFlashEdges);
        """,model(data,click),deadlineNs=10000000000L,processTimeoutSeconds=3600)
    }
  }
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
    for(point <- Seq("boot-por","boot-watchdog","persist-por","persist-watchdog","persist-header-watchdog","persist-magic-watchdog")) {
      test(s"${if(click) "Click" else "BD"} recovery at $point") {
        val updating=point.startsWith("persist")
        val por=point.endsWith("por")
        ClockedSimulation.run(fixture(click),"generic-"+point,s"""
          ${if(updating) s"wait(readReturns>0);#100000;${upload(program,start=false)} command(10);wait(eraseCount==1);"
            else "@(posedge serviceClock);while(!loaderWrite) @(posedge serviceClock);#1;"}
          ${if(point=="persist-header-watchdog") "wait(opcode==2 && phase==4 && written>=20);" else ""}
          ${if(point=="persist-magic-watchdog") "wait(opcode==2 && phase==4 && firstAddress==0 && written==1);" else ""}
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
        // Isolate MISO wake from the next legitimate periodic sample. Drain
        // outstanding work with LF paused, then exercise the full idle window.
        referenceEnabled=0;wait(sleeping);
        if(adcBusy || !adcCsN) $fatal(1,"SPI_SLEEP_BEFORE_DRAIN");
        idleMisoCheck=1;
        repeat(20) begin #500;adcMiso=~adcMiso;end
        if(gpioEvents || !adcCsN) $fatal(1,"SPI_MISO_WOKE_GPIO");
        if(!sleeping) $fatal(1,"SPI_IDLE_MISO_WOKE_CPU");
        idleMisoCheck=0;resumedConversions=conversions;referenceEnabled=1;
        wait(conversions>resumedConversions);
        if(gpioEvents) $fatal(1,"SPI_RESUMED_MISO_WOKE_GPIO");
        """,model(Vector.empty,click)+"""
integer conversions=0,gpioEvents=0,resumedConversions=0;
reg [15:0] adcShift;reg watchGpio=0,idleMisoCheck=0;
always @(posedge serviceClock) if(!reset && watchGpio && gpioEvent) gpioEvents=gpioEvents+1;
always @(*) if(idleMisoCheck && (!sleeping || !adcCsN || adcBusy || gpioEvents))
  $fatal(1,"SPI_IDLE_MISO_WAKE_OR_ACTIVITY");
always @(negedge adcCsN) if(!reset) begin
  if(!flashCsN || spiOwned) $fatal(1,"SHARED_SPI_DOUBLE_OWNER");
  conversions=conversions+1;adcShift=16'h5aaa;adcMiso=adcShift[15];
end
always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1;adcMiso=adcShift[15];end
""",deadlineNs=100000000L,processTimeoutSeconds=240,referenceHalfPeriodNs=1250)
    }
  }
}
