// SPDX-License-Identifier: Apache-2.0
// Restartable service source; schematic candidate nominally 12 MHz.
// Startup <=100 us, 8..20 MHz (supports 400 kHz SCL phase minima).
// Stop low after a full final high pulse;
// no runt pulses or edges while disabled. This declaration is not analog IP.
// Supply failure may truncate a pulse: downstream logic is asynchronously reset.
(* blackbox *) module riscay_service_osc(input wire rst_n, input wire enable, output wire clk);
endmodule
