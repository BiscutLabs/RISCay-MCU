// SPDX-License-Identifier: Apache-2.0
// Required physical IP: restartable internal 10 MHz service oscillator.
// Startup <=100 us, 8..20 MHz (supports 400 kHz SCL phase minima).
// Stop low after a full final high pulse;
// no runt pulses or edges while disabled. This declaration is not analog IP.
(* blackbox *) module riscay_service_osc(input wire enable, output wire clk);
endmodule
