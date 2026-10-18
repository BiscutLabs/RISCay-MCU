// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Exercise the wire deadline, not just eventual native snapshot completion.
  * The host does not stretch SCL while an application reset is in progress.
  */
class AppSnapshotRecoverySpec extends AnyFunSuite {
  private val config = McuConfiguration(256,256,7,Vector.empty,
    ApplicationProfile(1,1,"snapshot-recovery",Vector(HostRegister(0,"VALUE")),Vector.empty))
  private val tasks = """
integer captures=0;
always @(posedge serviceClock) if(!reset && snapshotCaptured) captures=captures+1;
task app_access(input integer wr,input integer off,input [31:0] data,input [31:0] expected);
begin
  @(negedge serviceClock);
  request_bits_operation=wr ? 2:1;request_bits_address=32'h30000000+off;
  request_bits_data=data;request_bits_mask=15;request_valid=1;
  @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);
  #1;request_valid=0;
  wait(response_valid);
  if(response_bits_error || response_bits_data!==expected) $fatal(1,"RECOVERY_SETUP_ACCESS");
  @(negedge serviceClock);response_ready=1;
  @(posedge serviceClock);#1;response_ready=0;
end endtask
// Keep the already-selected application bank. This avoids confounding the
// snapshot boundary with a host selector command during reset.
reg [255:0] selectedSnapshot;
reg [31:0] selectedSupported;
task read_selected;
integer b; reg [7:0] value;
begin
  start_bus();write_byte(8'h6b);
  for(b=0;b<36;b=b+1) begin
    read_byte(value,b==35);
    if(b<32) selectedSnapshot[8*b+:8]=value;else selectedSupported[8*(b-32)+:8]=value;
  end
  stop_bus();
end endtask
"""

  test("BD serial host reads cleared application words during application recovery") {
    ClockedSimulation.run(new AppRegisterIntegrationFixture(SocParameters(config,
      watchdogCycles=1000000,spiBoot=true)),"app-snapshot-recovery","""
      wait(!cancel);#1000;
      app_access(1,48,0,0);app_access(1,52,32'ha5c35a3c,0);
      read_words(128,0,0);
      if(snapshot[31:0]!==32'ha5c35a3c || supported!==1)
        $fatal(1,"RECOVERY_INITIAL_SNAPSHOT");
      begin : during_recovery
        integer beforeCaptures;
        resetApplication=1;wait(cancel);wait(nativeReset);#2000;
        beforeCaptures=captures;
        // The application words have been cleared. A completed I2C transaction
        // must capture that bank before the first byte, not replay the old bank
        // and perform its requested capture after reset eventually reopens.
        read_selected();
        if(selectedSnapshot[31:0]!==0 || selectedSupported!==1)
          $fatal(1,"APP_RECOVERY_SERIAL_STALE_BANK actual=%h supported=%h",selectedSnapshot[31:0],selectedSupported);
        if(captures!==beforeCaptures+1)
          $fatal(1,"APP_RECOVERY_SERIAL_CAPTURE_COUNT before=%d after=%d",beforeCaptures,captures);
        resetApplication=0;wait(!cancel);#1000;
        read_selected();
        if(selectedSnapshot[31:0]!==0 || selectedSupported!==1) $fatal(1,"APP_RECOVERY_SERIAL_REOPEN");
      end
    """,tasks)
  }
}
