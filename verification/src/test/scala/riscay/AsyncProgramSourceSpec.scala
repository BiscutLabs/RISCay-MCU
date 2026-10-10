// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import scala.jdk.CollectionConverters._

/** Independent slot/receipt counts; no service clock is supplied.
  * A 2 fs reaction separates testbench drives from the monitor's 1 fs snapshot;
  * all modeled control delays remain orders of magnitude larger.
  */
class AsyncProgramSourceSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickProgramSource(new ResetDomain("root"))
    else new riscay.bd.FourPhaseProgramSource(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-program-source-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def selectedSourceSkew(directory: java.nio.file.Path): Unit = {
    // Reuse the unchanged seed-1 stimulus and every monitor. Two selected primitives
    // move from the minimum to maximum of the existing 1..10 ns cell envelope.
    val base=directory.toAbsolutePath
    val node=ujson.read(Files.readString(base.resolve("export/contract.json")))("manifest")("design")
    val original=Files.readString(base.resolve("seed-1/testbench.sv"))
    val sources=Files.readAllLines(base.resolve("export/filelist.f")).asScala.filter(_.trim.nonEmpty)
      .map(s => base.resolve("export").resolve(s.trim).normalize.toString).toSeq
    for((name,ids) <- Seq(
        "publication" -> Seq("effect_ready_nb","settled_nb"),
        "stored" -> Seq("stored_retired_nb","retire_fire_nb"),
        "issue" -> Seq("stored_selection_nb","stored_fire_na"))) {
      var replay=original
      val paths=ids.map { id =>
        val primitive=node("primitives").arr.find(_("id").str == id).get
        val path="dut."+primitive("rtl_path").str.split('.').drop(1).mkString(".")
        val old=s"defparam $path.DELAY_FS=1000000;"
        val replacement=s"defparam $path.DELAY_FS=10000000;"
        require(replay.sliding(old.length).count(_ == old)==1,"PROGRAM_SOURCE_SKEW_OVERRIDE_SHAPE")
        replay=replay.replace(old,replacement); path
      }
      val out=Files.createDirectory(base.resolve("selected-skew-"+name))
      Files.writeString(out.resolve("testbench.sv"),replay)
      Files.writeString(out.resolve("delays.json"),ujson.write(ujson.Obj("base_seed"->1,
        "primitives"->ujson.Arr.from(paths),"delay_fs"->10000000,
        "other_delays_and_oracle_unchanged"->true),indent=2))
      def command(args: Seq[String],log: String): Unit = {
        val process=new ProcessBuilder(args:_*).directory(out.toFile).redirectErrorStream(true)
          .redirectOutput(out.resolve(log).toFile).start()
        if(!process.waitFor(90,java.util.concurrent.TimeUnit.SECONDS)) {
          process.destroyForcibly(); fail("PROGRAM_SOURCE_SKEW_TIMEOUT: "+out)
        }
        require(process.exitValue()==0,s"PROGRAM_SOURCE_SKEW_FAILED: $out/$log\n"+Files.readString(out.resolve(log)))
      }
      val simulator=chiselasync.testing.Simulator()
      command(Seq(simulator.iverilog,"-g2012","-s","Testbench","-o","sim.vvp")++sources++Seq("testbench.sv"),"compile.log")
      command(Seq(simulator.vvp,"sim.vvp"),"simulation.log")
      require(Files.readString(out.resolve("simulation.log")).contains("CA_TEST_PASS"),"PROGRAM_SOURCE_SKEW_NO_PASS")
    }
  }
  private val resetPulse="applicationReset=1; #10000000; applicationReset=0; #20000000;"
  test("bd program source: Stored return holds reservation ACK falling, not rising") {
    AsyncTest.run(top(false),1L to 24L,fresh("bd-stored-return")) { _ =>
      (0 until 8).map { n => s"""
        wordDrained=1; reserve_bits=1; reserve_req=1;
        wait(grant_req); #2; grant_ack=1;
        decision_bits=1; decision_req=1; publication_bits=${n%2}; publication_req=1;
        wait(!grant_req); #2; grant_ack=0;
        wait(stored_req); #2; stored_ack=1;
        wait(reserve_ack && decision_ack && publication_ack); #2;
        reserve_req=0; decision_req=0; publication_req=0;
        wait(!publication_ack); #2;
        publication_bits=${(n+1)%2};
        repeat(10) begin #100000000;
          if(!reserve_ack || idle) $$fatal(1,"PROGRAM_SOURCE_STORED_RETURN_BARRIER");
        end
        stored_ack=0;
        wait(!reserve_ack && !decision_ack && !publication_ack); #2;
        wait(idle); #2;
      """ }.mkString("\n")+"""
        #100000000;
        if(delivered_reserve != 8 || delivered_grant != 8 || delivered_decision != 8 ||
           delivered_publication != 8 || delivered_stored != 8)
          $fatal(1,"PROGRAM_SOURCE_STORED_RETURN_COUNTS");
      """
    }
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name program CPU source: reserve before commit, selected publication, cancellation and complete return") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-source")) { _ =>
        var publications=0
        val cycles=(0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          val commit=n%4!=1
          if(commit) publications+=1
          val published=if(click) publications%2 else 1
          s"""
            wordDrained=0; reserve_bits=0; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible) $$fatal(1,"PROGRAM_SOURCE_LATE_ARM");
            #300000000;
            if(!eligible || grant_bits !== 0 || reserve_ack == $phase)
              $$fatal(1,"PROGRAM_SOURCE_RESERVATION");
            repeat(3) begin #100000000;
              if(grant_req !== $phase || delivered_grant != $n || reserve_ack == $phase)
                $$fatal(1,"PROGRAM_SOURCE_GRANT_STALL");
            end
            ${if(!commit) resetPulse else ""}
            grant_ack=$phase;
            ${if(click) "#300000000;" else "wait(!grant_req); #300000000;"}
            decision_bits=${if(commit) 1 else 0}; decision_req=$phase;
            ${if(n%4==2) resetPulse else ""}
            #300000000;
            ${if(commit) s"publication_bits=${(n+1)%2}; publication_req=$published;" else ""}
            ${if(n%4==3) resetPulse+resetPulse else ""}
            #300000000;
            if(reserve_ack == $phase || decision_ack == $phase)
              $$fatal(1,"PROGRAM_SOURCE_BEFORE_WORD_DRAIN");
            ${if(n%4!=0) "if(eligible) $fatal(1,\"PROGRAM_SOURCE_RESET_REARMED\");" else ""}
            wordDrained=1;
            ${if(click) "" else """
              repeat(3) begin #300000000;
                if(reserve_ack || decision_ack) $fatal(1,"PROGRAM_SOURCE_BEFORE_GRANT_RTZ");
              end
              grant_ack=0;
            """}
            wait(decision_ack == $phase);
            ${if(commit) s"wait(publication_ack == $published);" else ""}
            wait(reserve_ack == $phase); #2;
            ${if(click) "" else s"""
              decision_req=0;
              ${if(commit) "publication_req=0;" else ""}
              #100000000;
              if(!reserve_ack) $$fatal(1,"PROGRAM_SOURCE_RELEASED_HELD_RESERVATION");
              reserve_req=0;
              wait(!reserve_ack && !decision_ack && !publication_ack); #2;
            """}
            wait(idle); #2;
          """
        }.mkString("\n")
        cycles+"""
          #100000000;
          if(delivered_grant != 16 || delivered_reserve != 16 ||
             delivered_decision != 16 || delivered_publication != 12)
            $fatal(1,"PROGRAM_SOURCE_RECEIPT_COUNTS");
        """
      }
    }
    test(s"$name program CPU source: earliest grant, commit and publication with immediate reservation reuse") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-fast")) { _ =>
        (0 until 32).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wordDrained=1; reserve_bits=0; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible || grant_bits !== 0) $$fatal(1,"PROGRAM_SOURCE_FAST_ARM");
            grant_ack=$phase;
            decision_bits=1; publication_bits=${(n+1)%2};
            decision_req=$phase; publication_req=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            wait(reserve_ack == $phase && decision_ack == $phase && publication_ack == $phase); #2;
            ${if(click) "" else """
              reserve_req=0; decision_req=0; publication_req=0;
              wait(!reserve_ack && !decision_ack && !publication_ack); #2;
            """}
          """
        }.mkString("\n")+"""
          wait(idle); #100000000;
          if(delivered_reserve != 32 || delivered_grant != 32 || delivered_decision != 32 || delivered_publication != 32)
            $fatal(1,"PROGRAM_SOURCE_FAST_COUNTS");
        """
      }
    }
    test(s"$name program CPU source: committed retirement waits for publication with every other condition already satisfied") {
      val directory=fresh(name+"-publication")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        (0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wordDrained=1; reserve_bits=0; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible) $$fatal(1,"PROGRAM_SOURCE_PUBLICATION_ARM");
            grant_ack=$phase; decision_bits=1; decision_req=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            repeat(10) begin #100000000;
              if(decision_ack == $phase || reserve_ack == $phase || idle)
                $$fatal(1,"PROGRAM_SOURCE_PUBLICATION_REQUIRED");
            end
            publication_bits=${(n+1)%2}; publication_req=$phase;
            wait(reserve_ack == $phase && decision_ack == $phase && publication_ack == $phase); #2;
            ${if(click) "" else "reserve_req=0; decision_req=0; publication_req=0; wait(!reserve_ack && !decision_ack && !publication_ack); #2;"}
            wait(idle); #2;
          """
        }.mkString("\n")+"""
          #100000000;
          if(delivered_reserve != 16 || delivered_grant != 16 || delivered_decision != 16 || delivered_publication != 16)
            $fatal(1,"PROGRAM_SOURCE_PUBLICATION_COUNTS");
        """
      }
      if(click) selectedSourceSkew(directory)
    }
    test(s"$name program CPU source: cancellation leaves unselected publication pending for the next committed owner") {
      AsyncTest.run(top(click),1L to 12L,fresh(name+"-unselected")) { _ =>
        s"""
          wordDrained=1; reserve_bits=0; reserve_req=1;
          wait(grant_req); #2;
          if(!eligible) $$fatal(1,"PROGRAM_SOURCE_UNSELECTED_ARM");
          grant_ack=1; decision_bits=0; decision_req=1;
          publication_bits=1; publication_req=1;
          ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
          wait(reserve_ack && decision_ack); #2;
          if(publication_ack) $$fatal(1,"PROGRAM_SOURCE_CANCEL_CONSUMED_PUBLICATION");
          ${if(click) "" else "reserve_req=0; decision_req=0; wait(!reserve_ack && !decision_ack); #2;"}
          #300000000;
          if(publication_ack || idle) $$fatal(1,"PROGRAM_SOURCE_UNSELECTED_LOST");
          reserve_bits=0; reserve_req=${if(click) 0 else 1};
          wait(grant_req == ${if(click) 0 else 1}); #2;
          grant_ack=${if(click) 0 else 1}; decision_bits=1; decision_req=${if(click) 0 else 1};
          ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
          wait(reserve_ack == ${if(click) 0 else 1} && decision_ack == ${if(click) 0 else 1} && publication_ack); #2;
          ${if(click) "" else "reserve_req=0; decision_req=0; publication_req=0;"}
          wait(idle); #100000000;
          if(delivered_reserve != 2 || delivered_grant != 2 || delivered_decision != 2 || delivered_publication != 1)
            $$fatal(1,"PROGRAM_SOURCE_UNSELECTED_COUNTS");
        """
      }
    }
    test(s"$name program CPU source: reset during capture keeps the reservation cancellable without resetting POR phases") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-capture-reset")) { _ =>
        (0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wordDrained=1; reserve_bits=0; reserve_req=$phase;
            #${1+n*3000000}; applicationReset=1; #10000000; applicationReset=0;
            wait(grant_req == $phase); #2;
            // An old queued reservation may arm after reset. The boundary must
            // cancel it under retained reset debt, irrespective of eligibility.
            grant_ack=$phase; decision_bits=0; decision_req=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            wait(reserve_ack == $phase && decision_ack == $phase); #2;
            ${if(click) "" else "reserve_req=0; decision_req=0; wait(!reserve_ack && !decision_ack); #2;"}
            wait(idle); #2;
          """
        }.mkString("\n")+"""
          #100000000;
          if(delivered_reserve != 16 || delivered_grant != 16 || delivered_decision != 16 || delivered_publication != 0)
            $fatal(1,"PROGRAM_SOURCE_CAPTURE_RESET_COUNTS");
        """
      }
    }
    test(s"$name program CPU source: POR cancels held reservations and committed publication debt without replay") {
      AsyncTest.run(top(click),Seq(1L,2L,7L,19L),fresh(name+"-por")) { _ =>
        (0 until 8).map { n => s"""
          wordDrained=0; reserve_bits=0; reserve_req=1;
          wait(grant_req); #2;
          if(!eligible) $$fatal(1,"PROGRAM_SOURCE_LATE_ARM");
          #300000000;
          if(!eligible) $$fatal(1,"PROGRAM_SOURCE_FRESH_ELIGIBILITY");
          ${if(n%2==0) "" else s"""
            grant_ack=1;
            ${if(click) "#300000000;" else "wait(!grant_req); #300000000; grant_ack=0;"}
            decision_bits=1; decision_req=1; #300000000;
            if(reserve_ack || decision_ack) $$fatal(1,"PROGRAM_SOURCE_UNPUBLISHED_RETIREMENT");
          """}
          reset=1; reserve_req=0; decision_req=0; publication_req=0; grant_ack=0;
          #1000000000;
          if(grant_req || reserve_ack || decision_ack || publication_ack || eligible)
            $$fatal(1,"PROGRAM_SOURCE_POR_STATE");
          reset=0; #1000000000;
          if(grant_req || eligible || !idle) $$fatal(1,"PROGRAM_SOURCE_POR_REPLAY");
        """ }.mkString("\n")+
          "if(delivered_grant != 4) $fatal(1,\"PROGRAM_SOURCE_POR_DELIVERY_COUNT\");"
      }
    }
    test(s"$name program source: independent CPU/publication/Stored histories and loader progress through reset") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-mixed")) { _ =>
        var publications=0; var stores=0
        val cycles=(0 until 32).map { n =>
          val loader=Set(1,2,5,7).contains(n%8)
          val commit=loader || n%4!=0
          val tag=if(loader) 1 else 0
          val phase=if(click) (n+1)%2 else 1
          if(commit) publications+=1
          val published=if(click) publications%2 else 1
          val oldStored=if(click) stores%2 else 0
          if(loader) stores+=1
          val storedPhase=if(click) stores%2 else 1
          s"""
            wordDrained=0; reserve_bits=$tag; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(grant_bits !== $tag || ownerLoader !== $tag) $$fatal(1,"PROGRAM_SOURCE_TAG");
            ${if(n%3!=0) resetPulse+resetPulse else ""}
            grant_ack=$phase; decision_bits=${if(commit) 1 else 0}; decision_req=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            #1000000000;
            if(stored_req !== $oldStored || decision_ack == $phase || reserve_ack == $phase)
              $$fatal(1,"PROGRAM_SOURCE_BEFORE_PUBLICATION");
            ${if(commit) s"publication_bits=${n%2}; publication_req=$published;" else ""}
            ${if(loader) s"""
              wait(stored_req == $storedPhase); #2;
              if(!stored_bits) $$fatal(1,"PROGRAM_SOURCE_STORED_TAG");
              ${resetPulse+resetPulse}
              repeat(5) begin #100000000;
                if(reserve_ack == $phase || decision_ack == $phase || publication_ack == $published)
                  $$fatal(1,"PROGRAM_SOURCE_STORED_BACKPRESSURE");
              end
              stored_ack=$storedPhase;
              ${if(click) "" else "wait(!stored_req); #2; stored_ack=0;"}
            """ else s"""
              #1000000000;
              if(stored_req !== $oldStored || delivered_stored != $stores)
                $$fatal(1,"PROGRAM_SOURCE_CPU_ISSUED_STORED");
            """}
            #300000000;
            // A completed Stored receipt keeps its independent output history
            // across application reset; it must not create a phantom next token.
            if(stored_req !== ${if(click) stores%2 else 0} || delivered_stored != $stores)
              $$fatal(1,"PROGRAM_SOURCE_STORED_HISTORY_AFTER_RESET");
            if(reserve_ack == $phase || decision_ack == $phase)
              $$fatal(1,"PROGRAM_SOURCE_WORD_DRAIN_REQUIRED");
            wordDrained=1;
            // All other inputs have settled: BD needs <=10+10+200=220 ns;
            // Click <=11+90+10+0.1+241.200001=352.300001 ns in this model.
            // Bound the external receipts without waiting for full BD RTZ.
            #1000000000;
            if(reserve_ack !== $phase || decision_ack !== $phase
               ${if(commit) s"|| publication_ack !== $published" else ""})
              $$fatal(1,"PROGRAM_SOURCE_COMMITTED_RECEIPTS_NOT_RETIRED");
            wait(reserve_ack == $phase && decision_ack == $phase); #2;
            ${if(commit) s"wait(publication_ack == $published); #2;" else ""}
            ${if(click) "" else s"""
              reserve_req=0; decision_req=0; ${if(commit) "publication_req=0;" else ""}
              wait(!reserve_ack && !decision_ack && !publication_ack); #2;
            """}
            wait(idle); #2;
          """
        }.mkString("\n")
        cycles+s"""
          #300000000;
          if(delivered_reserve != 32 || delivered_grant != 32 || delivered_decision != 32 ||
             delivered_publication != $publications || delivered_stored != $stores)
            $$fatal(1,"PROGRAM_SOURCE_MIXED_COUNTS");
        """
      }
    }
    test(s"$name program source: a committed loader cannot retire without Stored acknowledgment") {
      val directory=fresh(name+"-stored-required")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        (0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wordDrained=1; reserve_bits=1; reserve_req=$phase;
            wait(grant_req == $phase); #2; grant_ack=$phase;
            decision_bits=1; decision_req=$phase; publication_bits=${n%2}; publication_req=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            wait(stored_req == $phase); #2;
            repeat(10) begin #100000000;
              if(reserve_ack == $phase || decision_ack == $phase || publication_ack == $phase)
                $$fatal(1,"PROGRAM_SOURCE_STORED_REQUIRED");
            end
            stored_ack=$phase;
            ${if(click) "" else "wait(!stored_req); #2; stored_ack=0;"}
            wait(reserve_ack == $phase && decision_ack == $phase && publication_ack == $phase); #2;
            ${if(click) "" else "reserve_req=0; decision_req=0; publication_req=0; wait(!reserve_ack && !decision_ack && !publication_ack); #2;"}
          """
        }.mkString("\n")+"""
          wait(idle); #300000000;
          if(delivered_reserve != 16 || delivered_grant != 16 || delivered_decision != 16 ||
             delivered_publication != 16 || delivered_stored != 16)
            $fatal(1,"PROGRAM_SOURCE_STORED_COUNTS");
        """
      }
      if(click) selectedSourceSkew(directory)
    }
    test(s"$name program source: earliest loader Stored acceptance and immediate mixed source reuse") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-loader-fast")) { _ =>
        var stores=0
        val cycles=(0 until 32).map { n =>
          val loader=n%5>=2; if(loader) stores+=1
          val phase=if(click) (n+1)%2 else 1
          val sp=if(click) stores%2 else 1
          s"""
            wordDrained=1; reserve_bits=${if(loader) 1 else 0}; reserve_req=$phase;
            wait(grant_req == $phase); #2; grant_ack=$phase;
            decision_bits=1; publication_bits=${n%2}; decision_req=$phase; publication_req=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            ${if(loader) s"""
              wait(stored_req == $sp); #2; stored_ack=$sp;
              ${if(click) "" else "wait(!stored_req); #2; stored_ack=0;"}
            """ else ""}
            wait(reserve_ack == $phase && decision_ack == $phase && publication_ack == $phase); #2;
            ${if(click) "" else "reserve_req=0; decision_req=0; publication_req=0; wait(!reserve_ack && !decision_ack && !publication_ack); #2;"}
          """
        }.mkString("\n")
        cycles+s"""
          wait(idle); #100000000;
          if(delivered_reserve != 32 || delivered_grant != 32 || delivered_decision != 32 ||
             delivered_publication != 32 || delivered_stored != $stores)
            $$fatal(1,"PROGRAM_SOURCE_LOADER_FAST_COUNTS");
        """
      }
    }
  }
}
