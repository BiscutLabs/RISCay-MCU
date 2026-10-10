// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class AdcScalingFixture(click: Boolean) extends FabricFixture(SocParameters(McuConfiguration(
  8,8,0,Vector.empty,ApplicationProfile(1,1,"adc-scaling",Vector.empty,Vector.empty)))) {
  private val pAdc=AdcParameters(2,100,7,1,offset = -100,calibrated=true)
  val conversionStart = IO(Input(Bool())); val conversionBusy = IO(Output(Bool()))
  val conversionDone = IO(Output(Bool())); val sampleValid = IO(Output(Bool()))
  val scaledValue = IO(Output(UInt(32.W))); val calibrated = IO(Output(Bool()))
  if(click) {
    val adc=asyncChild("tested_spi_adc")(d => new riscay.click.SpiAdc(pAdc,false,d))
    adc.clock:=serviceClock; adc.io.ageStep:=0.U
    adc.miso := adcMiso; adc.io.start := conversionStart; adcCsN := adc.csN; adcSclk := adc.sclk
    conversionBusy := adc.io.busy; conversionDone := adc.io.done; sampleValid := adc.io.result.valid
    scaledValue := adc.io.result.bits.value; calibrated := adc.io.result.bits.calibrated
  } else {
    val adc=asyncChild("tested_spi_adc")(d => new riscay.bd.SpiAdc(pAdc,false,d))
    adc.clock:=serviceClock; adc.io.ageStep:=0.U
    adc.miso := adcMiso; adc.io.start := conversionStart; adcCsN := adc.csN; adcSclk := adc.sclk
    conversionBusy := adc.io.busy; conversionDone := adc.io.done; sampleValid := adc.io.result.valid
    scaledValue := adc.io.result.bits.value; calibrated := adc.io.result.bits.calibrated
  }
}
class AdcScalingSpec extends AnyFunSuite {
  for(click <- Seq(false,true)) test(s"${if(click) "click" else "bd"}: native ADC scaling preserves discard, signed offset, calibration and POR") {
    ClockedSimulation.run(new AdcScalingFixture(click),"adc-scaling","""
      for(campaign=0;campaign<2;campaign=campaign+1) begin
        for(code=0;code<4;code=code+1) begin
          wait(!conversionBusy); @(negedge serviceClock);
          adcCode=(code==0 ? 0 : code==1 ? 4095 : code==2 ? 1 : 2000);
          wanted=adcCode*7-100; conversionStart=1;
          @(negedge serviceClock); conversionStart=0;
          wait(conversionDone); #1;
          if(sampleValid !== (code!=0) || scaledValue !== wanted || !calibrated || !conversionBusy)
            $fatal(1,"ADC_SCALE_PUBLICATION code=%d value=%h valid=%b",adcCode,scaledValue,sampleValid);
          @(posedge serviceClock); #1;
          if(conversionDone || sampleValid) $fatal(1,"ADC_SCALE_DUPLICATE");
        end
        reset=1; #2000; reset=0; #5000;
      end
    ""","""
integer code,campaign; reg [31:0] wanted; reg [11:0] adcCode; reg [15:0] adcShift;
always @(negedge adcCsN) begin adcShift={4'b0,adcCode}; adcMiso=adcShift[15]; end
always @(negedge adcSclk) if(!adcCsN) begin adcShift=adcShift<<1; adcMiso=adcShift[15]; end
""")
  }
}
