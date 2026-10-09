// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class ScalingFixture(click: Boolean) extends FabricFixture(SocParameters(McuConfiguration(
  8,8,0,Vector.empty,ApplicationProfile(1,1,"scaling",Vector.empty,Vector.empty)),watchdogCycles=32)) {
  val target = IO(Input(UInt(32.W)))
  val consumed = IO(Output(UInt(32.W))); val valid = IO(Output(Bool()))
  val single = IO(Output(Bool())); val elapsed = IO(Output(Vec(3,UInt(32.W))))
  val start = IO(Input(Bool())); val raw = IO(Input(UInt(12.W)))
  val sampleBusy = IO(Output(Vec(3,Bool())))
  val done = IO(Output(Vec(3,Bool()))); val values = IO(Output(Vec(3,UInt(32.W))))
  val tickBusy = IO(Output(Bool()))
  val applicationReset = IO(Output(Bool())); applicationReset := systemReset
  val ticks = if(click) {
    val m = asyncChild("tested_ticks")(d => new riscay.click.ElapsedTicks(Seq(129354,83333,200000),d))
    m.clock := serviceClock; m.io
  } else {
    val m = asyncChild("tested_ticks")(d => new riscay.bd.ElapsedTicks(Seq(129354,83333,200000),d))
    m.clock := serviceClock; m.io
  }
  ticks.target := target; consumed := ticks.consumed; valid := ticks.valid
  tickBusy := ticks.busy
  single := ticks.single; elapsed := ticks.elapsed
  for(((n,d),i) <- Seq((25300,4095),(1000,4095),(7,1)).zipWithIndex) {
    val scaler = if(click) {
      val m = asyncChild(s"tested_sample_$i")(domain => new riscay.click.SampleScaler(n,d,domain))
      m.clock := serviceClock; m.io
    } else {
      val m = asyncChild(s"tested_sample_$i")(domain => new riscay.bd.SampleScaler(n,d,domain))
      m.clock := serviceClock; m.io
    }
    scaler.start := start; scaler.raw := raw
    sampleBusy(i) := scaler.busy
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
      // Change the target after actual native handoff, not after an assumed
      // number of service edges (BD may still be returning the preceding reply).
      wait(!tickBusy); @(negedge serviceClock); oldOffer=tickOffer; target=target+100;
      wait(tickOffer != oldOffer); target=target+11;
      check_elapsed(100,0); check_elapsed(11,0);
      // Pause publication after handoff: native arithmetic must still finish.
      // New ticks make the old one-tick reply ineligible for observation credit.
      wait(!tickBusy); @(negedge serviceClock);
      oldOffer=tickOffer; oldReply=nativeTickReply; oldConsumed=consumed; target=target+1;
      wait(tickOffer != oldOffer); @(negedge serviceClock); clockEnabled=0;
      target=target+4; #5000;
      if(nativeTickReply == oldReply || consumed !== oldConsumed || valid || !tickBusy)
        $$fatal(1,"CLOCKLESS_SCALING_OR_EARLY_CONSUMPTION");
      clockEnabled=1; check_elapsed(1,0); check_elapsed(4,0);
      if(consumed !== target) $$fatal(1,"PAUSED_SCALING_LOST_TARGET");
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
      if(elapsedResets < 2 || sampleResets < 2)
        $$fatal(1,"NO_WATCHDOG_RETENTION_EXERCISE elapsed=%d sample=%d",elapsedResets,sampleResets);
    ""","""
wire tickOffer = dut.ticks_ca_child_tested_ticks.ca_child_native.command_req;
wire nativeTickReply = dut.ticks_ca_child_tested_ticks.ca_child_native.reply_req;
integer code,lane; reg oldOffer,oldReply; reg [31:0] oldConsumed;
integer elapsedResets=0, sampleResets=0;
always @(posedge applicationReset) if(!reset) begin
  if(tickBusy) elapsedResets=elapsedResets+1;
  if(sampleBusy_0 && sampleBusy_1 && sampleBusy_2) sampleResets=sampleResets+1;
end
reg [63:0] remainder[0:2]; reg [63:0] total;
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
  for(click <- Seq(false,true); half <- Seq(5,50,500000))
    test(s"${if(click) "click" else "bd"}: sample capture/publication/drain bound at maximum cell delays and ${half*2} ns clock") {
      ClockedSimulation.run(new ScalingFixture(click),"sample-bound",s"""
        referenceEnabled=0;
        for(code=0;code<4;code=code+1) begin
          wait(!sampleBusy_0 && !sampleBusy_1 && !sampleBusy_2);
          @(negedge serviceClock); raw=(code==0 ? 0 : code==1 ? 1 : code==2 ? 2048 : 4095); start=1;
          launched=$$realtime;
          @(negedge serviceClock); start=0;
          wait(done_0); #1;
          if(!done_1 || !done_2 || values_0 !== (raw*25300)/4095 ||
            values_1 !== (raw*1000)/4095 || values_2 !== raw*7) $$fatal(1,"MAX_CORNER_ARITHMETIC");
          wait(!sampleBusy_0 && !sampleBusy_1 && !sampleBusy_2);
          if($$realtime-launched > ${16L*2*half+1000}) $$fatal(1,"SAMPLE_DRAIN_BOUND");
          if(done_0 || done_1 || done_2) $$fatal(1,"DONE_DURING_DRAIN");
        end
      """, "integer code; real launched;",serviceHalfPeriodNs=half,
        maximumDelaySubtree=Some("ca_child_tested_sample"),deadlineNs=200000000L)
    }

}
