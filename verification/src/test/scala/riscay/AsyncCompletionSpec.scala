// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import scala.jdk.CollectionConverters._

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
    val fixed=if(click) Seq("request_guard"->240200001L,"request_delay"->11000000L,
      "acknowledge_guard"->240200001L,"output_guard"->240200001L) else Seq("request_guard"->11000000L)
    fixed.foreach { case(id,expected) =>
      require(cells(id)("parameters")("DELAY_FS").str.toLong == expected,"COMPLETION_FIXED_GUARD_VALUE")
      require(!overrides.contains(cells(id)("rtl_path").str),"COMPLETION_FIXED_GUARD_RANDOMIZED")
    }
    def path(id: String)= "dut."+cells(id)("rtl_path").str.split('.').drop(1).mkString(".")
    // Assert the source requests at the actual payload capture pin. Delayed
    // ready vectors are not an oracle for a newly selected, absent source.
    val capture=if(click) path("payload")+".trigger" else {
      val reply=node("children").arr.find(_("id").str == "reply").get
      val storage=reply("contract")("primitives").arr.find(_("id").str == "payload").get
      "dut."+storage("rtl_path").str.split('.').drop(1).mkString(".")+".closed"
    }
    val pendingSources=names.map { name =>
      val ready=if(click) s"(${name}_req != ${path(name+"_phase")}.q)" else s"${name}_req"
      s"if(plan_bits_$name && !$ready) $$fatal(1,\"COMPLETION_CAPTURE_SOURCE_ABSENT_$name\");"
    }.mkString("\n")
    val sourceCheck=s"""fork begin forever begin @(posedge $capture);
      if(!reset) begin
        if(plan_bits_memory && plan_bits_ram) $$fatal(1,"COMPLETION_ILLEGAL_MEMORY_PLAN");
        $pendingSources
      end
    end end join_none
    """
    if(!click) return sourceCheck
    val checks=Seq("payload","plan_phase","memory_phase","ram_phase","telemetry_phase","housekeeping_phase").map { id =>
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
    sourceCheck+s"fork $checks join_none\n"
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
  private val names=Seq("memory","ram","telemetry","housekeeping")
  private val legalMasks=(0 until 16).filter(mask => (mask&3)!=3)
  private def selectedSourceSkew(directory: java.nio.file.Path): Unit = {
    // Retain every seed-1 transaction and oracle, rotating the selected-source
    // order so the skewed source is first. Recompute native phase literals using
    // the same generator; rotating already-generated phase constants is invalid.
    // Only one primitive moves from the existing 1..10 ns minimum to maximum.
    val base=directory.toAbsolutePath
    val node=ujson.read(Files.readString(base.resolve("export/contract.json")))("manifest")("design")
    val original=Files.readString(base.resolve("seed-1/testbench.sv"))
    val sources=Files.readAllLines(base.resolve("export/filelist.f")).asScala.filter(_.trim.nonEmpty)
      .map(s => base.resolve("export").resolve(s.trim).normalize.toString).toSeq
    for(name <- names) {
      val primitive=node("primitives").arr.find(_("id").str == name+"_available_nb").get
      val path="dut."+primitive("rtl_path").str.split('.').drop(1).mkString(".")
      val old=s"defparam $path.DELAY_FS=1000000;"
      val replacement=s"defparam $path.DELAY_FS=10000000;"
      require(original.sliding(old.length).count(_ == old)==1,"COMPLETION_SKEW_OVERRIDE_SHAPE")
      val originalCampaign=absentSourceCampaign(true)
      val start=original.indexOf(originalCampaign)
      require(start>=0 && original.lastIndexOf(originalCampaign)==start,"COMPLETION_SKEW_STIMULUS_SHAPE")
      val rotated=original.replace(originalCampaign,absentSourceCampaign(true,names.indexOf(name)))
      val out=Files.createDirectory(base.resolve("selected-skew-"+name))
      Files.writeString(out.resolve("testbench.sv"),rotated.replace(old,replacement))
      Files.writeString(out.resolve("delays.json"),ujson.write(ujson.Obj("base_seed"->1,
        "primitive"->path,"delay_fs"->10000000,"first_selected_source"->name,
        "transactions"->40,"per_source_transactions"->4,"other_delays_and_oracle_unchanged"->true),indent=2))
      def command(args: Seq[String],log: String): Unit = {
        val process=new ProcessBuilder(args:_*).directory(out.toFile).redirectErrorStream(true)
          .redirectOutput(out.resolve(log).toFile).start()
        if(!process.waitFor(90,java.util.concurrent.TimeUnit.SECONDS)) {
          process.destroyForcibly(); fail("COMPLETION_SKEW_TIMEOUT: "+out)
        }
        require(process.exitValue()==0,s"COMPLETION_SKEW_FAILED: $out/$log\n"+Files.readString(out.resolve(log)))
      }
      val simulator=chiselasync.testing.Simulator()
      command(Seq(simulator.iverilog,"-g2012","-s","Testbench","-o","sim.vvp")++sources++Seq("testbench.sv"),"compile.log")
      command(Seq(simulator.vvp,"sim.vvp"),"simulation.log")
      require(Files.readString(out.resolve("simulation.log")).contains("CA_TEST_PASS"),"COMPLETION_SKEW_NO_PASS")
    }
  }
  private def campaign(click: Boolean,masks: Seq[Int]): String = {
    val phases=Array.fill(names.size)(0)
    masks.zipWithIndex.map { case(mask,n) =>
      val p=if(click) (n+1)%2 else 1
      // Repeat every legal mask in all 24 source orders. Program and RAM are
      // independent alternatives; either may join both persistent effect tokens.
      val order=names.indices.permutations.toVector((n/legalMasks.size)%24)
      val selected=names.indices.filter(i => (mask & (1<<i)) != 0)
      val expected=if((mask&2)!=0) 0x9abc0000L+n else if((mask&1)!=0) 0x12340000L+n else 0x56780000L+n
      val memoryError=(n/legalMasks.size)%2
      val ramError=1-memoryError
      val expectedError=if((mask&2)!=0) ramError else if((mask&1)!=0) memoryError else n%2
      val check=s"if(response_bits_data !== 32'h${expected.toHexString} || response_bits_error !== $expectedError) $$fatal(1,\"COMPLETION_DATA_$n\");"
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
        plan_bits_memory=${mask&1}; plan_bits_ram=${(mask>>1)&1};
        plan_bits_telemetry=${(mask>>2)&1}; plan_bits_housekeeping=${(mask>>3)&1};
        plan_bits_response_data=32'h${(0x56780000L+n).toHexString}; plan_bits_response_error=${n%2};
        memory_bits_data=32'h${(0x12340000L+n).toHexString}; memory_bits_error=$memoryError;
        ram_bits_data=32'h${(0x9abc0000L+n).toHexString}; ram_bits_error=$ramError;
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
  private def absentSourceCampaign(click: Boolean,first: Int=0): String = {
    var operation=0
    val phases=Array.fill(names.size)(0)
    def transaction(selected: Option[Int]): String = {
      operation+=1
      val p=if(click) operation%2 else 1
      val old=if(click) 1-p else 0
      val source=selected.map { i =>
        phases(i)=if(click) 1-phases(i) else 1
        val s=names(i); val phase=phases(i)
        s"""repeat(100) begin #10000000;
          if(plan_ack !== $old || response_req !== $old || ${s}_ack !== ${if(click) 1-phase else 0})
            $$fatal(1,"COMPLETION_SELECTED_SOURCE_ABSENT");
        end
        ${s}_req=$phase;
        """
      }.getOrElse("")
      val returnSource=selected.map { i =>
        val s=names(i);val phase=phases(i)
        s"wait(${s}_ack == $phase); #2; "+(if(click) "" else s"${s}_req=0; wait(!${s}_ack);")
      }.getOrElse("")
      val expected=if(selected.contains(1)) "abcdef01" else if(selected.contains(0)) "12345678" else "87654321"
      s"""
        plan_bits_memory=${if(selected.contains(0)) 1 else 0};
        plan_bits_ram=${if(selected.contains(1)) 1 else 0};
        plan_bits_telemetry=${if(selected.contains(2)) 1 else 0};
        plan_bits_housekeeping=${if(selected.contains(3)) 1 else 0};
        plan_bits_response_data=32'h87654321; memory_bits_data=32'h12345678;
        ram_bits_data=32'habcdef01;
        plan_bits_response_error=0; memory_bits_error=0; ram_bits_error=0;
        telemetry_bits=1; housekeeping_bits=1;
        #2; plan_req=$p;
        $source
        fork
          begin wait(plan_ack == $p); #2; ${if(click) "" else "plan_req=0; wait(!plan_ack);"} end
          begin $returnSource end
          begin wait(response_req == $p); #2;
            if(response_bits_data !== 32'h$expected || response_bits_error)
              $$fatal(1,"COMPLETION_SELECTED_SOURCE_RESULT");
            response_ack=$p;
            ${if(click) "#2;" else "wait(!response_req); #2; response_ack=0;"}
          end
        join
        #500000000;
      """
    }
    val body=(0 until 16).map { n =>
          // Invert the extra-local-plan cadence on alternate four-source blocks
          // so every source is tested with both plan phases, still 40 operations.
          val extraLocal=(n%2)^((n/names.size)%2)
          (0 to extraLocal).map(_ => transaction(None)).mkString+transaction(Some((n+first)%names.size))
    }.mkString
    body+s"if(delivered_response != $operation) $$fatal(1,\"COMPLETION_SELECTED_SOURCE_COUNT\");"
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native completion: a newly selected absent source cannot retire despite available payload") {
      val directory=fresh(name+"-selected-absent")
      run(click,1L to 24L,directory) { _ => absentSourceCampaign(click) }
      if(click) selectedSourceSkew(directory)
    }
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
    test(s"$name native completion: all legal selected-input masks, independent order, early completions and response stalls") {
      val masks=(0 until 24).flatMap(_ => legalMasks)
      run(click,1L to 24L,fresh(name+"-join")) { _ =>
        s"${campaign(click,masks)} if(delivered_response != ${masks.size}) $$fatal(1,\"COMPLETION_EXACTLY_ONCE\");"
      }
    }
    test(s"$name native completion: pending program and RAM tokens keep independent payloads and phase histories") {
      run(click,1L to 24L,fresh(name+"-independent-memories")) { _ =>
        val selections=Seq(Some("memory"),Some("ram"),None,Some("memory"),None,Some("ram"))
        val phases=scala.collection.mutable.Map("memory"->0,"ram"->0)
        val setup="""
          memory_bits_data=32'h12345678; memory_bits_error=1;
          ram_bits_data=32'h87654321; ram_bits_error=0;
          telemetry_bits=1; housekeeping_bits=1;
          #2; memory_req=1; ram_req=1;
        """
        val transactions=selections.zipWithIndex.map { case(selection,n) =>
          val p=if(click) (n+1)%2 else 1
          val consume=selection.map { source =>
            phases(source)=if(click) 1-phases(source) else 1
            val phase=phases(source)
            val reoffer=if(n<2) {
              val word=if(source=="memory") "a5a51234" else "5a5afedc"
              s"${source}_bits_data=32'h$word; ${source}_req=${if(click) 1-phase else 1};"
            } else ""
            s"""wait(${source}_ack == $phase); #2;
              ${if(click) "" else s"${source}_req=0; wait(!${source}_ack); #2;"}
              $reoffer
            """
          }.getOrElse("")
          val expected=selection match {
            case Some("memory") => if(n<2) "12345678" else "a5a51234"
            case Some("ram") => if(n<2) "87654321" else "5a5afedc"
            case _ => "11223344"
          }
          val untouched=Seq("memory","ram").filterNot(selection.contains).map { source =>
            s"if(${source}_ack !== ${if(click) phases(source) else 0}) $$fatal(1,\"COMPLETION_MEMORY_ALIAS_$source\");"
          }.mkString("\n")
          s"""
            plan_bits_memory=${if(selection.contains("memory")) 1 else 0};
            plan_bits_ram=${if(selection.contains("ram")) 1 else 0};
            plan_bits_telemetry=0; plan_bits_housekeeping=0;
            plan_bits_response_data=32'h11223344; plan_bits_response_error=0;
            #2; plan_req=$p;
            fork
              begin wait(plan_ack == $p); #2; ${if(click) "" else "plan_req=0; wait(!plan_ack);"} end
              begin $consume end
              begin wait(response_req == $p); #2;
                repeat(5) begin #100000000;
                  $untouched
                  if(response_bits_data !== 32'h$expected || response_bits_error !== ${if(selection.contains("memory")) 1 else 0})
                    $$fatal(1,"COMPLETION_INDEPENDENT_MEMORY_PAYLOAD");
                end
                response_ack=$p;
                ${if(click) "#2;" else "wait(!response_req); #2; response_ack=0;"}
              end
            join
            #500000000;
          """
        }.mkString("\n")
        setup+transactions+"""
          if(delivered_response != 6 || delivered_memory != 2 || delivered_ram != 2)
            $fatal(1,"COMPLETION_INDEPENDENT_MEMORY_COUNT");
        """
      }
    }
    for(sourceIndex <- names.indices) {
      val source=names(sourceIndex)
      val first=if(sourceIndex<2) "22222222" else "11111111"
      val next=if(sourceIndex<2) "33333333" else "55555555"
      val initialPayload=if(sourceIndex<2) s"${source}_bits_data=32'h22222222; ${source}_bits_error=0;" else s"${source}_bits=1;"
      val nextPayload=if(sourceIndex<2) s"${source}_bits_data=32'h33333333;" else s"${source}_bits=0;"
      test(s"$name native completion: immediate $source reuse and its unselected pending token never acknowledge twice") {
      run(click,1L to 24L,fresh(name+"-reuse-"+source)) { _ => s"""
        plan_bits_memory=0; plan_bits_ram=0; plan_bits_telemetry=0; plan_bits_housekeeping=0;
        plan_bits_$source=1;
        plan_bits_response_data=32'h11111111; plan_bits_response_error=0;
        $initialPayload
        #1000000; plan_req=1; ${source}_req=1;
        fork
          begin
            wait(${source}_ack); #2;
            ${if(click) s"$nextPayload ${source}_req=0;" else s"""
              ${source}_req=0;
              #90000000; if(!${source}_ack) $$fatal(1,"COMPLETION_RETURN_BARRIER");
              wait(!${source}_ack); #2; $nextPayload ${source}_req=1;
            """}
          end
          begin
            wait(plan_ack); #200000000;
            ${if(click) "" else "plan_req=0; wait(!plan_ack);"}
          end
        join
        repeat(5) begin #100000000;
          if(${source}_ack !== ${if(click) 1 else 0}) $$fatal(1,"COMPLETION_REUSED_SOURCE_EARLY_ACK");
          if(!response_req || response_bits_data !== 32'h$first) $$fatal(1,"COMPLETION_HELD_REPLY_CHANGED");
        end
        response_ack=1;
        ${if(click) "#100000000;" else "wait(!response_req); #100000000; response_ack=0; #100000000;"}
        // The already-present token is not selected by this plan.
        plan_bits_$source=0; plan_bits_response_data=32'h44444444;
        #1000000; plan_req=${if(click) 0 else 1};
        wait(response_req == ${if(click) 0 else 1}); #100000000;
        if(${source}_ack !== ${if(click) 1 else 0} || response_bits_data !== 32'h44444444)
          $$fatal(1,"COMPLETION_UNSELECTED_TOKEN_CONSUMED");
        wait(plan_ack == ${if(click) 0 else 1});
        ${if(click) "" else "plan_req=0; wait(!plan_ack);"}
        response_ack=${if(click) 0 else 1};
        ${if(click) "#100000000;" else "wait(!response_req); #100000000; response_ack=0; #100000000;"}
        plan_bits_$source=1; plan_bits_response_data=32'h55555555; #1000000; plan_req=1;
        wait(response_req); #100000000;
        if(response_bits_data !== 32'h$next) $$fatal(1,"COMPLETION_NEXT_TOKEN_LOST");
        wait(plan_ack); ${if(click) "" else "plan_req=0;"}
        wait(${source}_ack == ${if(click) 0 else 1});
        ${if(click) "" else s"${source}_req=0; wait(!${source}_ack); wait(!plan_ack);"}
        response_ack=1;
        ${if(click) "#100000000;" else "wait(!response_req); #100000000; response_ack=0;"}
        #1000000000;
        if(delivered_response != 3 || delivered_$source != 2) $$fatal(1,"COMPLETION_REUSE_COUNT");
      """ }
      }
    }
    test(s"$name native completion: repeated reset cancels partial joins and held replies without phase aliasing") {
      run(click,Seq(1L,7L,19L),fresh(name+"-reset")) { _ =>
        val episodes=(0 until 8).map { n =>
          val selectedMemory=if(n%4<2) "memory" else "ram"
          s"""
          plan_bits_memory=${if(selectedMemory=="memory") 1 else 0};
          plan_bits_ram=${if(selectedMemory=="ram") 1 else 0}; plan_bits_telemetry=1; plan_bits_housekeeping=1;
          plan_bits_response_data=0; plan_bits_response_error=1;
          memory_bits_data=32'hbad0feed; memory_bits_error=0; ram_bits_data=32'hfeedbaad; ram_bits_error=0;
          telemetry_bits=1; housekeeping_bits=1;
          #2; plan_req=1; ${selectedMemory}_req=1;
          ${if(n%2==0) "#300000000; if(response_req) $fatal(1,\"COMPLETION_EARLY\");" else
            "telemetry_req=1; housekeeping_req=1; wait(response_req); #300000000;"}
          reset=1; plan_req=0; memory_req=0; ram_req=0; telemetry_req=0; housekeeping_req=0; response_ack=0;
          #1000000000; reset=0; #1000000000;
          if(plan_ack || memory_ack || ram_ack || telemetry_ack || housekeeping_ack || response_req || creditReturn_req)
            $$fatal(1,"COMPLETION_RESET_REPLAY");
        """ }.mkString("\n")
        episodes+campaign(click,Seq(0,12,1,13,0,2,14,0))
      }
    }
  }
}
