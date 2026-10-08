// SPDX-License-Identifier: Apache-2.0
// Digital integration contract, NOT an analog voltage/reference simulation.
module riscay_supply_monitor #(
  parameter real RELEASE_V = 3.20,
  parameter real TRIP_V = 3.09,
  parameter integer SETTLE_NS = 1000000
) (output reg good);
  timeunit 1ns; timeprecision 1ps;
  // Testbenches may drive this hierarchical real variable. No package pin.
  real supply_voltage = 3.3;
  reg settled = 0;
  initial begin
    if(TRIP_V < 3.0 || RELEASE_V <= TRIP_V || SETTLE_NS < 0)
      $fatal(1,"INVALID_SUPPLY_MONITOR_MODEL");
    // A delta-cycle assertion lets downstream asynchronous reset blocks observe
    // power-up even when the testbench never toggles its manual-reset pin.
    #0; good = 0;
    #(SETTLE_NS); settled = 1;
  end
  always @(supply_voltage or settled) begin
    if(settled) begin
      if(supply_voltage < TRIP_V) good = 0;
      else if(supply_voltage >= RELEASE_V) good = 1;
    end
  end
endmodule
