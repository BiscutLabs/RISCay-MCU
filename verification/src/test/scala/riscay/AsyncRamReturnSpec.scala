// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite

/** Independent POR capture/publication and application cancellation oracles.
  * Raw reset-boundary response/receipt ports have complete native monitors;
  * library monitors remain enabled for both ordinary POR channels.
  */
class AsyncRamReturnSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickRamReturn(new ResetDomain("root"))
    else new riscay.bd.FourPhaseRamReturn(new ResetDomain("root"))
  private def fresh(label: String) = {
    val root=Paths.get("build/async-ram-return-tests");Files.createDirectories(root)
    Files.createTempDirectory(root,label)
  }
  private def phase(click: Boolean,n: Int)=if(click) n%2 else 1
  private def send(click: Boolean,n: Int,data: Long): String = s"""
    word_bits=32'h${java.lang.Long.toHexString(data)}; #2; word_req=${phase(click,n)};
    wait(word_ack === ${phase(click,n)}); #2;
    ${if(click) "" else "word_req=0; wait(!word_ack); #2;"}
  """
  private def publication(click: Boolean,n: Int,data: Long,stall: Long): String = s"""
    wait(publication_req === ${phase(click,n)}); #$stall;
    if(publication_bits !== ${data&1}) $$fatal(1,"RAM_PUBLICATION_IDENTITY");
    publication_ack=${phase(click,n)}; #2;
    ${if(click) "" else "wait(!publication_req); #2; publication_ack=0; #2;"}
  """
  private def receipt(click: Boolean,n: Int,stall: Long): String = s"""
    wait(captureRequest === ${phase(click,n)}); #$stall;
    captureAcknowledge=${phase(click,n)}; #2;
    ${if(click) "" else "wait(!captureRequest); #2; captureAcknowledge=0; #2;"}
  """
  private def response(click: Boolean,data: Long,stall: Long): String = s"""
    wait(${if(click) "response_req !== response_ack" else "response_req"}); #$stall;
    if(response_bits_data !== 32'h${java.lang.Long.toHexString(data)} || response_bits_error)
      $$fatal(1,"RAM_RESPONSE_PAYLOAD");
    response_ack=response_req; #2;
    ${if(click) "" else "wait(!response_req); #2; response_ack=0; #2;"}
  """
  // After every externally held branch has returned, the longest modeled
  // cleanup cone is below 750 ns. One microsecond is a conservative digital
  // bound, independent of the global simulator deadline.
  private val settled="""
    fork
      begin wait(idle); end
      begin #1000000000;if(!idle) $fatal(1,"RAM_RETURN_CLEANUP_BOUND"); end
    join_any
    disable fork;
  """
  private def monitored(click: Boolean,body: String): String = {
    val appMonitor=if(click) """
      if(applicationReset) begin app_req_old=0;app_ack_old=0; end
      else begin
        if((^{response_req,response_ack}) === 1'bx) $fatal(1,"RAM_APP_UNKNOWN_HANDSHAKE");
        if(response_req != app_req_old) begin
          if(app_req_old != app_ack_old || response_ack != app_ack_old)
            $fatal(1,"RAM_APP_PHASE_ORDER");
          if((^{response_bits_data,response_bits_error}) === 1'bx) $fatal(1,"RAM_APP_UNKNOWN_PAYLOAD");
          app_held={response_bits_error,response_bits_data};app_offers=app_offers+1;
        end
        if(response_ack != app_ack_old) begin
          if(app_req_old == app_ack_old || response_req != app_req_old || response_ack != response_req)
            $fatal(1,"RAM_APP_ACK_ORDER");
          app_delivered=app_delivered+1;
        end
        if(response_req != response_ack && {response_bits_error,response_bits_data} !== app_held)
          $fatal(1,"RAM_APP_DATA_HOLD");
        app_req_old=response_req;app_ack_old=response_ack;
      end
    """ else """
      if(applicationReset) app_state=0;
      else begin
        if((^{response_req,response_ack}) === 1'bx) $fatal(1,"RAM_APP_UNKNOWN_HANDSHAKE");
        if({response_req,response_ack} != app_state) begin
          case(app_state)
            0: if({response_req,response_ack} != 2) $fatal(1,"RAM_APP_REQ_ORDER");
            2: if({response_req,response_ack} != 3) $fatal(1,"RAM_APP_ACK_ORDER");
            3: if({response_req,response_ack} != 1) $fatal(1,"RAM_APP_REQ_RETURN");
            1: if({response_req,response_ack} != 0) $fatal(1,"RAM_APP_ACK_RETURN");
          endcase
        end
        if(app_state==0 && response_req) begin
          if((^{response_bits_data,response_bits_error}) === 1'bx) $fatal(1,"RAM_APP_UNKNOWN_PAYLOAD");
          app_held={response_bits_error,response_bits_data};app_offers=app_offers+1;
        end
        if(app_state==2 && {response_req,response_ack}==3) app_delivered=app_delivered+1;
        if({response_req,response_ack}!=0 && app_state!=0 && {response_bits_error,response_bits_data} !== app_held)
          $fatal(1,"RAM_APP_DATA_HOLD");
        app_state={response_req,response_ack};
      end
    """
    val receiptMonitor=if(click) """
      if((^{captureRequest,captureAcknowledge}) === 1'bx) $fatal(1,"RAM_CAPTURE_UNKNOWN");
      if(captureRequest != receipt_req_old && (receipt_req_old != receipt_ack_old || captureAcknowledge != receipt_ack_old))
        $fatal(1,"RAM_CAPTURE_PHASE_ORDER");
      if(captureAcknowledge != receipt_ack_old) begin
        if(receipt_req_old==receipt_ack_old || captureRequest!=receipt_req_old || captureAcknowledge!=captureRequest)
          $fatal(1,"RAM_CAPTURE_ACK_ORDER");
        receipt_delivered=receipt_delivered+1;
      end
      receipt_req_old=captureRequest;receipt_ack_old=captureAcknowledge;
    """ else """
      if((^{captureRequest,captureAcknowledge}) === 1'bx) $fatal(1,"RAM_CAPTURE_UNKNOWN");
      if({captureRequest,captureAcknowledge} != receipt_state) begin
        case(receipt_state)
          0: if({captureRequest,captureAcknowledge}!=2) $fatal(1,"RAM_CAPTURE_REQ_ORDER");
          2: if({captureRequest,captureAcknowledge}!=3) $fatal(1,"RAM_CAPTURE_ACK_ORDER");
          3: if({captureRequest,captureAcknowledge}!=1) $fatal(1,"RAM_CAPTURE_REQ_RETURN");
          1: if({captureRequest,captureAcknowledge}!=0) $fatal(1,"RAM_CAPTURE_ACK_RETURN");
        endcase
      end
      if(receipt_state==2 && {captureRequest,captureAcknowledge}==3) receipt_delivered=receipt_delivered+1;
      receipt_state={captureRequest,captureAcknowledge};
    """
    s"""begin : native_return_test
      reg app_req_old=0,app_ack_old=0,receipt_req_old=0,receipt_ack_old=0;
      reg [1:0] app_state=0,receipt_state=0;
      reg [32:0] app_held;
      integer app_delivered=0,app_offers=0,receipt_delivered=0;
      fork
        forever begin
          @(response_req or response_ack or response_bits_data or response_bits_error or applicationReset); #1;
          $appMonitor
        end
        forever begin
          @(captureRequest or captureAcknowledge); #1;
          $receiptMonitor
        end
        forever begin
          @(posedge applicationReset); #250000000;
          if(response_req || response_ack) $$fatal(1,"RAM_RESET_SETTLEMENT");
        end
        begin $body end
      join_any
      disable fork;
    end"""
  }
  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native RAM word capture and independent publication/receipt/application stalls") {
      val dir=fresh(name+"-stalls")
      val words=(0 until 12).map(i => (0x1937a201L+0x1000bL*i)&0xffffffffL)
      AsyncTest.run(top(click),1L to 24L,dir) { _ => monitored(click,s"""
        eligible=1;
        fork
          begin ${words.zipWithIndex.map { case(d,i) => send(click,i+1,d) }.mkString("\n")} end
          begin ${words.zipWithIndex.map { case(d,i) => publication(click,i+1,d,if(i%3==0) 1300000000L else 20000000L) }.mkString("\n")} end
          begin ${words.indices.map(i => receipt(click,i+1,if(i%3==1) 1100000000L else 30000000L)).mkString("\n")} end
          begin ${words.zipWithIndex.map { case(d,i) => response(click,d,if(i%3==2) 1700000000L else 40000000L) }.mkString("\n")} end
        join
        $settled #1000000000;
        if(delivered_word!=12 || delivered_publication!=12 || receipt_delivered!=12 || app_delivered!=12 || app_offers!=12)
          $$fatal(1,"RAM_RETURN_COUNTS");
      """) }
    }
    test(s"$name ineligible words preserve POR effects and independent application phase history") {
      val dir=fresh(name+"-cancel")
      val words=(0 until 10).map(i => (0x819203a7L+17*i)&0xffffffffL)
      AsyncTest.run(top(click),1L to 24L,dir) { _ => monitored(click,words.zipWithIndex.map { case(d,i) =>
        val live=i%3!=1
        s"""
          wait(idle); eligible=${if(live) 1 else 0}; #100000000;
          fork
            begin ${send(click,i+1,d)} word_bits=32'hdeadbeef;eligible=${if(live) 0 else 1}; end
            begin ${publication(click,i+1,d,600000000L)} end
            begin ${receipt(click,i+1,800000000L)} end
            begin ${if(live) response(click,d,120000000L) else "#1200000000;if(response_req!==response_ack) $fatal(1,\"RAM_CANCEL_REVIVED_PRESENTATION\");"} end
          join
          $settled #100000000;
          if(delivered_word!=${i+1} || delivered_publication!=${i+1} || receipt_delivered!=${i+1} ||
            app_delivered!=${(0 to i).count(_%3!=1)} || app_offers!=${(0 to i).count(_%3!=1)})
            $$fatal(1,"RAM_CANCEL_COUNTS_OR_STALE_PHASE");
        """
      }.mkString("\n")) }
    }
    test(s"$name bounded native offers after accepted word with independently stalled receivers") {
      val dir=fresh(name+"-offer-bound")
      AsyncTest.run(top(click),1L to 24L,dir) { _ => monitored(click,(0 until 4).map { i =>
        val live=i!=1
        val data=0x9271ac53L+i
        s"""
          wait(idle);eligible=${if(live) 1 else 0};#100000000;
          ${send(click,i+1,data)}
          // All receivers retain their old ACK. This bounds production of each
          // offer, independent of acknowledgment timing and the global deadline.
          #800000000;
          if(publication_req!==${phase(click,i+1)} || captureRequest!==${phase(click,i+1)})
            $$fatal(1,"RAM_NATIVE_OFFER_BOUND");
          if(${if(live) (if(click) "response_req===response_ack" else "!response_req") else "response_req!==response_ack"})
            $$fatal(1,"RAM_APPLICATION_OFFER_BOUND");
          if(presentationSettled!==${if(live) 0 else 1})
            $$fatal(1,"RAM_PRESENTATION_SETTLEMENT_IDENTITY");
          if(publication_bits!==${data&1} || response_bits_data!==32'h${java.lang.Long.toHexString(data)} || response_bits_error)
            $$fatal(1,"RAM_BOUNDED_OFFER_PAYLOAD");
          fork
            begin ${publication(click,i+1,data,20000000L)} end
            begin ${receipt(click,i+1,30000000L)} end
            begin ${if(live) response(click,data,40000000L) else "#1;"} end
          join
          $settled
        """
      }.mkString("\n")+"""
        if(delivered_word!=4 || delivered_publication!=4 || receipt_delivered!=4 || app_delivered!=3 || app_offers!=3)
          $fatal(1,"RAM_BOUNDED_OFFER_COUNTS");
      """) }
    }
    if(!click) for(held <- Seq("input","publication","receipt","application")) {
      test(s"bd holds ownership and payload through $held full return") {
        val dir=fresh("bd-full-return-"+held)
        val check="""#1000000000;
          if(idle || delivered_word!=1 || response_bits_data!==32'h13ac57b9 || publication_bits!==1'b1)
            $fatal(1,"RAM_FULL_RETURN_EARLY_REUSE");
        """
        val input=if(held=="input") s"""
          word_bits=32'h13ac57b9;word_req=1;wait(word_ack);#2;
          $check
          word_req=0;wait(!word_ack);#2;
        """ else send(false,1,0x13ac57b9L)
        val pub=if(held=="publication") s"""
          wait(publication_req);#20000000;publication_ack=1;wait(!publication_req);#2;
          $check
          publication_ack=0;#2;
        """ else publication(false,1,0x13ac57b9L,20000000L)
        val capture=if(held=="receipt") s"""
          wait(captureRequest);#30000000;captureAcknowledge=1;wait(!captureRequest);#2;
          $check
          captureAcknowledge=0;#2;
        """ else receipt(false,1,30000000L)
        val app=if(held=="application") s"""
          wait(response_req);#40000000;
          if(response_bits_data!==32'h13ac57b9 || response_bits_error) $$fatal(1,"RAM_RESPONSE_PAYLOAD");
          response_ack=1;wait(!response_req);#2;
          $check
          response_ack=0;#2;
        """ else response(false,0x13ac57b9L,40000000L)
        AsyncTest.run(top(false),1L to 24L,dir) { _ => monitored(false,s"""
          eligible=1;
          fork
            begin $input ${send(false,2,0xeca36842L)} end
            begin $pub ${publication(false,2,0xeca36842L,20000000L)} end
            begin $capture ${receipt(false,2,30000000L)} end
            begin $app ${response(false,0xeca36842L,40000000L)} end
          join
          $settled#1000000000;
          if(delivered_word!=2 || delivered_publication!=2 || receipt_delivered!=2 || app_delivered!=2 || app_offers!=2)
            $$fatal(1,"RAM_FULL_RETURN_COUNTS");
        """) }
      }
    }
    for(resetAt <- Seq("held","arm","issue","offered","ack","cleanup","repeated","release_arm","release_issue","receipt_hold");
        priorWords <- (if(click) Seq(1,2) else Seq(1))) {
      test(s"$name application reset at $resetAt after $priorWords words preserves POR RAM capture/publication") {
        val dir=fresh(name+"-reset-"+resetAt+"-"+priorWords)
        AsyncTest.run(top(click),1L to 24L,dir) { _ =>
          val node=ujson.read(Files.readString(dir.resolve("export/contract.json")))("manifest")("design")
          def pin(id: String,port: String): String = "dut."+node("primitives").arr.find(_("id").str==id).get
            .apply("rtl_path").str.split('.').drop(1).mkString(".")+"."+port
          val arm=pin(if(click) "request_guard" else "pending","q")
          val issue=if(click) pin("request_delay","q") else pin("issued","q")
          val finish=if(click) pin("completed_phase","trigger") else pin("released","q")
          val middleDelivered=if(Set("ack","cleanup")(resetAt)) 1 else 0
          val middleOffered=if(Set("offered","ack","cleanup")(resetAt)) 1 else 0
          val before=resetAt match {
            case "held" => ""
            case "arm" | "repeated" | "release_arm" | "receipt_hold" => s"@(posedge $arm); #2;"
            case "issue" | "release_issue" => s"@(posedge $issue); #2;"
            case "offered" => s"wait(${if(click) "response_req !== response_ack" else "response_req"}); #100000000;"
            case "ack" => s"wait(${if(click) "response_req !== response_ack" else "response_req"}); #10000000; response_ack=response_req; #2;"
            case "cleanup" => s"@(posedge $finish); #2;"
          }
          val pulse=if(resetAt=="receipt_hold") "#350000000;applicationReset=0;#100000000;if(idle) $fatal(1,\"RAM_RECEIPT_RESET_DRAIN_BYPASS\");" else if(resetAt.startsWith("release_")) "applicationReset=0;" else if(resetAt=="held") s"""
            #1000000000;
            if(delivered_word!=${priorWords+1} || delivered_publication!=${priorWords+1} || receipt_delivered!=${priorWords+1} || !idle)
              $$fatal(1,"RAM_POR_PROGRESS_DURING_RESET");
            #1000000000;applicationReset=0;
          """ else "#350000000;applicationReset=0;"+
            (if(resetAt=="repeated") "#20000000;applicationReset=1;#350000000;applicationReset=0;" else "")
          val launch=if(resetAt.startsWith("release_")) "eligible=0;applicationReset=1;response_ack=0;#350000000;"
            else if(resetAt=="held") "eligible=0;applicationReset=1;response_ack=0;" else "eligible=1;"
          monitored(click,s"""
            eligible=1;#100000000;
            ${(1 to priorWords).map(n => s"""
              fork
                begin ${send(click,n,0x8172a3b5L+n)} end
                begin ${publication(click,n,0x8172a3b5L+n,20000000L)} end
                begin ${receipt(click,n,30000000L)} end
                begin ${response(click,0x8172a3b5L+n,40000000L)} end
              join
              $settled#100000000;
            """).mkString("\n")}
            $launch
            fork
              begin #10000000;${send(click,priorWords+1,0x647291acL)} word_bits=32'hdeadbeef; end
              begin ${publication(click,priorWords+1,0x647291acL,if(resetAt=="repeated") 1200000000L else 20000000L)} end
              begin ${receipt(click,priorWords+1,if(resetAt=="receipt_hold") 1200000000L else 30000000L)} end
              begin
                $before
                applicationReset=1;eligible=0;response_ack=0;
                $pulse
              end
              begin ${if(resetAt=="cleanup") response(click,0x647291acL,40000000L) else "#1;"} end
            join
            if(response_bits_data !== 32'h647291ac)
              $$fatal(1,"RAM_RESET_RETAINED_WORD");
            $settled#1000000000;
            if(response_req || response_ack || app_delivered!=${priorWords+middleDelivered} || app_offers!=${priorWords+middleOffered})
              $$fatal(1,"RAM_RESET_STALE_PRESENTATION");
            eligible=1;#100000000;
            fork
              begin ${send(click,priorWords+2,0xfefb37d1L)} end
              begin ${publication(click,priorWords+2,0xfefb37d1L,20000000L)} end
              begin ${receipt(click,priorWords+2,30000000L)} end
              begin ${response(click,0xfefb37d1L,40000000L)} end
            join
            $settled#1000000000;
            if(delivered_word!=${priorWords+2} || delivered_publication!=${priorWords+2} || receipt_delivered!=${priorWords+2} ||
                app_delivered!=${priorWords+1+middleDelivered} || app_offers!=${priorWords+1+middleOffered})
              $$fatal(1,"RAM_RESET_EFFECT_COUNTS");
          """)
        }
      }
    }
  }
}
