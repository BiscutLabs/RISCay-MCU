// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite
import scala.jdk.CollectionConverters._

/** Clockless role, debt and stale-publication oracles. Service fences are separate. */
class AsyncRecoveryOwnershipSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickPublicationSource(new ResetDomain("root"))
    else new riscay.bd.FourPhasePublicationSource(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-recovery-ownership-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  // The native input is the qualified application reset. Integration tests
  // below that qualifier retain the original 7 ns raw pulses.
  private val revoke="applicationReset=1; #350000000; applicationReset=0; #1000000;"
  private def grantReturn(click: Boolean) = if(click) "" else "wait(!grant_req); #2; grant_ack=0;"
  private def publicationReturn(click: Boolean) = if(click) "" else "publication_req=0; wait(!publication_ack); #2;"
  private def sourceReturn(click: Boolean,commit: Boolean) = if(click) "" else
    "reserve_req=0; decision_req=0;"+(if(commit) "wait(!drain_req); #2; drain_ack=0;" else "")+
      "wait(!reserve_ack && !decision_ack); #2;"

  private def selectedSkew(directory: java.nio.file.Path,click: Boolean): Unit = {
    val base=directory.toAbsolutePath
    val node=ujson.read(Files.readString(base.resolve("export/contract.json")))("manifest")("design")
    val original=Files.readString(base.resolve("seed-1/testbench.sv"))
    val sources=Files.readAllLines(base.resolve("export/filelist.f")).asScala.filter(_.trim.nonEmpty)
      .map(s => base.resolve("export").resolve(s.trim).normalize.toString).toSeq
    // Keep retirement feedback at minimum while slowing each selector and clear
    // gate independently. The functional debt/count oracle is unchanged.
    val profiles=if(click) Seq(
      "selector" -> Seq("recovery_selected_na","recovery_selected_nb","recovery_selected_or","recovery_selected",
        "recovery_live_na","recovery_live_nb","recovery_live_or","recovery_live"),
      "clear" -> Seq("recovery_clear_na","recovery_clear_nb","recovery_clear_or","recovery_clear"),
      "reset" -> Seq("eligibility","debt_storage"))
    else Seq("selector" -> Seq("recovery_clear"),"clear" -> Seq("retirement","debt_storage"),
      "reset" -> Seq("eligibility","reservation_return"))
    for((name,ids) <- profiles) {
      var replay=original
      val paths=ids.map { id =>
        val primitive=node("primitives").arr.find(_("id").str == id).get
        val path="dut."+primitive("rtl_path").str.split('.').drop(1).mkString(".")
        val old=s"defparam $path.DELAY_FS=1000000;"
        require(replay.sliding(old.length).count(_ == old)==1,"RECOVERY_SKEW_OVERRIDE_SHAPE")
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
          process.destroyForcibly();fail("RECOVERY_SKEW_TIMEOUT: "+out)
        }
        require(process.exitValue()==0,s"RECOVERY_SKEW_FAILED: $out/$log\n"+Files.readString(out.resolve(log)))
      }
      val simulator=chiselasync.testing.Simulator()
      command(Seq(simulator.iverilog,"-g2012","-s","Testbench","-o","sim.vvp")++sources++Seq("testbench.sv"),"compile.log")
      command(Seq(simulator.vvp,"sim.vvp"),"simulation.log")
      require(Files.readString(out.resolve("simulation.log")).contains("CA_TEST_PASS"),"RECOVERY_SKEW_NO_PASS")
    }
  }

  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name recovery owner: CPU, cancellation, stale and fresh publications have separate debt effects") {
      val directory=fresh(name+"-roles")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        var receipts=0; var publications=0; var debt=1
        "if(!recoveryDebt) $fatal(1,\"RECOVERY_POR_DEBT\");\n"+(0 until 32).map { n =>
          val kind=n%8; val recovery=kind!=0 && kind!=4
          val commit=kind!=1; val publish=commit && kind!=2
          val stale=kind==2 || kind==5; val resetAfter=kind==7
          val phase=if(click) (n+1)%2 else 1
          if(commit) receipts+=1
          if(publish) publications+=1
          val receipt=if(click) receipts%2 else 1
          val publication=if(click) publications%2 else 1
          if(stale) debt=1
          val before=debt
          if(recovery && commit && publish && !stale) debt=0
          val after=debt
          if(resetAfter) debt=1
          s"""
            reserve_bits_recovery=${if(recovery) 1 else 0}; reserve_bits_tag=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible || ownerRecovery !== ${if(recovery) 1 else 0} ||
                grant_bits_recovery !== ${if(recovery) 1 else 0} || grant_bits_tag !== ${n%2})
              $$fatal(1,"RECOVERY_GRANT_ROLE");
            grant_ack=$phase; ${grantReturn(click)}
            ${if(stale) revoke else ""}
            decision_bits=${if(commit) 1 else 0}; decision_req=$phase;
            ${if(commit) s"""
              #1000000000;
              if(drain_req !== $receipt || drain_bits_recovery !== ${if(recovery) 1 else 0})
                $$fatal(1,"RECOVERY_DRAIN_ROLE_BOUND");
              ${if(publish) s"""
                publication_bits=${n%2}; publication_req=$publication;
                #1000000000;
                if(publication_ack !== $publication) $$fatal(1,"RECOVERY_PUBLICATION_BOUND");
                ${publicationReturn(click)}
              """ else ""}
              #1000000000;
              if(recoveryDebt !== $before || reserve_ack == $phase || decision_ack == $phase)
                $$fatal(1,"RECOVERY_CLEARED_BEFORE_DRAIN");
              drain_ack=$receipt;
            """ else ""}
            #1000000000;
            if(reserve_ack !== $phase || decision_ack !== $phase || recoveryDebt !== $after)
              $$fatal(1,"RECOVERY_RETIREMENT_DEBT expected=%0d actual=%0d",$after,recoveryDebt);
            ${if(resetAfter) revoke else ""}
            ${sourceReturn(click,commit)}
            #1000000000;
            if(!idle || recoveryDebt !== $debt) $$fatal(1,"RECOVERY_RETURN_DEBT");
            if(delivered_reserve != ${n+1} || delivered_decision != ${n+1} ||
                delivered_publication != $publications || delivered_drain != $receipts)
              $$fatal(1,"RECOVERY_ROLE_COUNTS");
          """
        }.mkString("\n")
      }
      selectedSkew(directory,click)
    }
    test(s"$name recovery owner: live recovery cannot clear without publication and all return obligations") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-required")) { _ =>
        """
          reserve_bits_recovery=1; reserve_bits_tag=1; reserve_req=1;
          wait(grant_req); #2; grant_ack=1;
        """+grantReturn(click)+"""
          decision_bits=1; decision_req=1; wait(drain_req); #2; drain_ack=1;
          #1000000000;
          if(!recoveryDebt || reserve_ack || decision_ack || idle)
            $fatal(1,"RECOVERY_CLEARED_WITHOUT_PUBLICATION");
          publication_bits=1; publication_req=1; wait(publication_ack); #2;
        """+publicationReturn(click)+"""
          #1000000000;
          if(recoveryDebt || !reserve_ack || !decision_ack) $fatal(1,"RECOVERY_FRESH_RETIREMENT");
        """+sourceReturn(click,true)+"""
          #1000000000;
          if(!idle || recoveryDebt || delivered_reserve != 1 || delivered_publication != 1 || delivered_drain != 1)
            $fatal(1,"RECOVERY_REQUIRED_COUNTS");
        """+revoke+s"""
          reserve_bits_recovery=1; reserve_bits_tag=0; reserve_req=${if(click) 0 else 1};
          wait(grant_req == ${if(click) 0 else 1}); #2;
          ${if(click) "" else "grant_ack=1; wait(!grant_req); #2;"}
          decision_bits=1; decision_req=${if(click) 0 else 1};
          publication_bits=0; publication_req=${if(click) 0 else 1};
          wait(publication_ack == ${if(click) 0 else 1}); #2; ${publicationReturn(click)}
          wait(drain_req == ${if(click) 0 else 1}); #2; drain_ack=${if(click) 0 else 1};
          #1000000000;
          if(!recoveryDebt || reserve_ack == ${if(click) 0 else 1} || decision_ack == ${if(click) 0 else 1})
            $$fatal(1,"RECOVERY_CLEARED_BEFORE_GRANT_RETURN");
          grant_ack=0;
          #1000000000;
          if(recoveryDebt || reserve_ack !== ${if(click) 0 else 1} || decision_ack !== ${if(click) 0 else 1})
            $$fatal(1,"RECOVERY_GRANT_RETURN_BOUND");
          ${sourceReturn(click,true)}
          #1000000000;
          if(!idle || recoveryDebt || delivered_reserve != 2 || delivered_publication != 2 || delivered_drain != 2)
            $$fatal(1,"RECOVERY_GRANT_RETURN_COUNTS");
        """
      }
    }
    test(s"$name recovery owner: reset before, during and after debt capture cannot be cleared by an old slot") {
      val directory=fresh(name+"-capture-reset")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        val node=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
        def pin(id: String,field: String) = "dut."+node("primitives").arr.find(_("id").str==id).get
          .apply("rtl_path").str.split('.').drop(1).mkString(".")+"."+field
        val clearDelay=pin("recovery_clear","DELAY_FS")
        val before=if(click) "negedge "+pin("recovery_clear_or","q") else "posedge "+pin("retirement","q")
        val broad=(0 until 64).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            reserve_bits_recovery=1; reserve_bits_tag=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2; grant_ack=$phase; ${grantReturn(click)}
            decision_bits=1; decision_req=$phase;
            publication_bits=${n%2}; publication_req=$phase;
            wait(publication_ack == $phase); #2; ${publicationReturn(click)}
            wait(drain_req == $phase); #2; drain_ack=$phase;
            #${1000000+n*5000000}; $revoke
            #1000000000;
            if(!recoveryDebt || eligible || reserve_ack !== $phase || decision_ack !== $phase)
              $$fatal(1,"RECOVERY_RESET_CAPTURE_STALE_CLEAR");
            ${sourceReturn(click,true)}
            #1000000000;
            if(!idle || !recoveryDebt || delivered_reserve != ${n+1} ||
                delivered_publication != ${n+1} || delivered_drain != ${n+1})
              $$fatal(1,"RECOVERY_RESET_CAPTURE_COUNTS");
          """
        }.mkString("\n")
        // An open-loop sweep can miss a narrow reset/capture overlap for a
        // particular random skew. Observe the actual upstream transition and
        // the selected model delay to place reset 100 ps before/after capture.
        // No internal signal is driven; all role, debt and count oracles remain.
        broad+(64 until 66).map { n =>
          val phase=if(click) (n+1)%2 else 1
          val placement=if(n==64) s"@($before); #($clearDelay-100000);" else
            s"@(posedge ${pin("debt_storage","trigger")}); #100000;"
          s"""
            reserve_bits_recovery=1; reserve_bits_tag=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2; grant_ack=$phase; ${grantReturn(click)}
            decision_bits=1; decision_req=$phase;
            publication_bits=${n%2}; publication_req=$phase;
            wait(publication_ack == $phase); #2; ${publicationReturn(click)}
            wait(drain_req == $phase); #2;
            fork
              begin $placement $revoke end
              begin #2; drain_ack=$phase; end
            join
            #1000000000;
            if(!recoveryDebt || eligible || reserve_ack !== $phase || decision_ack !== $phase)
              $$fatal(1,"RECOVERY_DIRECTED_RESET_CAPTURE_STALE_CLEAR");
            ${sourceReturn(click,true)}
            #1000000000;
            if(!idle || !recoveryDebt || delivered_reserve != ${n+1} ||
                delivered_publication != ${n+1} || delivered_drain != ${n+1})
              $$fatal(1,"RECOVERY_DIRECTED_RESET_CAPTURE_COUNTS");
          """
        }.mkString("\n")
      }
      selectedSkew(directory,click)
    }
    test(s"$name recovery owner: minimum-delay retirement and immediate reuse preserve clear pulses") {
      val directory=fresh(name+"-fast")
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        (0 until 32).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            $revoke
            reserve_bits_recovery=1; reserve_bits_tag=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2; grant_ack=$phase;
            decision_bits=1; decision_req=$phase;
            publication_bits=${n%2}; publication_req=$phase;
            ${grantReturn(click)}
            wait(publication_ack == $phase); #2; ${publicationReturn(click)}
            wait(drain_req == $phase); #2; drain_ack=$phase;
            wait(reserve_ack == $phase && decision_ack == $phase); #2;
            if(recoveryDebt) $$fatal(1,"RECOVERY_FAST_CLEAR_MISSING");
            ${sourceReturn(click,true)}
            wait(idle); #2;
            if(delivered_reserve != ${n+1} || delivered_publication != ${n+1} || delivered_drain != ${n+1})
              $$fatal(1,"RECOVERY_FAST_COUNTS");
          """
        }.mkString("\n")
      }
      selectedSkew(directory,click)
    }
  }
}
