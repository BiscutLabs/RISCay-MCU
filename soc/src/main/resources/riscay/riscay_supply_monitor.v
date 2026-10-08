// SPDX-License-Identifier: Apache-2.0
// Analog power pins are implicit here; explicit vdd/vss in the SPICE macro.
// Bind to the characterized supply monitor, not a constant tie-high.
(* blackbox *) module riscay_supply_monitor(output wire good);
endmodule
