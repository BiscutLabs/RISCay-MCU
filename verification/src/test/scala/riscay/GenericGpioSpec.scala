// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Profile descriptions are metadata. Only explicit MMIO writes enable pads. */
class GenericGpioSpec extends AnyFunSuite {
  private val config = McuConfiguration(16,16,3,Vector.empty,
    ApplicationProfile(1,1,"metadata-only",Vector(HostRegister(0,"APP")),
      Vector(PinRole(0,"label",output=true,resetHigh=true))))
  private val tasks = """
task write_mmio(input [31:0] offset, input [31:0] value); begin
  @(negedge serviceClock); request_bits_operation=2; request_bits_address=32'h30000000+offset;
  request_bits_mask=15; request_bits_data=value; request_valid=1; response_ready=0;
  @(posedge serviceClock); while(!request_ready) @(posedge serviceClock);
  #1; request_valid=0; wait(response_valid);
  if(response_bits_error) $fatal(1,"GENERIC_GPIO_MMIO_ERROR");
  @(negedge serviceClock); response_ready=1;
  @(posedge serviceClock); #1; response_ready=0;
end endtask
"""
  for(click <- Seq(false,true); retain <- Seq(false,true); spi <- Seq(false,true)) {
    test(s"${if(click) "Click" else "BD"} GPIO POR inputs and watchdog retain=$retain SPI=$spi") {
      val p=SocParameters(if(spi) config.copy(workingRamBytes=256,gpioCount=7) else config,
        watchdogCycles=1000,retainGpioOnWatchdog=retain,spiBoot=spi)
      ClockedSimulation.run(if(click) new ClickResetCrossingFixture(p) else new ResetCrossingFixture(p),
        "generic-gpio", s"""
        heartbeatEnabled=1;
        #20000;
        if(gpioOut!==0 || gpioOe!==0) $$fatal(1,"PROFILE_CHANGED_POR_GPIO");
        write_mmio(24,${if(spi) 63 else 7}); write_mmio(28,${if(spi) 63 else 7}); write_mmio(48,0); write_mmio(52,32'h12345678);
        if(gpioOut!==${if(spi) 63 else 7} || gpioOe!==${if(spi) 63 else 7}) $$fatal(1,"GENERIC_GPIO_OWNERSHIP_OVERRIDE");
        heartbeatEnabled=0; wait(systemReset); #1;
        if(gpioOut!==${if(retain) 7 else 0} || gpioOe!==${if(retain) 7 else 0})
          $$fatal(1,"GENERIC_GPIO_RESET_ISOLATION");
        wait(!systemReset); #20000;
        if(gpioOut!==${if(retain) 7 else 0} || gpioOe!==${if(retain) 7 else 0})
          $$fatal(1,"GENERIC_GPIO_RECOVERY_STATE");
        reset=1; #2000;
        if(gpioOut!==0 || gpioOe!==0) $$fatal(1,"GENERIC_GPIO_POR_RETENTION");
        reset=0; #20000;
        if(gpioOut!==0 || gpioOe!==0) $$fatal(1,"GENERIC_GPIO_POR_REPLAY");
        """, tasks)
    }
  }
}
