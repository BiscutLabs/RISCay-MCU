// Independent actual-pin timing monitor. Stop/reset do not mask valid-rail checks.
module PinAperture #(parameter integer WIDTH=1, parameter time SETUP_FS=1000000,
  HOLD_FS=2000000, HIGH_FS=1000000, LOW_FS=1000000,
  parameter LABEL="capture", parameter [WIDTH-1:0] CHECK_MASK={WIDTH{1'b1}})
 (input wire railValid, trigger, enable, input wire [WIDTH-1:0] d);
 timeunit 1fs; timeprecision 1fs;
 time lastChange[WIDTH]; time lastRise=0, lastFall=0;
 bit seenRise=0, seenFall=0;
 integer rising[WIDTH], falling[WIDTH];
 genvar b;
 generate for(b=0;b<WIDTH;b=b+1) begin: bitMonitor
   initial begin lastChange[b]=0; rising[b]=0; falling[b]=0; end
   always @(d[b]) begin
     if(railValid && CHECK_MASK[b] && seenRise && $time-lastRise<HOLD_FS)
       $fatal(1,"A4_PIN_HOLD:%s:%0d",LABEL,b);
     lastChange[b]=$time;
     if(railValid) begin
       if(d[b]===1'b1) rising[b]=rising[b]+1;
       if(d[b]===1'b0) falling[b]=falling[b]+1;
     end
   end
   always @(posedge trigger) if(railValid && CHECK_MASK[b] && enable && $time-lastChange[b]<SETUP_FS)
     $fatal(1,"A4_PIN_SETUP:%s:%0d",LABEL,b);
 end endgenerate
 always @(posedge trigger) if(railValid && enable) begin
   if(seenFall && $time-lastFall<LOW_FS) $fatal(1,"A4_CAPTURE_LOW:%s",LABEL);
   lastRise=$time; seenRise=1;
 end
 always @(negedge trigger) if(railValid) begin
   if(seenRise && $time-lastRise<HIGH_FS) $fatal(1,"A4_CAPTURE_HIGH:%s",LABEL);
   lastFall=$time; seenFall=1;
 end
endmodule
