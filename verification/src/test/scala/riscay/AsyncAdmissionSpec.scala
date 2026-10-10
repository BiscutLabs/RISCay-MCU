// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Native credit tests use no service clock and independently count grants. */
class AsyncAdmissionSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickAdmission(new ResetDomain("root"))
    else new riscay.bd.FourPhaseAdmission(new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-admission-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native admission: one seed, held grant, early retirement and every return phase") {
      AsyncTest.run(top(click),1L to 24L,fresh(name+"-credit")) { _ =>
        val cycles=(0 until 16).map { n =>
          val phase=if(click) (n+1)%2 else 1
          s"""
            wait(grant_req == $phase); #100000000;
            repeat(4) begin #100000000;
              if(grant_req !== $phase || delivered_grant != $n) $$fatal(1,"ADMISSION_GRANT_STALL");
            end
            grant_ack=$phase;
            ${if(click) "#500000000;" else "wait(!grant_req); #500000000;"}
            if(grant_req !== ${if(click) phase else 0} || delivered_grant != ${n+1})
              $$fatal(1,"ADMISSION_UNEARNED_GRANT");
            ${if(click) "" else "responseIdle=0;"}
            returned_bits=0; returned_req=$phase;
            wait(returned_ack == $phase); #100000000;
            ${if(click) "" else """
              // Keep the consumed grant's ACK high. Retirement must still be
              // retained without waiting for that earlier handshake to return.
              if(grant_req) $fatal(1,"ADMISSION_BEFORE_RESPONSE_RTZ");
              returned_req=0; wait(!returned_ack); #100000000;
              grant_ack=0;
              repeat(5) begin #100000000;
                if(grant_req) $fatal(1,"ADMISSION_RESPONSE_RETURN_BARRIER");
              end
              responseIdle=1;
            """}
            #500000000;
          """
        }.mkString("\n")
        s"${if(click) "start=1;" else "responseIdle=1;"}\n"+cycles+
          "if(delivered_grant != 16 || delivered_returned != 16) $fatal(1,\"ADMISSION_CREDIT_COUNT\");"
      }
    }
    test(s"$name native admission: HALT consumes credit until reset and reset aborts held returns") {
      AsyncTest.run(top(click),Seq(1L,7L,19L),fresh(name+"-reset")) { _ =>
        (0 until 8).map { n => s"""
          ${if(click) "start=1;" else "responseIdle=1;"}
          wait(grant_req); #100000000; grant_ack=1;
          ${if(click) "#500000000;" else "wait(!grant_req); #100000000; grant_ack=0;"}
          repeat(8) begin #200000000;
            // AsyncTest delivery counters accumulate across coordinated resets.
            if(grant_req !== ${if(click) 1 else 0} || delivered_grant != ${n+1})
              $$fatal(1,"ADMISSION_HALT_REPLENISHED");
          end
          ${if(n%2==0) "" else s"""
            ${if(click) "" else "responseIdle=0;"}
            returned_req=1; wait(returned_ack); #100000000;
          """}
          reset=1; returned_req=0; grant_ack=0;
          ${if(click) "start=0;" else "responseIdle=0;"}
          #1000000000;
          if(grant_req || returned_ack) $$fatal(1,"ADMISSION_RESET_PHASE");
          reset=0; #1000000000;
          ${if(click) "if(grant_req) $fatal(1,\"ADMISSION_SEED_BEFORE_START\");" else ""}
        """ }.mkString("\n")
      }
    }
    test(s"$name native admission: reset aborts uncaptured return and an unconsumed recycled grant") {
      AsyncTest.run(top(click),Seq(3L,11L,23L),fresh(name+"-reset-transfer")) { _ =>
        (0 until 8).map { n => s"""
          ${if(click) "start=1;" else "responseIdle=1;"}
          wait(grant_req); #100000000; grant_ack=1;
          ${if(click) "#500000000;" else "wait(!grant_req); #100000000; grant_ack=0;"}
          returned_req=1;
          ${if(n%2==0) "#1; if(returned_ack) $fatal(1,\"RETURN_ALREADY_CAPTURED\");" else s"""
            wait(returned_ack); #100000000;
            ${if(click) "" else "returned_req=0; wait(!returned_ack);"}
            wait(grant_req == ${if(click) 0 else 1}); #300000000;
          """}
          reset=1; returned_req=0; grant_ack=0;
          ${if(click) "start=0;" else "responseIdle=0;"}
          #1000000000;
          if(grant_req || returned_ack) $$fatal(1,"TRANSFER_RESET_PHASE");
          reset=0; #1000000000;
          ${if(click) "start=1;" else "responseIdle=1;"}
          wait(grant_req); #100000000;
          if(delivered_grant != ${2*n+1}) $$fatal(1,"RESET_REPLAYED_OLD_CREDIT");
          grant_ack=1;
          ${if(click) "#500000000;" else "wait(!grant_req); #100000000; grant_ack=0;"}
          #1000000000;
          if(grant_req !== ${if(click) 1 else 0} || delivered_grant != ${2*n+2})
            $$fatal(1,"RESET_DUPLICATED_FRESH_CREDIT");
          reset=1; returned_req=0; grant_ack=0;
          ${if(click) "start=0;" else "responseIdle=0;"}
          #1000000000; reset=0; #1000000000;
        """ }.mkString("\n")
      }
    }
  }
}
