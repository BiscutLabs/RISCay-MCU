// SPDX-License-Identifier: Apache-2.0
// Executable interface requirements, NOT a GF180 analog implementation.
module riscay_service_osc #(
  parameter real NOMINAL_HZ = 12000000.0,
  parameter integer STARTUP_NS = 100000
) (input wire rst_n, input wire enable, output reg clk = 0);
  timeunit 1ns; timeprecision 1ps;
  real halfPeriod;
  initial begin
    if(NOMINAL_HZ < 8000000 || NOMINAL_HZ > 20000000 || STARTUP_NS < 0 || STARTUP_NS > 100000)
      $fatal(1,"INVALID_SERVICE_OSCILLATOR_MODEL");
    halfPeriod = 5.0e8 / NOMINAL_HZ;
    forever begin
      wait(enable === 1'b1 && rst_n === 1'b1);
      fork : session
        begin
          #(STARTUP_NS);
          forever begin clk = 1; #(halfPeriod); clk = 0; #(halfPeriod); end
        end
        begin
          wait(enable !== 1'b1);
          if(clk === 1'b1) @(negedge clk);
        end
        begin
          wait(rst_n !== 1'b1);
        end
      join_any
      disable session;
      clk = 0;
    end
  end
endmodule
