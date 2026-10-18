// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._
import java.util.zip.CRC32

class BootIngressSpec extends AnyFunSuite {
  private val config=McuConfiguration(16,16,3,Vector.empty,
    ApplicationProfile(1,1,"boot-ingress",Vector.empty,Vector.empty))
  private val words=Seq(0x00100073L,0x12345678L,0x87654321L,0xdeadbeefL)
  private val crc=new CRC32
  words.foreach(w => (0 until 4).foreach(b => crc.update(((w >>> (8*b))&255).toInt)))
  private val tasks="""
reg [31:0] answer;
task bus(input [1:0] op,input [31:0] addr,input [31:0] value); begin
  @(negedge serviceClock); request_bits_operation=op;request_bits_address=addr;
  request_bits_mask=15;request_bits_data=value;request_valid=1;response_ready=0;
  @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);
  #1;request_valid=0;wait(response_valid);answer=response_bits_data;
  if(response_bits_error) $fatal(1,"BOOT_INGRESS_BUS_ERROR addr=%h",addr);
  @(negedge serviceClock);response_ready=1;@(posedge serviceClock);#1;response_ready=0;
end endtask
task boot_command(input [31:0] v);begin bus(2,32'h30000050,v);end endtask
task data_word(input [31:0] v);begin bus(2,32'h30000054,v);end endtask
task status(input [7:0] error);begin bus(1,32'h3000004c,0);
  if(answer[15:8]!==error) $fatal(1,"BOOT_INGRESS_STATUS actual=%h expected=%h",answer,error);
end endtask
"""
  for(click <- Seq(false,true)) {
    test(s"${if(click) "Click" else "BD"} streaming boot full-width validation, ownership, CRC and lock") {
      val header=Seq(16L,0L,crc.getValue,0x10000L,16L,7L,0L,123L)
      val invalid=Seq((0,0L,4),(0,17L,4),(0,0x80000010L,4),
        (1,16L,4),(1,2L,4),(3,0x10001L,5),(4,17L,5),(5,8L,5),(6,1L,5))
      val bad=invalid.map { case(index,value,error) =>
        "boot_command(1);status(0);\n" + header.take(index).map(v => s"data_word(32'h${v.toHexString});status(0);").mkString("\n") +
          s"\ndata_word(32'h${value.toHexString});status($error);if(programmed) $$fatal(1,\"BAD_HEADER_VALID\");"
      }.mkString("\n")
      ClockedSimulation.run(if(click) new ClickFabricFixture(SocParameters(config,watchdogCycles=1000000))
        else new FabricFixture(SocParameters(config,watchdogCycles=1000000)),"boot-ingress",s"""
        $bad
        boot_command(1);status(0);
        bus(1,32'h30000054,0);if(answer!==0) $$fatal(1,"BOOT_STREAM_READ_NOT_ZERO");
        status(0);if(answer[19:16]!==0 || !answer[3]) $$fatal(1,"BOOT_STREAM_READ_CHANGED_SESSION");
        begin_image(4,0,0,32'h10000);expect_error(3);
        ${header.map(v => s"data_word(32'h${v.toHexString});status(0);").mkString("\n")}
        boot_command(2);status(7);if(programmed) $$fatal(1,"TRUNCATED_BOOT_VALID");
        ${words.map(v => s"data_word(32'h${v.toHexString});status(0);").mkString("\n")}
        data_word(0);status(4);
        boot_command(2);status(0);
        if(!programmed || mode!=2) $$fatal(1,"COMPLETE_BOOT_INVALID");
        ${words.zipWithIndex.map { case(v,n) => s"bus(1,32'h${(0x10000000L+4*n).toHexString},0);if(answer!==32'h${v.toHexString}) $$fatal(1,\"BOOT_RAM_WORD_$n\");" }.mkString("\n")}
        command(4);await_locked();boot_command(1);status(2);
        if(!programmed || !locked) $$fatal(1,"LOCKED_BOOT_METADATA_CHANGED");
        boot_command(3);status(0);if(mode!=3) $$fatal(1,"LOCKED_RETAINED_START");
        """,tasks)
    }
  }
}
