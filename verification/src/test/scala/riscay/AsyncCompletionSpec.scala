// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Independent mask/data oracle, with no periodic clock in the fixture. */
class AsyncCompletionSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickCompletion(new ResetDomain("root"))
    else new riscay.bd.FourPhaseCompletion(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-completion-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def timingChecks(directory: java.nio.file.Path,seed: Long,click: Boolean): String = {
    val node=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    val cells=node("primitives").arr.map(p => p("id").str -> p).toMap
    val overrides=ujson.read(Files.readString(directory.resolve(s"seed-$seed/delays.json")))("cells_fs").obj
    val fixed=if(click) Seq("request_guard"->11000000L,"request_delay"->11000000L,
      "acknowledge_guard"->210200001L,"output_guard"->210200001L) else Seq("request_guard"->11000000L)
    fixed.foreach { case(id,expected) =>
      require(cells(id)("parameters")("DELAY_FS").str.toLong == expected,"COMPLETION_FIXED_GUARD_VALUE")
      require(!overrides.contains(cells(id)("rtl_path").str),"COMPLETION_FIXED_GUARD_RANDOMIZED")
    }
    if(!click) return ""
    def path(id: String)= "dut."+cells(id)("rtl_path").str.split('.').drop(1).mkString(".")
    val checks=Seq("payload","plan_phase","memory_phase","telemetry_phase","housekeeping_phase").map { id =>
      val p=path(id)
      s"""begin
        time rise=0, fall=0, changed=0;
        bit rose=0, fell=0, dataSeen=0;
        fork
          begin forever begin @(posedge $p.trigger or posedge reset);
            if(reset) begin rose=0; fell=0; dataSeen=0; end
            else begin
              if(fell && $$time-fall <= 100000) $$fatal(1,"COMPLETION_PULSE_LOW_$id");
              if(dataSeen && $$time-changed <= 100000) $$fatal(1,"COMPLETION_SETUP_$id");
              rise=$$time; rose=1;
            end
          end end
          begin forever begin @(negedge $p.trigger);
            if(!reset && rose) begin
              if($$time-rise <= 100000) $$fatal(1,"COMPLETION_PULSE_HIGH_$id");
              fall=$$time; fell=1;
            end
          end end
          begin forever begin @($p.d);
            if(!reset) begin
              if(rose && $$time-rise <= 100000) $$fatal(1,"COMPLETION_HOLD_$id");
              changed=$$time; dataSeen=1;
            end
          end end
        join
      end"""
    }.mkString("\n")
    s"fork $checks join_none\n"
  }
  private def run(click: Boolean,seeds: Seq[Long],directory: java.nio.file.Path)
      (body: AsyncTest.Context => String): Unit = {
    AsyncTest.run(top(click),seeds,directory) { c => timingChecks(directory,c.seed,click)+s"""
      // Explicit native retirement consumer for this standalone join fixture.
      // Integrated admission tests independently stall and reset its real owner.
      fork begin forever begin
        wait(creditReturn_req != creditReturn_ack); #3000000;
        creditReturn_ack=creditReturn_req;
      end end join_none
      """+body(c) }
  }
  private val names=Seq("memory","telemetry","housekeeping")
  private def campaign(click: Boolean,masks: Seq[Int]): String = {
    val phases=Array.fill(3)(0)
    masks.zipWithIndex.map { case(mask,n) =>
      val p=if(click) (n+1)%2 else 1
      // The outer campaign repeats all eight masks six times. Advance the
      // permutation per group, so each fixed mask sees all six orders.
      val order=names.indices.permutations.toVector((n/8)%6)
      val selected=names.indices.filter(i => (mask & (1<<i)) != 0)
      val expected=if((mask&1)!=0) 0x12340000L+n else 0x56780000L+n
      val memoryError=(n/8)%2
      val check=s"if(response_bits_data !== 32'h${expected.toHexString} || response_bits_error !== ${if((mask&1)!=0) memoryError else n%2}) $$fatal(1,\"COMPLETION_DATA_$n\");"
      val inputs=selected.map { i =>
        phases(i)=if(click) 1-phases(i) else 1
        val phase=phases(i); val name=names(i)
        val delay=(order.indexOf(i)+1)*130000000L
        s"""begin
          #$delay; ${name}_req=$phase; wait(${name}_ack == $phase); #2;
          ${if(click) "" else s"#${(i+1)*17000000}; ${name}_req=0; wait(!${name}_ack);"}
        end"""
      }.mkString("\n")
      s"""
        plan_bits_memory=${mask&1}; plan_bits_telemetry=${(mask>>1)&1}; plan_bits_housekeeping=${(mask>>2)&1};
        plan_bits_response_data=32'h${(0x56780000L+n).toHexString}; plan_bits_response_error=${n%2};
        memory_bits_data=32'h${(0x12340000L+n).toHexString}; memory_bits_error=$memoryError;
        telemetry_bits=1; housekeeping_bits=1;
        fork
          begin #${if(n%2==0) 700000000 else 2}; plan_req=$p; wait(plan_ack == $p); #2;
            ${if(click) "" else "plan_req=0; wait(!plan_ack);"}
          end
          $inputs
          begin wait(response_req == $p); #2; $check
            repeat(5) begin #210000000; $check end
            response_ack=$p;
            ${if(click) "#2;" else "wait(!response_req); #130000000; response_ack=0;"}
          end
        join
        #300000000;
      """
    }.mkString("\n")
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native completion: retained retirement backpressure prevents response overwrite") {
      val directory=fresh(name+"-credit-stall")
      AsyncTest.run(top(click),1L to 24L,directory) { c => timingChecks(directory,c.seed,click)+s"""
        plan_bits_response_data=32'h12345678; plan_req=1;
        wait(plan_ack); #2; ${if(click) "" else "plan_req=0; wait(!plan_ack); #2;"}
        wait(response_req); #300000000; response_ack=1;
        wait(creditReturn_req);
        plan_bits_response_data=32'h87654321; #100000000;
        plan_req=${if(click) 0 else 1};
        repeat(8) begin #100000000;
          if(!response_req || response_bits_data !== 32'h12345678 || creditReturn_ack)
            $$fatal(1,"COMPLETION_IGNORED_CREDIT_BACKPRESSURE");
          if(plan_ack !== ${if(click) 1 else 0}) $$fatal(1,"COMPLETION_PLAN_REACCEPTED_EARLY");
        end
        creditReturn_ack=1;
        ${if(click) "" else "wait(!response_req); #100000000; response_ack=0; wait(!creditReturn_req); #2; creditReturn_ack=0;"}
        wait(response_req == ${if(click) 0 else 1}); #300000000;
        if(response_bits_data !== 32'h87654321) $$fatal(1,"COMPLETION_RETIRED_NEXT_DATA");
        wait(plan_ack == ${if(click) 0 else 1}); #2;
        ${if(click) "" else "plan_req=0; wait(!plan_ack); #2;"}
        response_ack=${if(click) 0 else 1};
        wait(creditReturn_req == ${if(click) 0 else 1}); #2; creditReturn_ack=${if(click) 0 else 1};
        ${if(click) "#100000000;" else "wait(!response_req); #2; response_ack=0; wait(!creditReturn_req); #2; creditReturn_ack=0;"}
        #1000000000;
        if(delivered_response != 2 || delivered_creditReturn != 2) $$fatal(1,"COMPLETION_CREDIT_COUNT");
      """ }
    }
    test(s"$name native completion: all selected-input masks, independent order, early completions and response stalls") {
      val masks=(0 until 6).flatMap(_ => 0 until 8)
      run(click,1L to 24L,fresh(name+"-join")) { _ =>
        s"${campaign(click,masks)} if(delivered_response != ${masks.size}) $$fatal(1,\"COMPLETION_EXACTLY_ONCE\");"
      }
    }
    test(s"$name native completion: immediate source reuse and an unselected pending completion never acknowledge twice") {
      run(click,1L to 24L,fresh(name+"-reuse")) { _ => s"""
        plan_bits_memory=1; plan_bits_telemetry=0; plan_bits_housekeeping=0;
        plan_bits_response_data=32'h11111111; plan_bits_response_error=0;
        memory_bits_data=32'h22222222; memory_bits_error=0;
        #1000000; plan_req=1; memory_req=1;
        fork
          begin
            wait(memory_ack); #2;
            ${if(click) "memory_bits_data=32'h33333333; memory_req=0;" else """
              memory_req=0;
              #90000000; if(!memory_ack) $fatal(1,"COMPLETION_RETURN_BARRIER");
              wait(!memory_ack); #2; memory_bits_data=32'h33333333; memory_req=1;
            """}
          end
          begin
            wait(plan_ack); #200000000;
            ${if(click) "" else "plan_req=0; wait(!plan_ack);"}
          end
        join
        repeat(5) begin #100000000;
          if(memory_ack !== ${if(click) 1 else 0}) $$fatal(1,"COMPLETION_REUSED_SOURCE_EARLY_ACK");
          if(!response_req || response_bits_data !== 32'h22222222) $$fatal(1,"COMPLETION_HELD_REPLY_CHANGED");
        end
        response_ack=1;
        ${if(click) "#100000000;" else "wait(!response_req); #100000000; response_ack=0; #100000000;"}
        // The already-present memory token is not selected by this plan.
        plan_bits_memory=0; plan_bits_response_data=32'h44444444;
        #1000000; plan_req=${if(click) 0 else 1};
        wait(response_req == ${if(click) 0 else 1}); #100000000;
        if(memory_ack !== ${if(click) 1 else 0} || response_bits_data !== 32'h44444444)
          $$fatal(1,"COMPLETION_UNSELECTED_TOKEN_CONSUMED");
        wait(plan_ack == ${if(click) 0 else 1});
        ${if(click) "" else "plan_req=0; wait(!plan_ack);"}
        response_ack=${if(click) 0 else 1};
        ${if(click) "#100000000;" else "wait(!response_req); #100000000; response_ack=0; #100000000;"}
        plan_bits_memory=1; #1000000; plan_req=1;
        wait(response_req); #100000000;
        if(response_bits_data !== 32'h33333333) $$fatal(1,"COMPLETION_NEXT_TOKEN_LOST");
        wait(plan_ack); ${if(click) "" else "plan_req=0;"}
        wait(memory_ack == ${if(click) 0 else 1});
        ${if(click) "" else "memory_req=0; wait(!memory_ack); wait(!plan_ack);"}
        response_ack=1;
        ${if(click) "#100000000;" else "wait(!response_req); #100000000; response_ack=0;"}
        #1000000000;
        if(delivered_response != 3 || delivered_memory != 2) $$fatal(1,"COMPLETION_REUSE_COUNT");
      """ }
    }
    test(s"$name native completion: repeated reset cancels partial joins and held replies without phase aliasing") {
      run(click,Seq(1L,7L,19L),fresh(name+"-reset")) { _ =>
        val episodes=(0 until 8).map { n => s"""
          plan_bits_memory=1; plan_bits_telemetry=1; plan_bits_housekeeping=1;
          plan_bits_response_data=0; plan_bits_response_error=1;
          memory_bits_data=32'hbad0feed; memory_bits_error=0; telemetry_bits=1; housekeeping_bits=1;
          #2; plan_req=1; memory_req=1;
          ${if(n%2==0) "#300000000; if(response_req) $fatal(1,\"COMPLETION_EARLY\");" else
            "telemetry_req=1; housekeeping_req=1; wait(response_req); #300000000;"}
          reset=1; plan_req=0; memory_req=0; telemetry_req=0; housekeeping_req=0; response_ack=0;
          #1000000000; reset=0; #1000000000;
          if(plan_ack || memory_ack || telemetry_ack || housekeeping_ack || response_req || creditReturn_req)
            $$fatal(1,"COMPLETION_RESET_REPLAY");
        """ }.mkString("\n")
        episodes+campaign(click,Seq(0,6,1,7,0))
      }
    }
  }
}
