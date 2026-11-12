// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class DesyncStopSpec extends AnyFunSuite with SocImplementationSuite {
  override protected def synchronous: Boolean = true
  override protected def generated: Boolean = true
  private val config=McuConfiguration(16,32,3,Vector.empty,
    ApplicationProfile(1,1,"stop-wake",Vector.empty,Vector.empty))
  private val p=SocParameters(config,watchdogCycles=10000,
    lowPower=Some(LowPowerParameters(maximumSleepMs=1000,stopServiceClock=true)))
  test("desync drains, wakes on GPIO/SDA/LF, handles wake while stopping and POR at rest") {
    run(new riscay.clocked.ClockedSoc(p),"desync-stop-wake","""
      wait(!serviceClockEnable); #5000; saved=captures; #10000;
      if(captures!==saved) $fatal(1,"NATIVE_GRAPH_DID_NOT_STOP");
      gpioIn=5;wait(serviceClockEnable);wait(!serviceClockEnable);
      // SDA wake uses the same public address probe as the stopped-clock chip.
      read_words(0,0,0);
      if(snapshot[0+:32]!==32'h00010000) $fatal(1,"SDA_WAKE_LOST_ABI");
      wait(!serviceClockEnable); saved=captures;
      #1200000;
      if(captures<=saved) $fatal(1,"LF_DID_NOT_WAKE_GRAPH");
      for(i=0;i<8;i=i+1) begin
        wait(!serviceClockEnable); #(i*37); gpioIn=gpioIn^1;
        wait(serviceClockEnable);
      end
      wait(!serviceClockEnable);reset=1;#2000;
      if(gpioOe || programmed || locked || !systemReset) $fatal(1,"STOPPED_POR_STATE");
      reset=0;wait(!systemReset);wait(!serviceClockEnable);
      read_words(0,0,0);
      if(snapshot[0+:32]!==32'h00010000) $fatal(1,"POR_WAKE_LOST_ABI");
    ""","""
      integer captures=0,saved=0,i;
      always @(posedge dut.desync_cpu_capture) if(!reset) captures=captures+1;
    """,referenceHalfPeriodNs=125000,processTimeoutSeconds=180)
  }
}
