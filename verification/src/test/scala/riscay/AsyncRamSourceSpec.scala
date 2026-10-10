// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Independent slot/receipt counts; no service clock is supplied.
  * A 2 fs reaction separates testbench drives from the monitor's 1 fs snapshot;
  * all modeled control delays remain orders of magnitude larger.
  */
class AsyncRamSourceSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickRamSource(new ResetDomain("root"))
    else new riscay.bd.FourPhaseRamSource(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-ram-source-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private val resetPulse="applicationReset=1; #10000000; applicationReset=0; #20000000;"
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name RAM source: reserve before commit, selected publication, cancellation and complete return") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-source")) { _ =>
        var publications=0
        val cycles=(0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          val commit=n%4!=1
          if(commit) publications+=1
          val published=if(click) publications%2 else 1
          s"""
            wordDrained=0; reserve_bits=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible) $$fatal(1,"RAM_SOURCE_LATE_ARM");
            #300000000;
            if(!eligible || grant_bits !== ${n%2} || reserve_ack == $phase)
              $$fatal(1,"RAM_SOURCE_RESERVATION");
            repeat(3) begin #100000000;
              if(grant_req !== $phase || delivered_grant != $n || reserve_ack == $phase)
                $$fatal(1,"RAM_SOURCE_GRANT_STALL");
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
              $$fatal(1,"RAM_SOURCE_BEFORE_WORD_DRAIN");
            ${if(n%4!=0) "if(eligible) $fatal(1,\"RAM_SOURCE_RESET_REARMED\");" else ""}
            wordDrained=1;
            ${if(click) "" else """
              repeat(3) begin #300000000;
                if(reserve_ack || decision_ack) $fatal(1,"RAM_SOURCE_BEFORE_GRANT_RTZ");
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
              if(!reserve_ack) $$fatal(1,"RAM_SOURCE_RELEASED_HELD_RESERVATION");
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
            $fatal(1,"RAM_SOURCE_RECEIPT_COUNTS");
        """
      }
    }
    test(s"$name RAM source: earliest grant, commit and publication with immediate reservation reuse") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-fast")) { _ =>
        (0 until 32).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wordDrained=1; reserve_bits=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible || grant_bits !== ${n%2}) $$fatal(1,"RAM_SOURCE_FAST_ARM");
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
            $fatal(1,"RAM_SOURCE_FAST_COUNTS");
        """
      }
    }
    test(s"$name RAM source: committed retirement waits for publication with every other condition already satisfied") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-publication")) { _ =>
        (0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wordDrained=1; reserve_bits=${n%2}; reserve_req=$phase;
            wait(grant_req == $phase); #2;
            if(!eligible) $$fatal(1,"RAM_SOURCE_PUBLICATION_ARM");
            grant_ack=$phase; decision_bits=1; decision_req=$phase;
            ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
            repeat(10) begin #100000000;
              if(decision_ack == $phase || reserve_ack == $phase || idle)
                $$fatal(1,"RAM_SOURCE_PUBLICATION_REQUIRED");
            end
            publication_bits=${(n+1)%2}; publication_req=$phase;
            wait(reserve_ack == $phase && decision_ack == $phase && publication_ack == $phase); #2;
            ${if(click) "" else "reserve_req=0; decision_req=0; publication_req=0; wait(!reserve_ack && !decision_ack && !publication_ack); #2;"}
            wait(idle); #2;
          """
        }.mkString("\n")+"""
          #100000000;
          if(delivered_reserve != 16 || delivered_grant != 16 || delivered_decision != 16 || delivered_publication != 16)
            $fatal(1,"RAM_SOURCE_PUBLICATION_COUNTS");
        """
      }
    }
    test(s"$name RAM source: cancellation leaves unselected publication pending for the next committed owner") {
      AsyncTest.run(top(click),1L to 12L,fresh(name+"-unselected")) { _ =>
        s"""
          wordDrained=1; reserve_bits=0; reserve_req=1;
          wait(grant_req); #2;
          if(!eligible) $$fatal(1,"RAM_SOURCE_UNSELECTED_ARM");
          grant_ack=1; decision_bits=0; decision_req=1;
          publication_bits=1; publication_req=1;
          ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
          wait(reserve_ack && decision_ack); #2;
          if(publication_ack) $$fatal(1,"RAM_SOURCE_CANCEL_CONSUMED_PUBLICATION");
          ${if(click) "" else "reserve_req=0; decision_req=0; wait(!reserve_ack && !decision_ack); #2;"}
          #300000000;
          if(publication_ack || idle) $$fatal(1,"RAM_SOURCE_UNSELECTED_LOST");
          reserve_bits=1; reserve_req=${if(click) 0 else 1};
          wait(grant_req == ${if(click) 0 else 1}); #2;
          grant_ack=${if(click) 0 else 1}; decision_bits=1; decision_req=${if(click) 0 else 1};
          ${if(click) "" else "wait(!grant_req); #2; grant_ack=0;"}
          wait(reserve_ack == ${if(click) 0 else 1} && decision_ack == ${if(click) 0 else 1} && publication_ack); #2;
          ${if(click) "" else "reserve_req=0; decision_req=0; publication_req=0;"}
          wait(idle); #100000000;
          if(delivered_reserve != 2 || delivered_grant != 2 || delivered_decision != 2 || delivered_publication != 1)
            $$fatal(1,"RAM_SOURCE_UNSELECTED_COUNTS");
        """
      }
    }
    test(s"$name RAM source: reset during capture keeps the reservation cancellable without resetting POR phases") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-capture-reset")) { _ =>
        (0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wordDrained=1; reserve_bits=${n%2}; reserve_req=$phase;
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
            $fatal(1,"RAM_SOURCE_CAPTURE_RESET_COUNTS");
        """
      }
    }
    test(s"$name RAM source: POR cancels held reservations and committed publication debt without replay") {
      AsyncTest.run(top(click),Seq(1L,2L,7L,19L),fresh(name+"-por")) { _ =>
        (0 until 8).map { n => s"""
          wordDrained=0; reserve_bits=${n%2}; reserve_req=1;
          wait(grant_req); #2;
          if(!eligible) $$fatal(1,"RAM_SOURCE_LATE_ARM");
          #300000000;
          if(!eligible) $$fatal(1,"RAM_SOURCE_FRESH_ELIGIBILITY");
          ${if(n%2==0) "" else s"""
            grant_ack=1;
            ${if(click) "#300000000;" else "wait(!grant_req); #300000000; grant_ack=0;"}
            decision_bits=1; decision_req=1; #300000000;
            if(reserve_ack || decision_ack) $$fatal(1,"RAM_SOURCE_UNPUBLISHED_RETIREMENT");
          """}
          reset=1; reserve_req=0; decision_req=0; publication_req=0; grant_ack=0;
          #1000000000;
          if(grant_req || reserve_ack || decision_ack || publication_ack || eligible)
            $$fatal(1,"RAM_SOURCE_POR_STATE");
          reset=0; #1000000000;
          if(grant_req || eligible || !idle) $$fatal(1,"RAM_SOURCE_POR_REPLAY");
        """ }.mkString("\n")+
          "if(delivered_grant != 4) $fatal(1,\"RAM_SOURCE_POR_DELIVERY_COUNT\");"
      }
    }
  }
}
