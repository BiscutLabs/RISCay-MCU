// SPDX-License-Identifier: Apache-2.0
// Synthesizable chip-boundary reset sequencer. No clock is needed to assert reset.
module riscay_reset_hold #(
  parameter integer HOLD_CYCLES = 100000
) (input wire clk, input wire power_good, input wire reset,
   output reg released);
  localparam integer WIDTH = $clog2(HOLD_CYCLES + 1);
  wire unsafe_supply = !power_good || reset;
  (* async_reg = "true" *) reg [1:0] qualified;
  reg [WIDTH-1:0] count;
  always @(posedge clk or posedge unsafe_supply) begin
    if(unsafe_supply) begin
      qualified <= 0; count <= 0; released <= 0;
    end else begin
      qualified <= {qualified[0], 1'b1};
      if(!qualified[1]) begin count <= 0; released <= 0; end
      else if(!released) begin
        if(count == HOLD_CYCLES-1) released <= 1;
        else count <= count + 1'b1;
      end
    end
  end
endmodule
