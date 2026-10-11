// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import scala.jdk.CollectionConverters._

/** Independent source/grant/publication/drain counts, without a service clock.
  * Independent native receipt regression.
  */
class AsyncPublicationSourceSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickPublicationSource(new ResetDomain("root"))
    else new riscay.bd.FourPhasePublicationSource(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-publication-source-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def selectedSkew(directory: java.nio.file.Path,click: Boolean): Unit = {
    val base=directory.toAbsolutePath
    val node=ujson.read(Files.readString(base.resolve("export/contract.json")))("manifest")("design")
    val original=Files.readString(base.resolve("seed-1/testbench.sv"))
    val sources=Files.readAllLines(base.resolve("export/filelist.f")).asScala.filter(_.trim.nonEmpty)
      .map(s => base.resolve("export").resolve(s.trim).normalize.toString).toSeq
    val profiles=if(click) Seq(
      "publication" -> Seq("publication_owner_nb","publication_fire_na"),
      "drain" -> Seq("drain_owner_nb","drain_fire_na"),
      "retirement" -> Seq("retire_source_nb","retire_fire_na"))
    else Seq("publication" -> Seq("receipt_seen"),"drain" -> Seq("drain_issue","retirement"),
      "retirement" -> Seq("reservation_return","eligibility"))
    for((name,ids) <- profiles) {
      var replay=original
      val paths=ids.map { id =>
        val primitive=node("primitives").arr.find(_("id").str == id).get
        val path="dut."+primitive("rtl_path").str.split('.').drop(1).mkString(".")
        val old=s"defparam $path.DELAY_FS=1000000;"
        require(replay.sliding(old.length).count(_ == old)==1,"PUBLICATION_SKEW_OVERRIDE_SHAPE")
        replay=replay.replace(old,s"defparam $path.DELAY_FS=10000000;");path
      }
      val out=Files.createDirectory(base.resolve("selected-skew-"+name))
      Files.writeString(out.resolve("testbench.sv"),replay)
      Files.writeString(out.resolve("delays.json"),ujson.write(ujson.Obj("base_seed"->1,
        "primitives"->ujson.Arr.from(paths),"delay_fs"->10000000,"other_delays_and_oracle_unchanged"->true),indent=2))
      def command(args: Seq[String],log: String): Unit = {
        val process=new ProcessBuilder(args:_*).directory(out.toFile).redirectErrorStream(true)
          .redirectOutput(out.resolve(log).toFile).start()
        if(!process.waitFor(60,java.util.concurrent.TimeUnit.SECONDS)) {
          process.destroyForcibly();fail("PUBLICATION_SKEW_TIMEOUT: "+out)
        }
        require(process.exitValue()==0,s"PUBLICATION_SKEW_FAILED: $out/$log\n"+Files.readString(out.resolve(log)))
      }
      val simulator=chiselasync.testing.Simulator()
      command(Seq(simulator.iverilog,"-g2012","-s","Testbench","-o","sim.vvp")++sources++Seq("testbench.sv"),"compile.log")
      command(Seq(simulator.vvp,"sim.vvp"),"simulation.log")
      require(Files.readString(out.resolve("simulation.log")).contains("CA_TEST_PASS"),"PUBLICATION_SKEW_NO_PASS")
    }
  }
  private val resetPulse="applicationReset=1; #10000000; applicationReset=0; #20000000;"
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name publication source: independent commit, cancellation and receipt histories with immediate reuse") {
      val directory=fresh(name+"-mixed")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        var publications=0; var drains=0
        (0 until 24).map { n =>
          val phase=if(click) (n+1)%2 else 1
          val commit=n%5!=1 && n%5!=4
          val publish=commit && n%5!=2
          val cancelled=n%5>=2
          if(commit) drains+=1
          if(publish) publications+=1
          val publicationPhase=if(click) publications%2 else 1
          val drainPhase=if(click) drains%2 else 1
          s"""
            reserve_bits_tag=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible || grant_bits_tag !== ${n%2}) $$fatal(1,"PUBLICATION_SOURCE_GRANT_IDENTITY");
            #300000000;
            if(reserve_ack == $phase || delivered_grant != $n)
              $$fatal(1,"PUBLICATION_SOURCE_PRECOMMIT_RETIREMENT");
            grant_ack=$phase;
            ${if(click) "#300000000;" else "wait(!grant_req); #2; grant_ack=0; #300000000;"}
            if(reserve_ack == $phase || decision_ack == $phase)
              $$fatal(1,"PUBLICATION_SOURCE_BEFORE_DECISION");
            ${if(cancelled) resetPulse+"if(eligible) $fatal(1,\"PUBLICATION_SOURCE_RESET_ELIGIBILITY\");" else ""}
            decision_bits=${if(commit) 1 else 0}; decision_req=$phase;
            ${if(commit) s"""
              #1000000000;
              if(drain_req !== $drainPhase) $$fatal(1,"PUBLICATION_SOURCE_DRAIN_OFFER_BOUND");
              wait(drain_req == $drainPhase); #2;
              if(drain_bits_tag !== ${n%2}) $$fatal(1,"PUBLICATION_SOURCE_DRAIN_IDENTITY");
              ${if(publish) s"""
                publication_bits=${n%2}; publication_req=$publicationPhase;
                #1000000000;
                if(publication_ack !== $publicationPhase) $$fatal(1,"PUBLICATION_SOURCE_PUBLICATION_ACK_BOUND");
                wait(publication_ack == $publicationPhase); #2;
                ${if(click) "" else "publication_req=0; wait(!publication_ack); #2;"}
              """ else ""}
              #1000000000;
              if(reserve_ack == $phase || decision_ack == $phase)
                $$fatal(1,"PUBLICATION_SOURCE_IGNORED_DRAIN");
              if(delivered_publication != $publications || delivered_drain != ${drains-1})
                $$fatal(1,"PUBLICATION_SOURCE_RECEIPT_HISTORY");
              drain_ack=$drainPhase;
            """ else ""}
            #1000000000;
            if(reserve_ack !== $phase || decision_ack !== $phase)
              $$fatal(1,"PUBLICATION_SOURCE_RECEIPT_BOUND");
            wait(reserve_ack == $phase && decision_ack == $phase); #2;
            ${if(click) "" else s"""
              reserve_req=0; decision_req=0;
              ${if(commit) "wait(!drain_req); #2; drain_ack=0;" else ""}
              wait(!reserve_ack && !decision_ack); #2;
            """}
            #1000000000;
            if(!idle) $$fatal(1,"PUBLICATION_SOURCE_RETURN_BOUND");
            wait(idle); #2;
            if(delivered_reserve != ${n+1} || delivered_grant != ${n+1} ||
               delivered_decision != ${n+1} || delivered_publication != $publications ||
               delivered_drain != $drains)
              $$fatal(1,"PUBLICATION_SOURCE_EXACT_COUNTS");
          """
        }.mkString("\n")
      }
      selectedSkew(directory,click)
    }
    test(s"$name publication source: a live committed slot cannot retire without its actual publication") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-publication-required")) { _ =>
        """
          reserve_bits_tag=1; reserve_req=1; wait(grant_req); #2; grant_ack=1;
        """+(if(click) "#300000000;" else "wait(!grant_req); #2; grant_ack=0; #300000000;")+"""
          decision_bits=1; decision_req=1; wait(drain_req); #2; drain_ack=1;
          #1000000000;
          if(reserve_ack || decision_ack || !eligible || idle)
            $fatal(1,"PUBLICATION_SOURCE_MISSING_SELECTED_RECEIPT");
          publication_bits=1; publication_req=1; wait(publication_ack); #2;
        """+(if(click) "" else "publication_req=0; wait(!publication_ack); #2;")+"""
          wait(reserve_ack && decision_ack); #2;
        """+(if(click) "" else "reserve_req=0; decision_req=0; wait(!drain_req); #2; drain_ack=0;")+"""
          wait(idle); #2;
          if(delivered_publication != 1 || delivered_drain != 1 || delivered_reserve != 1)
            $fatal(1,"PUBLICATION_SOURCE_REQUIRED_COUNTS");
        """
      }
    }
    test(s"$name publication source: a second publication cannot be accepted into one reservation") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-duplicate")) { _ =>
        """
          reserve_bits_tag=1; reserve_req=1; wait(grant_req); #2; grant_ack=1;
        """+(if(click) "#300000000;" else "wait(!grant_req); #2; grant_ack=0; #300000000;")+"""
          decision_bits=1; decision_req=1; wait(drain_req); #2;
          publication_bits=0; publication_req=1; wait(publication_ack); #2;
        """+(if(click) "" else "publication_req=0; wait(!publication_ack); #2;")+s"""
          publication_bits=1; publication_req=${if(click) 0 else 1};
          #1000000000;
          if(publication_ack !== ${if(click) 1 else 0} || delivered_publication != 1 || reserve_ack)
            $$fatal(1,"PUBLICATION_SOURCE_DUPLICATE_ACCEPTED");
          // The deliberately invalid second producer is abandoned only by POR.
          reset=1; #1000000000;
          reserve_req=0; grant_ack=0; decision_req=0; publication_req=0; drain_ack=0;
          reset=0; #1000000000;
          if(!idle || eligible || reserve_ack || decision_ack || publication_ack || drain_req)
            $$fatal(1,"PUBLICATION_SOURCE_POR_IDLE");
        """
      }
    }
    test(s"$name publication source: reset throughout committed drain and publication capture preserves both histories") {
      val directory=fresh(name+"-capture-reset")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        // Sweep beyond Click's 241.200001 ns decision guard, the selection
        // tree, register capture and outward ACK guard. Keep drain unaccepted
        // throughout so even a late reset still belongs to this reservation.
        (0 until 72).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            reserve_bits_tag=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2; grant_ack=$phase;
            decision_bits=1; decision_req=$phase;
            publication_bits=${n%2}; publication_req=$phase;
            #${1000000+n*10000000}; applicationReset=1; #10000000; applicationReset=0;
            #20000000;
            if(eligible) $$fatal(1,"PUBLICATION_SOURCE_CAPTURE_RESET_ELIGIBILITY");
            wait(publication_ack == $phase); #2;
            ${if(click) "" else "publication_req=0; wait(!publication_ack); #2;"}
            wait(drain_req == $phase); #2;
            if(reserve_ack == $phase || decision_ack == $phase)
              $$fatal(1,"PUBLICATION_SOURCE_RESET_BYPASSED_DRAIN");
            drain_ack=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            wait(reserve_ack == $phase && decision_ack == $phase); #2;
            ${if(click) "" else "reserve_req=0; decision_req=0; wait(!drain_req); #2; drain_ack=0; wait(!reserve_ack && !decision_ack); #2;"}
            wait(idle); #2;
            if(delivered_reserve != ${n+1} || delivered_decision != ${n+1} ||
               delivered_publication != ${n+1} || delivered_drain != ${n+1})
              $$fatal(1,"PUBLICATION_SOURCE_CAPTURE_RESET_COUNTS");
          """
        }.mkString("\n")
      }
      selectedSkew(directory,click)
    }
    test(s"$name publication source: fastest committed receipts and skipped histories permit immediate reuse") {
      val directory=fresh(name+"-fast")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        var receipts=0
        (0 until 32).map { n =>
          val phase=if(click) (n+1)%2 else 1
          val commit=n%4!=1
          if(commit) receipts+=1
          val receipt=if(click) receipts%2 else 1
          s"""
            reserve_bits_tag=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2; grant_ack=$phase;
            decision_bits=${if(commit) 1 else 0}; decision_req=$phase;
            ${if(commit) s"publication_bits=${n%2}; publication_req=$receipt;" else ""}
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            ${if(commit) s"""
              wait(publication_ack == $receipt); #2;
              ${if(click) "" else "publication_req=0; wait(!publication_ack); #2;"}
              wait(drain_req == $receipt); #2; drain_ack=$receipt;
            """ else ""}
            wait(reserve_ack == $phase && decision_ack == $phase); #2;
            ${if(click) "" else s"""
              reserve_req=0; decision_req=0;
              ${if(commit) "wait(!drain_req); #2; drain_ack=0;" else ""}
              wait(!reserve_ack && !decision_ack); #2;
            """}
            wait(idle); #2;
            if(delivered_reserve != ${n+1} || delivered_decision != ${n+1} ||
               delivered_publication != $receipts || delivered_drain != $receipts)
              $$fatal(1,"PUBLICATION_SOURCE_FAST_COUNTS");
          """
        }.mkString("\n")
      }
      selectedSkew(directory,click)
    }
  }
  test("bd publication source: early drain ACK and delayed grant/receipt return cannot recycle ownership") {
    AsyncTest.run(top(false),1L to 24L,fresh("bd-return")) { _ =>
      """
        reserve_bits_tag=1; reserve_req=1; wait(grant_req); #2; grant_ack=1;
        decision_bits=1; decision_req=1;
        wait(drain_req); #2; drain_ack=1;
        publication_bits=1; publication_req=1; wait(publication_ack); #2;
        publication_req=0; wait(!publication_ack); #2;
        #1000000000;
        if(reserve_ack || decision_ack || !drain_req)
          $fatal(1,"PUBLICATION_SOURCE_GRANT_RETURN_BARRIER");
        grant_ack=0; wait(reserve_ack && decision_ack); #2;
        reserve_req=0; decision_req=0; wait(!drain_req); #2;
        #1000000000;
        if(!reserve_ack || idle) $fatal(1,"PUBLICATION_SOURCE_DRAIN_RETURN_BARRIER");
        drain_ack=0; wait(!reserve_ack && !decision_ack); #2;
        wait(idle); #2;
        if(delivered_reserve != 1 || delivered_decision != 1 || delivered_publication != 1 || delivered_drain != 1)
          $fatal(1,"PUBLICATION_SOURCE_RETURN_COUNTS");
      """
    }
  }
}
