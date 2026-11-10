// SPDX-License-Identifier: Apache-2.0
// DIGITAL PROTOTYPE ONLY. Bounds are explicit testbench assumptions, not PVT
// characterization. No definition survives SYNTHESIS; physical recipes stay
// unavailable. The mutex abstracts finite resolution, not analog metastability.
`ifndef SYNTHESIS
module RiscayDesyncController(input wire reset, run, delayed, cycleGrant, pauseGrant,
    output reg clockOut=0, output wire cycleRequest, output reg pauseRequest=0);
  timeunit 1ns; timeprecision 1ps;
  assign cycleRequest = !reset && !clockOut;
  // C-element: completion of both branches is causal, not another timed wait.
  always @(reset or cycleGrant or delayed) begin
    if(reset) clockOut <= 0;
    else if(cycleGrant && !delayed) clockOut <= 1;
    else if(!cycleGrant && delayed) clockOut <= 0;
  end
  // An unresolved stop request cannot be withdrawn by a racing wake.
  always @(reset or run or pauseGrant) begin
    if(reset) pauseRequest <= 0;
    else if(!run) pauseRequest <= 1;
    else if(pauseGrant) pauseRequest <= 0;
  end
endmodule

module RiscayDesyncDelay #(parameter real MIN_NS=0, MAX_NS=0,
    parameter integer SEED=1)(input wire reset, in, output reg out=0);
  timeunit 1ns; timeprecision 1ps;
  reg [31:0] randomState=SEED;
  reg [31:0] epoch=0;
  reg [32:0] scheduled=0;
  real selected;
  initial if(MIN_NS<=0 || MAX_NS<MIN_NS) $fatal(1,"DESYNC_SIM_BOUNDS_REQUIRED");
  // Inertial digital abstraction: a changed input or POR invalidates pending
  // simulator events. The epoch is not hardware storage. POR discharge and
  // release of a physical delay chain still need a qualified implementation.
  always @(in or reset) begin
    epoch=epoch+1;
    if(reset) out<=0;
    else if(in!==out) begin
      randomState=(randomState ^ (randomState<<13));
      randomState=(randomState ^ (randomState>>17));
      randomState=(randomState ^ (randomState<<5));
      selected=MIN_NS+(MAX_NS-MIN_NS)*(real'(randomState)/4294967295.0);
      scheduled <= #(selected) {epoch,in};
    end
  end
  always @(scheduled) if(!reset && scheduled[32:1]==epoch) out<=scheduled[0];
endmodule

module RiscayDesyncMutex #(parameter real MIN_NS=0, MAX_NS=0,
    parameter integer SEED=17)(input wire reset, request0, request1,
    output reg grant0=0, grant1=0);
  timeunit 1ns; timeprecision 1ps;
  reg [31:0] randomState=SEED;
  integer epoch=0, offeredEpoch;
  real selected;
  // Epoch only cancels scheduled simulator activity across POR. It is NOT RTL
  // state and has no physical recipe or storage-area claim.
  always @(posedge reset) begin epoch=epoch+1;grant0=0;grant1=0;end
  initial begin
    if(MIN_NS<=0 || MAX_NS<MIN_NS) $fatal(1,"DESYNC_SIM_BOUNDS_REQUIRED");
    forever begin
      wait(!reset && (request0 || request1));
      offeredEpoch=epoch;
      randomState=(randomState ^ (randomState<<13));
      randomState=(randomState ^ (randomState>>17));
      randomState=(randomState ^ (randomState<<5));
      selected=MIN_NS+(MAX_NS-MIN_NS)*(real'(randomState)/4294967295.0);
      #(selected);
      if(!reset && epoch==offeredEpoch) begin
        if(request0 && request1) begin
          grant0=randomState[0];grant1=!randomState[0];
        end else begin grant0=request0;grant1=request1;end
        wait(reset || (grant0 && !request0) || (grant1 && !request1) || (!grant0 && !grant1));
        grant0=0;grant1=0;
      end
    end
  end
endmodule
`endif
