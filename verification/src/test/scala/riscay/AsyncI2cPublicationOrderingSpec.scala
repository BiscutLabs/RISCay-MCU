// SPDX-License-Identifier: Apache-2.0
// Composed ownership witness; all independent serial/effect oracles remain intact.
package riscay

import chiselasync.core.{AsyncModule,ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files,Path,Paths}
import org.scalatest.funsuite.AnyFunSuite

class AsyncI2cPublicationOrderingSpec extends AnyFunSuite {
  private def fresh(name: String): Path = {
    val root=Paths.get("build/async-i2c-publication-ordering");Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def native(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickI2c(0x35,new ResetDomain("root")) else
    new riscay.bd.FourPhaseI2c(0x35,new ResetDomain("root"))

  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native I2C keeps the blocked publication after early state acceptance and complete fork return") {
      val dir=fresh(name)
      AsyncTest.run(native(click),Seq(1L,2L,19L),dir) { _ =>
        val manifest=ujson.read(Files.readString(dir.resolve("export/contract.json")))("manifest")
        val root=manifest("design")
        val references="(?m)^`define\\s+ref_\\S+?_(ca_p_\\S+)\\s+(\\S+)\\s*$".r
          .findAllMatchIn(Files.readString(dir.resolve("export/"+manifest("probe_abi")("file").str)))
          .map(m => m.group(1)->m.group(2)).toMap
        def node(id: String)=root("children").arr.find(_("id").str==id).get("contract")
        def endpoint(owner: String,id: String,width: Int): String = {
          val e=node(owner)("endpoints").arr.find(_("id").str==id).get
          require(e("width").num.toInt==width,s"I2C_ORDER_ENDPOINT_WIDTH_${owner}_$id")
          "dut."+references(e("probe").str)
        }
        def cell(owner: String,id: String): String = {
          val p=node(owner)("primitives").arr.find(_("id").str==id).get
          "dut."+p("rtl_path").str.split('.').drop(1).mkString(".")
        }
        val pubReq=endpoint("publication","in_request",1)
        val pubAck=endpoint("publication","in_acknowledge",1)
        val pubData=endpoint("publication","in_data",174)
        val pubCapture=endpoint("publication","capture",1)
        val updateReq=endpoint("update","out_request",1)
        val updateAck=endpoint("update","out_acknowledge",1)
        val updateData=endpoint("update","out_data",174)
        val stateReq=endpoint("state","in_request",1)
        val stateAck=endpoint("state","in_acknowledge",1)
        val stateData=endpoint("state","out_data",76)
        val forkReq=endpoint("fork","in_request",1)
        val forkAck=endpoint("fork","in_acknowledge",1)
        val stateBranchAck=endpoint("fork",if(click) "left_acknowledge" else "out0_acknowledge",1)
        val publicationBranchAck=endpoint("fork",if(click) "right_acknowledge" else "out1_acknowledge",1)
        val scratch=cell("publication","receive_all")

        var head=0
        def edge(rise: Boolean=false,fall: Boolean=false,start: Boolean=false,stop: Boolean=false,
            sda: Boolean=true,epoch: Int=0,waitPublished: Boolean=true): String = {
          val slot=head%8;head=(head+1)%16;val gray=head^(head>>1)
          s"""edges_${slot}_rise=${if(rise) 1 else 0}; edges_${slot}_fall=${if(fall) 1 else 0};
            edges_${slot}_start=${if(start) 1 else 0}; edges_${slot}_stop=${if(stop) 1 else 0};
            edges_${slot}_sda=${if(sda) 1 else 0}; edges_${slot}_timeout=0;
            edges_${slot}_readWord=0; edges_${slot}_resetActive=0; edges_${slot}_programBusy=0;
            edges_${slot}_resetEpoch=$epoch; #1000000; tailGray=$gray;
            ${if(waitPublished) s"wait(observed_headGray==$gray); #400000000;" else ""}
          """
        }
        def byte(value: Int): String = (7 to 0 by -1).map(bit =>
          edge(rise=true,sda=(value&(1<<bit))!=0)+edge(fall=true)).mkString+
          "if(!observed_drive) $fatal(1,\"I2C_ORDER_BYTE_NOT_ACKNOWLEDGED\");\n"+
          edge(rise=true)+edge(fall=true)
        val first=edge(start=true)+byte(0x6a)+byte(0xa1)+edge(stop=true,epoch=111)
        val secondPrefix=edge(start=true)+byte(0x6a)+byte(0xb2)
        val beforeStopGray=head^(head>>1)
        val secondStop=edge(stop=true,epoch=222,waitPublished=false)
        val blockedHead=head
        val queuedStart=edge(start=true,waitPublished=false)
        val queuedGray=head^(head>>1)
        val third=byte(0x6a)+byte(0xc3)+edge(stop=true,epoch=333)
        def frame(value: Int,epoch: Int,label: String): String = s"""
          if(frame_bits_ingress_frame_length !== 6'd1 || frame_bits_ingress_frame_overflow ||
             frame_bits_ingress_resetActive || frame_bits_ingress_programBusy ||
             frame_bits_resetEpoch !== 64'd$epoch || frame_bits_ingress_frame_bytes_0 !== 8'd$value)
            $$fatal(1,"I2C_ORDER_${label}_FRAME");
        """+(1 until 33).map(i=>s"if(frame_bits_ingress_frame_bytes_$i !== 8'd0) $$fatal(1,\"I2C_ORDER_${label}_UNUSED_$i\");").mkString("\n")
        val firstFrame=frame(0xa1,111,"FIRST")
        val secondFrame=frame(0xb2,222,"SECOND")
        val thirdFrame=frame(0xc3,333,"THIRD")
        val returnFirst=if(click) "frame_ack=1;" else "frame_ack=1; wait(!frame_req); #2; frame_ack=0;"
        val returnSecond=if(click) "frame_ack=0;" else "frame_ack=1; wait(!frame_req); #2; frame_ack=0;"
        val returnThird=if(click) "frame_ack=1;" else "frame_ack=1; wait(!frame_req); #2; frame_ack=0;"
        val bdReturn=if(click) "" else s"""begin forever begin @(posedge $updateReq);
          if(!reset && ($forkAck || $stateBranchAck || $publicationBranchAck))
            $$fatal(1,"I2C_ORDER_BD_REUSE_BEFORE_BOTH_FORK_RETURNS");
        end end"""

        s"""begin
          integer publicationCaptures=0,scratchCaptures=0,byteCommits=0,frameCaptures=0,frameOffers=0;
          integer savedPublication=0,savedScratch=0,savedBytes=0;
          reg [173:0] blockedResult;
          reg [263:0] blockedScratch;
          reg [2:0] frameInputPhases=0;
          bit holdWindow=0,earlyStateSeen=0,blockedPhase=0;
          time scratchRise=0,scratchFall=0,scratchChange=0;
          bit scratchRose=0,scratchFell=0,scratchChanged=0;
          fork
            begin forever begin @(posedge $pubCapture);
              if(!reset) begin
                publicationCaptures=publicationCaptures+1;
                if(holdWindow) $$fatal(1,"I2C_ORDER_BLOCKED_PUBLICATION_CAPTURE");
                if($pubData[97]) begin
                  if(frameCaptures>=3) $$fatal(1,"I2C_ORDER_DUPLICATE_FRAME_CAPTURE");
                  frameInputPhases[frameCaptures]=$pubReq; frameCaptures=frameCaptures+1;
                  if(${if(click) "1" else "0"} && $pubReq !== 1'b0)
                    $$fatal(1,"I2C_ORDER_CLICK_FRAME_INPUT_PHASE");
                end
              end
            end end
            begin forever begin @(posedge $scratch.trigger);
              if(!reset) begin
                if(scratchFell && $$time-scratchFall <= 100000) $$fatal(1,"I2C_ORDER_SCRATCH_LOW");
                if(scratchChanged && $$time-scratchChange <= 100000) $$fatal(1,"I2C_ORDER_SCRATCH_SETUP");
                scratchRise=$$time;scratchRose=1;scratchCaptures=scratchCaptures+1;
                if(holdWindow) $$fatal(1,"I2C_ORDER_BLOCKED_SCRATCH_CAPTURE");
                if($pubData[14]) begin
                  byteCommits=byteCommits+1;
                  if($pubData[13:8] !== 6'd0 || $scratch.d[263:8] !== 256'd0)
                    $$fatal(1,"I2C_ORDER_BYTE_DESTINATION");
                  case(byteCommits)
                    1: if($scratch.d[7:0] !== 8'ha1) $$fatal(1,"I2C_ORDER_BYTE_ONE_D");
                    2: if($scratch.d[7:0] !== 8'hb2) $$fatal(1,"I2C_ORDER_BYTE_TWO_D");
                    3: if($scratch.d[7:0] !== 8'hc3) $$fatal(1,"I2C_ORDER_BYTE_THREE_D");
                    default: $$fatal(1,"I2C_ORDER_DUPLICATE_BYTE_COMMIT");
                  endcase
                end
              end
            end end
            begin forever begin @(negedge $scratch.trigger);
              if(!reset && scratchRose) begin
                if($$time-scratchRise <= 100000) $$fatal(1,"I2C_ORDER_SCRATCH_HIGH");
                scratchFall=$$time;scratchFell=1;
              end
            end end
            begin forever begin @($scratch.d);
              if(!reset) begin
                if(scratchRose && $$time-scratchRise <= 100000) $$fatal(1,"I2C_ORDER_SCRATCH_HOLD");
                scratchChange=$$time;scratchChanged=1;
              end
            end end
            begin forever begin @(${if(click) pubAck else "posedge "+pubAck});
              if(!reset && $pubAck==$pubReq && $pubData[14]) begin
                if($scratch.q[7:0] !== $pubData[7:0] || $scratch.q[263:8] !== 256'd0)
                  $$fatal(1,"I2C_ORDER_BYTE_ACK_BEFORE_Q");
              end
            end end
            begin forever begin @(${if(click) "frame_req" else "posedge frame_req"});
              if(!reset) begin
                frameOffers=frameOffers+1;
                if(${if(click) "1" else "0"} && frame_req !== (frameOffers%2))
                  $$fatal(1,"I2C_ORDER_CLICK_EFFECT_PHASE");
                if(frameOffers>3) $$fatal(1,"I2C_ORDER_DUPLICATE_FRAME_OFFER");
              end
            end end
            $bdReturn
          join_none
          ${if(click) "start=1;" else ""}
          $first
          wait(frame_req==1); #2; $firstFrame
          $secondPrefix
          if(byteCommits!=2 || frameOffers!=1 || frameCaptures!=1) $$fatal(1,"I2C_ORDER_PREFIX_COUNTS");
          $firstFrame
          $secondStop
          wait($pubReq != $pubAck && $pubData[97] && $pubData[173:170]==4'd$blockedHead);
          blockedPhase=$pubReq;
          // Match this retained request's phase, never the previous idle equality.
          // The state payload may arrive before its acknowledge guard returns.
          wait($forkReq==blockedPhase && $stateReq==blockedPhase && $stateAck==blockedPhase &&
               $stateBranchAck==blockedPhase && $stateData[75:72]==4'd$blockedHead);
          if($pubReq !== blockedPhase || $forkReq !== blockedPhase)
            $$fatal(1,"I2C_ORDER_BLOCKED_PHASE_CHANGED");
          if($forkReq==$forkAck || $updateReq==$updateAck || $stateBranchAck!=$stateReq ||
             $publicationBranchAck==$pubReq || observed_headGray!==4'd$beforeStopGray)
            $$fatal(1,"I2C_ORDER_EARLY_STATE_WITNESS_MISSING");
          earlyStateSeen=1;blockedResult=$updateData;blockedScratch=$scratch.q;
          savedPublication=publicationCaptures;savedScratch=scratchCaptures;savedBytes=byteCommits;
          holdWindow=1;
          $queuedStart
          #2000000000;
          if($updateData !== blockedResult || $pubData !== blockedResult || $scratch.q !== blockedScratch ||
             publicationCaptures!=savedPublication || scratchCaptures!=savedScratch || byteCommits!=savedBytes ||
             frameCaptures!=1 || frameOffers!=1 || $pubReq==$pubAck || $forkReq==$forkAck)
            $$fatal(1,"I2C_ORDER_BLOCKED_TOKEN_CHANGED");
          $firstFrame
          holdWindow=0;$returnFirst
          wait(frame_req==${if(click) 0 else 1}); #2;$secondFrame
          if(frameCaptures!=2 || frameOffers!=2 || byteCommits!=2) $$fatal(1,"I2C_ORDER_SECOND_COUNTS");
          $returnSecond
          wait(observed_headGray==4'd$queuedGray); #400000000;
          if(byteCommits!=2) $$fatal(1,"I2C_ORDER_NEXT_START_WROTE_BYTES");
          $third
          wait(frame_req==1); #2;$thirdFrame
          $returnThird
          #1000000000;
          if(!earlyStateSeen || frameOffers!=3 || frameCaptures!=3 || byteCommits!=3 || delivered_frame!=3 ||
             publicationCaptures!=scratchCaptures || snapshot_req || delivered_snapshot!=0)
            $$fatal(1,"I2C_ORDER_FINAL_COUNTS");
          ${if(click) "if(frameInputPhases !== 3'b000 || frame_req !== 1'b1 || frame_ack !== 1'b1) $fatal(1,\"I2C_ORDER_CLICK_INDEPENDENT_HISTORIES\");" else
            s"if($forkAck || $stateBranchAck || $publicationBranchAck || $forkReq || frame_req || frame_ack) $$fatal(1,\"I2C_ORDER_BD_FINAL_RETURNS\");"}
        end"""
      }
    }
  }
}
