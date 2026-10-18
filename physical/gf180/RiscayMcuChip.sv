// SPDX-License-Identifier: Apache-2.0
// Logical chip shell. Analog macros and physical I/O/ESD are separate deliverables.
// Do not synthesize the 'z' assignments into core logic: replace with GF180 pads.
module RiscayMcuChip (
  input wire reset, scl, adcMiso,
  output wire adcCsN, adcSclk,
  inout wire sda,
  inout wire [@GPIO_PAD_COUNT@-1:0] gpio
);
  wire serviceClock, watchdogClock, powerGood, serviceClockEnable, porReleased;
  wire sdaLow;
  wire [@GPIO_COUNT@-1:0] gpioOut, gpioOe;
  wire [@GPIO_COUNT@-1:0] gpioSense;
  riscay_supply_monitor supplyMonitor (.good(powerGood));
  riscay_lf_osc lf (.rst_n(porReleased), .clk(watchdogClock));
  riscay_service_osc fast (.rst_n(powerGood),
    .enable(powerGood && (reset || !porReleased || serviceClockEnable)), .clk(serviceClock));
  RiscayMcuDigital digital (.serviceClock(serviceClock), .watchdogClock(watchdogClock),
    .powerGood(powerGood), .reset(reset), .serviceClockEnable(serviceClockEnable),
    .porReleased(porReleased), .scl(scl), .sda(sda), .sdaLow(sdaLow),
    .gpioIn(gpioSense), .gpioOut(gpioOut), .gpioOe(gpioOe),
    .adcMiso(adcMiso), .adcCsN(adcCsN), .adcSclk(adcSclk));
  assign sda = sdaLow ? 1'b0 : 1'bz;
@GPIO_PAD_BINDINGS@
endmodule
