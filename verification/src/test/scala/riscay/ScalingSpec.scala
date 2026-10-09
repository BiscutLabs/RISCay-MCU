// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class ScalingFixture(click: Boolean) extends FabricFixture(SocParameters(McuConfiguration(
  8,8,0,Vector.empty,ApplicationProfile(1,1,"scaling",Vector.empty,Vector.empty)))) {
  val target = IO(Input(UInt(32.W)))
  val consumed = IO(Output(UInt(32.W))); val valid = IO(Output(Bool()))
  val single = IO(Output(Bool())); val elapsed = IO(Output(Vec(3,UInt(32.W))))
  val start = IO(Input(Bool())); val raw = IO(Input(UInt(12.W)))
  val done = IO(Output(Vec(3,Bool()))); val values = IO(Output(Vec(3,UInt(32.W))))
  val ticks = withClockAndReset(serviceClock,reset) {
    if(click) Module(new riscay.click.ElapsedTicks(Seq(129354,83333,200000))).io
    else Module(new riscay.bd.ElapsedTicks(Seq(129354,83333,200000))).io
  }
  ticks.target := target; consumed := ticks.consumed; valid := ticks.valid
  single := ticks.single; elapsed := ticks.elapsed
  for(((n,d),i) <- Seq((25300,4095),(1000,4095),(7,1)).zipWithIndex) {
    val scaler = withClockAndReset(serviceClock,reset) {
      if(click) Module(new riscay.click.SampleScaler(n,d)).io
      else Module(new riscay.bd.SampleScaler(n,d)).io
    }
    scaler.start := start; scaler.raw := raw
    done(i) := scaler.done; values(i) := scaler.value
  }
}

class ScalingSpec extends AnyFunSuite {
  for(click <- Seq(false,true)) test(s"${if(click) "click" else "bd"}: fractional elapsed ticks match a wide integer oracle through missed ticks and count wrap; ADC scaling is exhaustive") {
    val random = new scala.util.Random(0x5353414cL)
    val deltas = Seq(1L,1L,17L,0xffffffffL,0x80000000L,1L) ++
      Seq.fill(128)(random.nextInt().toLong & 0xffffffffL) ++ Seq.fill(1000)(1L)
    ClockedSimulation.run(new ScalingFixture(click),"constant-scaling",s"""
      ${deltas.map(d => s"advance(32'h${d.toHexString});").mkString("\n")}
      // Target updates during the 32-cycle catch-up must be consumed afterwards.
      @(negedge serviceClock); target=target+100;
      repeat(4) @(negedge serviceClock);
      target=target+11;
      check_elapsed(100,0); check_elapsed(11,0);
      // Reset cancels both partial serial calculations and retained fractions.
      @(negedge serviceClock); target=target+100; raw=1234; start=1;
      repeat(4) @(negedge serviceClock);
      reset=1; start=0; target=0; #2000; reset=0; #5000;
      for(lane=0;lane<3;lane=lane+1) remainder[lane]=0;
      if(consumed || valid || done_0 || done_1 || done_2) $$fatal(1,"SCALER_RESET");
      advance(1);
      for(code=0;code<4096;code=code+1) begin
        @(negedge serviceClock); raw=code; start=1;
        @(negedge serviceClock); start=0;
        wait(done_0); #1;
        if(!done_1 || !done_2 || values_0 !== (code*25300)/4095 ||
          values_1 !== (code*1000)/4095 || values_2 !== code*7)
          $$fatal(1,"ADC_RATIONAL_SCALE code=%d values=%d %d %d",code,values_0,values_1,values_2);
        @(posedge serviceClock); #1;
        if(done_0 || done_1 || done_2) $$fatal(1,"ADC_DUPLICATE_COMPLETION");
      end
    ""","""
integer code,lane; reg [63:0] remainder[0:2]; reg [63:0] total;
initial begin remainder[0]=0; remainder[1]=0; remainder[2]=0; end
task check_elapsed(input [31:0] delta,input expectSingle);
reg [31:0] wanted[0:2]; begin
  wait(valid); #1;
  for(lane=0;lane<3;lane=lane+1) begin
    total={32'b0,delta}*(lane==0 ? 129354 : lane==1 ? 83333 : 200000)+remainder[lane];
    wanted[lane]=total/1000; remainder[lane]=total%1000;
  end
  if(elapsed_0 !== wanted[0] || elapsed_1 !== wanted[1] || elapsed_2 !== wanted[2] || single !== expectSingle)
    $fatal(1,"ELAPSED_SCALE delta=%d actual=%d %d %d expected=%d %d %d",delta,elapsed_0,elapsed_1,elapsed_2,wanted[0],wanted[1],wanted[2]);
  @(posedge serviceClock); #1;
end endtask
task advance(input [31:0] delta); begin
  @(negedge serviceClock); target=target+delta;
  check_elapsed(delta,delta==1);
  if(consumed !== target) $fatal(1,"SCALER_LOST_TARGET");
end endtask
""")
  }
}
