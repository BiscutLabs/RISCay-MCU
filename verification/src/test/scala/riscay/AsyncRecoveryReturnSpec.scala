// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Clockless proof identity, final-return and earliest-next-input oracles. */
class AsyncRecoveryReturnSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickPublicationSource(new ResetDomain("root"))
    else new riscay.bd.FourPhasePublicationSource(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-recovery-return-tests");Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private val reset="applicationReset=1; #350000000; applicationReset=0; #1000000;"
  private def grantReturn(click: Boolean) = if(click) "" else "wait(!grant_req); #2; grant_ack=0;"
  private def publicationReturn(click: Boolean) = if(click) "" else "publication_req=0; wait(!publication_ack); #2;"
  private def sourceReturn(click: Boolean,commit: Boolean) = if(click) "" else
    "reserve_req=0; decision_req=0;"+(if(commit) "wait(!drain_req); #2; drain_ack=0;" else "")+
      "wait(!reserve_ack && !decision_ack); #2;"

  for(click <- Seq(false,true); resetAt <- Seq("none","receipt","cleanup")) {
    val name=if(click) "click" else "bd"
    test(s"$name final recovery return: retained proof excludes early next input, reset=$resetAt") {
      val directory=fresh(name+"-"+resetAt)
      AsyncTest.run(top(click),1L to 24L,directory) { _ =>
        val node=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
        val trigger="dut."+node("primitives").arr.find(_("id").str=="eligibility").get
          .apply("rtl_path").str.split('.').drop(1).mkString(".")+".trigger"
        val stimulus=(0 until 6).map { n =>
          val proofPhase=if(click) (n+1)%2 else 1
          val nextPhase=if(click) 0 else 1
          val heldGrant=if(click) 1 else 0
          val expectedDebt=if(resetAt=="none") 0 else 1
          s"""
            $reset
            reserve_bits_recovery=1; reserve_bits_tag=1; reserve_req=1;
            wait(grant_req); #2; grant_ack=1; ${grantReturn(click)}
            decision_bits=1; decision_req=1;
            publication_bits=${n%2}; publication_req=$proofPhase;
            wait(publication_ack == $proofPhase); #2; ${publicationReturn(click)}
            wait(drain_req == $proofPhase); #2;
            #1000000000;
            if(!recoveryDebt || reserve_ack || decision_ack ||
                finalRequest !== ${if(click) n%2 else 0})
              $$fatal(1,"FINAL_RETURN_BEFORE_OLD_DRAIN");
            drain_ack=$proofPhase;
            wait(reserve_ack && decision_ack); #2;
            ${if(click) "" else """
              #1000000000;
              if(!recoveryDebt || finalRequest) $fatal(1,"FINAL_RETURN_BEFORE_ORIGINAL_RTZ");
            """}
            ${sourceReturn(click,true)}
            #1000000000;
            if(finalRequest !== $proofPhase || !recoveryDebt || !recoveryReturning || idle)
              $$fatal(1,"FINAL_RETURN_OFFER_BOUND");
            // A reopened BD latch may follow this changed payload. The old
            // proof must retain its identity independently, without a new arm.
            reserve_bits_recovery=0; reserve_bits_tag=0; reserve_req=$nextPhase;
            ${if(resetAt=="receipt") reset else ""}
            #1000000000;
            if(grant_req !== $heldGrant || !recoveryDebt || !recoveryReturning ||
                delivered_grant != ${2*n+1} || delivered_reserve != ${2*n+1})
              $$fatal(1,"FINAL_RETURN_EARLY_ADMISSION");
            ${if(resetAt=="receipt") "if(eligible) $fatal(1,\"FINAL_RETURN_STALE_REARM\");" else ""}
            finalAcknowledge=$proofPhase;
            ${if(click) "" else """
              wait(!finalRequest); #2;
              #1000000000;
              if(!recoveryDebt || grant_req || !recoveryReturning)
                $fatal(1,"FINAL_RETURN_BEFORE_ACK_RTZ");
              finalAcknowledge=0;
            """}
            ${if(resetAt!="receipt") s"""
              wait(!recoveryDebt); #2;
              if(!recoveryReturning || grant_req !== $heldGrant)
                $$fatal(1,"FINAL_RETURN_CLEANUP_BYPASSED");
              ${if(resetAt=="cleanup") """
                applicationReset=1; #20000000;
                if(eligible || !recoveryDebt) $fatal(1,"FINAL_RETURN_RESET_REVOCATION");
                #330000000; applicationReset=0; #1000000;
              """ else ""}
            """ else ""}
            #1000000000;
            if(grant_req !== $nextPhase || recoveryReturning || recoveryDebt !== $expectedDebt ||
                grant_bits_recovery || grant_bits_tag ||
                ${if(resetAt=="cleanup") "eligible !== eligibility_expected" else "!eligible"})
              $$fatal(1,"FINAL_RETURN_NEW_OWNER_BOUND");
            grant_ack=$nextPhase; ${grantReturn(click)}
            decision_bits=0; decision_req=$nextPhase;
            wait(reserve_ack == $nextPhase && decision_ack == $nextPhase); #2;
            ${sourceReturn(click,false)}
            #1000000000;
            if(!idle || recoveryDebt !== $expectedDebt ||
                delivered_grant != ${2*n+2} || delivered_reserve != ${2*n+2} ||
                delivered_decision != ${2*n+2} || delivered_publication != ${n+1} || delivered_drain != ${n+1})
              $$fatal(1,"FINAL_RETURN_COUNTS_OR_STALE_CLEAR");
          """
        }.mkString("\n")
        // Observe the actual arm edge, without driving any internal signal.
        // POR transport may admit the queued slot during reset; that slot must
        // remain ineligible after deassertion unless a new arm occurs afterward.
        s"""begin : eligibility_oracle
          reg eligibility_expected;
          eligibility_expected=0;
          fork
            forever begin
              @(posedge applicationReset or posedge $trigger);
              eligibility_expected=!applicationReset;
            end
            begin $stimulus end
          join_any
          disable fork;
        end"""
      }
    }
  }
}
