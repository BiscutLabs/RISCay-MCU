// SPDX-License-Identifier: Apache-2.0
// Digital timing view; nominal comes from schematic SPICE, not silicon.
module riscay_lf_osc #(
  parameter real NOMINAL_HZ = 7.7307,
  parameter integer ERROR_PPM = 0,
  parameter integer JITTER_PPM = 0,
  parameter integer STARTUP_NS = 16000000
) (
  input wire rst_n,
  output reg clk = 0
);
  timeunit 1ns; timeprecision 1ps;
  real frequency, periodNs;
  integer cycle = 0;
  initial begin
    frequency = NOMINAL_HZ * (1.0 + ERROR_PPM / 1000000.0);
    if(frequency <= 0 || JITTER_PPM < 0 || JITTER_PPM >= 1000000 || STARTUP_NS < 0)
      $fatal(1,"INVALID_OSCILLATOR_MODEL_PARAMETERS");
    forever begin
      wait(rst_n === 1'b1);
      fork : session
        begin
          #(STARTUP_NS);
          forever begin
            periodNs = (1.0e9/frequency) * (1.0 + ((cycle & 1) ? JITTER_PPM : -JITTER_PPM)/1000000.0);
            clk = 1; #(periodNs/2.0); clk = 0; #(periodNs/2.0);
            cycle = cycle + 1;
          end
        end
        begin wait(rst_n !== 1'b1); end
      join_any
      disable session;
      clk = 0; cycle = 0;
    end
  end
endmodule
