// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import java.util.zip.CRC32
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

/** Independent Control stalls and real captures: Click's composed feedback and
  * BD's closed architectural/effect banks with CRC committed only on Stored.
  * Guard-output holds extend legal protocol latency; no payload/capture is forced.
  * These digital tests do not qualify physical capture or C-element envelopes.
  */
class AsyncCrcControlSpec extends AnyFunSuite {
  private val config = McuConfiguration(16,16,1,Vector(MeasurementChannel(0,"test",1,0)),
    ApplicationProfile(1,1,"crc-control",Vector(HostRegister(0,"A")),Vector.empty))
  private val p = SocParameters(config)
  private val word = 0xabcde701L
  private val checksum = {
    val c = new CRC32
    (0 until 4).foreach(i => c.update(((word >>> (8*i)) & 255).toInt)); c.getValue
  }
  private val pendingCrcValue = checksum ^ 0xffffffffL
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickControl(p,new ResetDomain("root"))
    else new riscay.bd.FourPhaseControl(p,new ResetDomain("root"))
  private def fresh(name: String): Path = {
    val root=Paths.get("build/async-crc-control-tests")
    Files.createDirectories(root); Files.createTempDirectory(root,name)
  }
  private def child(n: ujson.Value, id: String): ujson.Value = {
    val xs=n("children").arr.filter(_("id").str==id)
    require(xs.size==1,s"CRC_BINDING_CHILD:$id"); xs.head("contract")
  }
  private def path(rtl: String): String = "dut."+rtl.split('.').drop(1).mkString(".")
  private def primitive(n: ujson.Value, id: String, model: String, width: Int = 0): ujson.Value = {
    val xs=n("primitives").arr.filter(_("id").str==id)
    require(xs.size==1,s"CRC_BINDING_PRIMITIVE:$id")
    val v=xs.head; require(v("model").str==model,s"CRC_BINDING_MODEL:$id")
    if(width>0) require(v("parameters")("WIDTH").str.toInt==width,s"CRC_BINDING_WIDTH:$id")
    v
  }
  private def port(abi: ujson.Value, n: ujson.Value, name: String): String = {
    val ns=abi("nodes").arr.filter(_("rtl_path").str==n("rtl_path").str)
    require(ns.size==1,s"CRC_BINDING_ABI_NODE:$name")
    val source=s"~|${n("module").str}>$name"
    val ps=ns.head("ports").arr.filter(_("source").str==source)
    require(ps.size==1 && ps.head("width").num.toInt==1 && !ps.head("signed").bool,
      s"CRC_BINDING_ABI_PORT:$name")
    path(n("rtl_path").str)+"."+name.replace('.','_').replace('[','_').replace("]","")
  }
  private def slice(n: ujson.Value, channel: String, field: String, wire: String, width: Int): String = {
    val cs=n("channels").arr.filter(_("id").str==channel)
    require(cs.size==1,s"CRC_BINDING_CHANNEL:$channel")
    val fs=cs.head("layout").arr.filter(_("field").str==field)
    require(fs.size==1 && fs.head("width").num.toInt==width && !fs.head("signed").bool,
      s"CRC_BINDING_FIELD:$field")
    require(fs.head("source").str==s"~|${n("module").str}>$channel.$field",s"CRC_BINDING_SOURCE:$field")
    val lo=fs.head("lsb").num.toInt
    if(width==1) s"$wire[$lo]" else s"$wire[${lo+width-1}:$lo]"
  }
  private case class Bindings(crcCapture: String, crcD: String, crcQ: String,
    stateCapture: String, stateD: String, stateQ: String, statePending: String,
    stateWord: String, stateCrc: String, stateReceived: String, stateCandidate: String,
    updateCapture: String, updateQ: String, contextWidth: Int, stateWidth: Int,
    crcReq: String, crcAck: String, resultReq: String, stateReq: String, stateAck: String,
    forkAck: String, offerGuard: String, stateGuard: String, crcAckGuard: String)
  private def bindings(directory: Path, click: Boolean): Bindings = {
    val n=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    val abi=ujson.read(Files.readString(directory.resolve("export/ports.json")))
    val crc=child(n,"crc"); val state=child(n,"state"); val update=child(n,"update"); val fork=child(n,"fork")
    val storage=if(click) state else child(child(state,"stage0"),"storage")
    val model=if(click) "ChiselAsyncEventRegister_v1" else "ChiselAsyncClosingLatch_v1"
    val cp=path(primitive(crc,"payload",model,32)("rtl_path").str)
    val layouts=storage("channels").arr.filter(_("id").str=="out")
    require(layouts.size==1,"CRC_BINDING_STATE_CHANNEL")
    val lanes=layouts.head("layout").arr.sortBy(_("lsb").num.toInt)
    var stateWidth=0
    lanes.foreach { field =>
      val width=field("width").num.toInt
      require(width>0 && field("lsb").num.toInt==stateWidth,"CRC_BINDING_STATE_LAYOUT")
      stateWidth+=width
    }
    require(stateWidth>0,"CRC_BINDING_EMPTY_STATE")
    val sp=path(primitive(storage,"payload",model,stateWidth)("rtl_path").str)
    val up=primitive(update,"payload",model); val uq=path(up("rtl_path").str)
    for(id <- Seq("crc_context_request","crc_context_return")) {
      val gate=primitive(n,id,"ChiselAsyncAsymmetricC_v1")
      require(gate("parameters")("COMMON").str=="2" && gate("parameters")("COMMON_INVERT").str=="0" &&
        gate("parameters")("RISING").str=="0" && gate("parameters")("FALLING").str=="0", "CRC_BINDING_RENDEZVOUS")
    }
    def guard(owner: ujson.Value, id: String): String = {
      val g=primitive(owner,id,"ChiselAsyncControlGate_v1",1)
      require(g("parameters")("OP").str=="0",s"CRC_BINDING_GUARD:$id"); path(g("rtl_path").str)+".q"
    }
    val capture=if(click) ".trigger" else ".closed"
    Bindings(cp+capture,cp+".d",cp+".q",sp+capture,sp+".d",sp+".q",
      slice(storage,"out","bits.state.loaderPending",sp+".d",1),
      slice(storage,"out","bits.state.loaderWord",sp+".d",32),
      slice(storage,"out","bits.state.crc",sp+".d",32),
      slice(storage,"out","bits.state.received",sp+".d",5),
      slice(storage,"out","bits.pendingCrc",sp+".d",32),
      uq+capture,uq+".q",up("parameters")("WIDTH").str.toInt,stateWidth,
      port(abi,crc,"in.req"),port(abi,crc,"in.ack"),port(abi,crc,"out.req"),
      port(abi,state,"in.req"),port(abi,state,"in.ack"),port(abi,fork,if(click) "left.ack" else "out[0].ack"),
      guard(crc,if(click) "output_guard" else "output_delay"),guard(storage,"request_delay"),
      if(click) guard(crc,"acknowledge_guard") else
        path(primitive(crc,"acknowledge","ChiselAsyncAsymmetricC_v1")("rtl_path").str)+".q")
  }
  private def hex(v: Long): String = s"32'h${v.toHexString}"
  private def frame(op: Int, words: Long*): Seq[Int] = Seq(op)++words.flatMap(w =>
    (0 until 4).map(i => ((w >>> (8*i))&255).toInt))
  private def source(click: Boolean, phase: Int, kind: Int, bytes: Seq[Int] = Seq.empty): String = {
    val data=bytes.padTo(33,0).zipWithIndex.map { case(v,i) => s"command_bits_frame_bytes_$i=$v;" }.mkString("\n")
    s"""command_bits_kind=$kind; command_bits_frame_length=${bytes.size}; command_bits_frame_overflow=0;
      $data
      #2; command_req=$phase; wait(command_ack == $phase); #2;
      ${if(click) "command_bits_frame_bytes_5=8'h5a;" else "command_req=0; wait(!command_ack); #2;"}
    """
  }
  private def stateChecks(stored: Boolean, cold: Boolean = false, ended: Boolean = false): String = {
    val fields=Map("received" -> (if(stored) 4L else 0L), "crc" -> (if(stored) pendingCrcValue else 0xffffffffL),
      "loaderPending" -> (if(!stored && !cold) 1L else 0L), "loaderWord" -> (if(cold) 0L else word),
      "imageLength" -> (if(cold) 0L else 4L), "imageId" -> (if(cold) 0L else 19L),
      "expectedCrc" -> (if(cold) 0L else checksum), "mode" -> (if(cold) 0L else if(ended) 2L else 1L),
      "programmed" -> (if(ended) 1L else 0L))
    fields.toSeq.sortBy(_._1).map { case(k,v) =>
      s"if(reply_bits_state_$k !== ${hex(v)}) $$fatal(1,\"CRC_CONTROL_STATE:$k\");"
    }.mkString("\n")
  }
  private def finishReply(click: Boolean, phase: Int): String =
    s"reply_ack=$phase; "+(if(click) "#2;" else "wait(!reply_req); #2; reply_ack=0; #2;")
  private def normal(click: Boolean, phase: Int, kind: Int, bytes: Seq[Int], check: String): String = s"""
    fork begin ${source(click,phase,kind,bytes)} end
      begin wait(reply_req == $phase); #2; $check ${finishReply(click,phase)} end join
    #1000000000;
  """

  private def observers(b: Bindings, phase: Int, click: Boolean): String = s"""
    fork : boundary_observers
      begin : request_watch forever begin
        @(${b.stateReq}); #1;
        if(!reset && request_blocked && ${b.stateReq} == $phase)
          $$fatal(1,"CRC_CONTEXT_REQUEST_EARLY");
      end end
      begin : ack_watch forever begin
        @(${b.forkAck}); #1;
        if(!reset && state_blocked && ${b.forkAck} == $phase)
          $$fatal(1,"CRC_CONTEXT_ACK_EARLY");
      end end
      begin : return_watch forever begin
        @(${b.forkAck}); #1;
        if(!reset && return_blocked && ${b.forkAck} == ${if(click) phase else 0})
          $$fatal(1,"CRC_CONTEXT_RETURN_EARLY");
      end end
      begin : crc_capture_watch forever begin
        @(posedge ${b.crcCapture}); #1;
        if(!reset && tracking) begin
          crc_captures=crc_captures+1;
          if(${b.crcD} !== ${hex(pendingCrcValue)}) $$fatal(1,"CRC_CONTROL_CAPTURE_D");
          #20000000;
          if(!reset && tracking && ${b.crcQ} !== ${hex(pendingCrcValue)}) $$fatal(1,"CRC_CONTROL_CAPTURE_Q");
        end
      end end
      begin : state_capture_watch forever begin
        @(posedge ${b.stateCapture}); #1;
        if(!reset && tracking) begin
          state_captures=state_captures+1;
          if(${b.stateCandidate} !== ${hex(pendingCrcValue)} || ${b.stateWord} !== ${hex(word)} ||
            ${b.stateCrc} !== (${b.statePending} ? 32'hffffffff : ${hex(pendingCrcValue)}) ||
            ${b.stateReceived} !== (${b.statePending} ? 32'd0 : 32'd4))
              $$fatal(1,"CRC_CONTROL_STATE_CAPTURE_D");
          saved_state=${b.stateD}; #20000000;
          if(!reset && tracking && ${b.stateQ} !== saved_state) $$fatal(1,"CRC_CONTROL_STATE_CAPTURE_Q");
        end
      end end
      begin : update_capture_watch forever begin
        @(posedge ${b.updateCapture}); #1;
        if(!reset && tracking) update_captures=update_captures+1;
      end end
      begin : context_watch forever begin
        @(${b.updateQ}); #1;
        if(!reset && hold_context && ${b.updateQ} !== held_context)
          $$fatal(1,"CRC_CONTROL_CONTEXT_CHANGED");
      end end
    join_none
    #2;
  """

  // Click retains the CRC/context rendezvous. Its existing fixtures and both
  // phase polarities remain unchanged. BD's one-bank replacements follow below.
  for(click <- Seq(true); scenario <- Seq("offer","accept","return","reply","por")) {
    val variant=if(click) "click" else "bd"
    test(s"$variant CRC retained context: independent $scenario stall, native captures and exact publication") {
      for(phase <- (if(click) Seq(0,1) else Seq(1))) {
        val directory=fresh(s"$variant-$scenario-phase-$phase")
        AsyncTest.run(top(click),Seq(1L,2L,19L),directory) { _ =>
          val b=bindings(directory,click); val old=if(click) 1-phase else 0
          val padded=click && phase==1
          val next=if(click) 1-phase else 1
          val returning=scenario=="return" || scenario=="por"
          val forceBefore= scenario match {
            case "offer" => s"force ${b.offerGuard}=1'b$old; request_blocked=1;"
            case "accept" => s"force ${b.stateGuard}=1'b$old; state_blocked=1;"
            case "return" | "por" if click => s"force ${b.crcAckGuard}=1'b$old; return_blocked=1;"
            case _ => ""
          }
          val release= scenario match {
            case "offer" => s"release ${b.offerGuard};"
            case "accept" => s"release ${b.stateGuard};"
            case "return" | "por" => s"release ${b.crcAckGuard};"
            case _ => ""
          }
          val begin=normal(click,1,0,frame(1,4,0,checksum,0x10000L,0,0,0,19),
            "if(reply_bits_state_mode !== 1 || reply_bits_state_loaderPending || reply_bits_state_received != 0) $fatal(1,\"CRC_CONTROL_BEGIN\");")
          val pad=if(padded) normal(click,0,1,Seq.empty,
            "if(reply_bits_state_received != 0 || reply_bits_state_crc !== 32'hffffffff) $fatal(1,\"CRC_CONTROL_PADDING\");") else ""
          val heldShape= scenario match {
            case "offer" => s"${b.resultReq} !== $old || ${b.stateReq} !== $old || ${b.crcAck} !== $phase || state_captures != 0"
            case "accept" => s"${b.resultReq} !== $phase || ${b.stateReq} !== $phase || ${b.stateAck} !== $old || state_captures != 0"
            case "return" | "por" if click => s"${b.stateAck} !== $phase || ${b.crcAck} !== $old || ${b.forkAck} !== $old || state_captures != 1"
            case "return" | "por" => s"${b.stateAck} !== 0 || ${b.crcAck} !== 1 || ${b.forkAck} !== 1 || ${b.crcReq} !== 0 || state_captures != 1"
            case _ => s"reply_req !== $phase || reply_ack !== $old || state_captures != 1"
          }
          val returnSetup=if(returning && !click) s"""
            wait(${b.crcAck}); #2; force ${b.crcAckGuard}=1'b1;
            wait(${b.stateAck} && ${b.forkAck}); #2; return_blocked=1;
            ${finishReply(click,phase)}
            wait(!${b.stateAck}); #2;
          """ else if(scenario!="reply" && !(scenario=="por" && click)) s"reply_ack=$phase; #2;" else ""
          val tail=if(scenario=="por") s"""
            // Click POR includes an actually held phase-zero host result. BD POR
            // occurs after state ACK returned low while CRC ingress ACK stays high.
            before_reset_replies=delivered_reply;
            tracking=0; hold_context=0; request_blocked=0; state_blocked=0; return_blocked=0;
            reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
            #2; $release
            #1000000000; reset=0; #1000000000;
            if(command_ack || reply_req) $$fatal(1,"CRC_CONTROL_POR_STALE");
            ${if(click) "start=1;" else ""}
            ${normal(click,1,1,Seq.empty,stateChecks(stored=false,cold=true))}
            ${normal(click,if(click) 0 else 1,0,frame(3),stateChecks(stored=false,cold=true)+
              "if(reply_bits_state_lastError !== 6) $fatal(1,\"CRC_CONTROL_POR_ACCOUNTING\");")}
            if(delivered_reply != before_reset_replies+2) $$fatal(1,"CRC_CONTROL_POR_EXACTLY_ONCE");
          """ else s"""
            hold_context=0; request_blocked=0; state_blocked=0; return_blocked=0; $release
            ${if(scenario=="reply") finishReply(click,phase) else if(!click && !returning)
              "wait(!reply_req); #2; reply_ack=0; #2;" else ""}
            wait(reply_req == $next); #2;
            ${stateChecks(stored=true)}
            if(reply_bits_kind !== 1 || reply_bits_programWrite) $$fatal(1,"CRC_CONTROL_STORED_REPLY");
            ${finishReply(click,next)}
            #1000000000;
            if(crc_captures != 2 || state_captures != 2 || update_captures != 2)
              $$fatal(1,"CRC_CONTROL_CAPTURE_EXACTLY_ONCE");
            tracking=0;
            ${normal(click,phase,1,Seq.empty,stateChecks(stored=true))}
            ${normal(click,next,0,frame(3),stateChecks(stored=true,ended=true))}
            if(delivered_reply != ${if(padded) 6 else 5}) $$fatal(1,"CRC_CONTROL_REPLY_EXACTLY_ONCE");
          """
          s"""begin : crc_context_test
            integer crc_captures=0, state_captures=0, update_captures=0, before_reset_replies=0;
            reg tracking=0, request_blocked=0, state_blocked=0, return_blocked=0, hold_context=0;
            reg [${b.contextWidth-1}:0] held_context;
            reg [${b.stateWidth-1}:0] saved_state; // Compare every declared state lane at real capture.
            ${observers(b,phase,click)}
            ${if(click) "start=1;" else ""}
            $begin $pad
            tracking=1; $forceBefore
            ${source(click,phase,0,frame(2,0,word))}
            wait(${b.crcReq} == $phase); wait(crc_captures == 1); #20000000;
            wait(reply_req == $phase); #2;
            ${stateChecks(stored=false)}
            if(reply_bits_kind !== 0 || !reply_bits_programWrite) $$fatal(1,"CRC_CONTROL_WORD_REPLY");
            held_context=${b.updateQ}; hold_context=1;
            $returnSetup
            // A legal next source offer is retained by the existing join. It
            // must not overwrite the pending WORD context behind a stalled fork.
            ${source(click,next,1)}
            #300000000;
            if($heldShape) $$fatal(1,"CRC_CONTROL_STALL_SHAPE");
            if(crc_captures != 1 || update_captures != 1 || ${b.updateQ} !== held_context)
              $$fatal(1,"CRC_CONTROL_STALLED_EXACTLY_ONCE");
            $tail
            disable boundary_observers;
          end"""
        }
      }
    }
  }

  private case class BdBindings(stateCapture: String, stateD: String, stateQ: String,
    stateWidth: Int, initialState: BigInt, effectCapture: String, effectD: String,
    effectQ: String, effectWidth: Int, kindCapture: String, kindQ: String,
    requestGuard: String, acknowledgeGuard: String, outputGuard: String,
    stateFields: Map[String,(Int,Int)]) {
    def field(name: String, wire: String): String = {
      val (lo,width)=stateFields(name)
      if(width==1) s"$wire[$lo]" else s"$wire[${lo+width-1}:$lo]"
    }
  }
  private def bdBindings(directory: Path): BdBindings = {
    val n=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    val transaction=child(n,"transaction")
    val state=primitive(n,"state_bank","ChiselAsyncEventRegister_v1")
    val effect=primitive(n,"effect_bank","ChiselAsyncEventRegister_v1")
    val kind=primitive(transaction,"payload","ChiselAsyncClosingLatch_v1",3)
    val reply=n("channels").arr.filter(_("id").str=="reply")
    require(reply.size==1,"CRC_BANK_REPLY_CHANNEL")
    val fields=reply.head("layout").arr.filter(_("field").str.startsWith("bits.state."))
      .sortBy(_("lsb").num.toInt)
    require(fields.nonEmpty,"CRC_BANK_STATE_LAYOUT")
    val first=fields.head("lsb").num.toInt
    var width=0
    val layout=fields.map { f =>
      val lo=f("lsb").num.toInt-first;val bits=f("width").num.toInt
      require(lo==width && bits>0 && !f("signed").bool,"CRC_BANK_STATE_CONTIGUOUS")
      width+=bits
      f("field").str.stripPrefix("bits.state.") -> (lo,bits)
    }.toMap
    require(width==state("parameters")("WIDTH").str.toInt,"CRC_BANK_STATE_WIDTH")
    require(layout("crc")._2==32 && layout("loaderWord")._2==32 &&
      layout("loaderPending")._2==1 && layout("received")._2==BigInt(config.programBytes).bitLength,
      "CRC_BANK_ACCOUNTING_WIDTHS")
    def guard(owner: ujson.Value,id: String): String = {
      val g=primitive(owner,id,"ChiselAsyncControlGate_v1",1)
      require(g("parameters")("OP").str=="0",s"CRC_BANK_GUARD:$id")
      path(g("rtl_path").str)+".q"
    }
    val sp=path(state("rtl_path").str);val ep=path(effect("rtl_path").str)
    val kp=path(kind("rtl_path").str)
    BdBindings(sp+".trigger",sp+".d",sp+".q",width,BigInt(state("parameters")("RESET_VALUE").str),
      ep+".trigger",ep+".d",ep+".q",effect("parameters")("WIDTH").str.toInt,kp+".closed",kp+".q",
      guard(transaction,"request_delay"),guard(n,"acknowledge_guard"),guard(n,"output_guard"),layout)
  }
  private def bdFields(b: BdBindings,wire: String,stored: Boolean,ended: Boolean=false): String = {
    val fields=Map("received" -> (if(stored) 4L else 0L),
      "crc" -> (if(stored) pendingCrcValue else 0xffffffffL),
      "loaderPending" -> (if(stored) 0L else 1L),"loaderWord" -> word,
      "imageLength" -> 4L,"imageId" -> 19L,"expectedCrc" -> checksum,
      "mode" -> (if(ended) 2L else 1L),"programmed" -> (if(ended) 1L else 0L))
    fields.toSeq.sortBy(_._1).map { case(k,v) =>
      s"if(${b.field(k,wire)} !== ${hex(v)}) $$fatal(1,\"CRC_BANK_ACCOUNTING:$k\");"
    }.mkString("\n")
  }
  private def bdObservers(b: BdBindings): String = s"""
    fork : bank_observers
      begin : state_capture_watch forever begin
        @(posedge ${b.stateCapture}); #1;
        if(!reset && tracking) begin
          state_captures=state_captures+1;
          if(accounting_checks) begin
            case(state_captures)
              1: begin ${bdFields(b,b.stateD,stored=false)} end
              2,3: begin ${bdFields(b,b.stateD,stored=true)} end
              4: begin ${bdFields(b,b.stateD,stored=true,ended=true)} end
              default: $$fatal(1,"CRC_BANK_EXTRA_CAPTURE");
            endcase
          end
          captured_state=${b.stateD}; #20000000;
          if(!reset && tracking && ${b.stateQ} !== captured_state)
            $$fatal(1,"CRC_BANK_CAPTURE_Q");
        end
      end end
      begin : effect_capture_watch forever begin
        @(posedge ${b.effectCapture}); #1;
        if(!reset && tracking) begin
          effect_captures=effect_captures+1;captured_effects=${b.effectD}; #20000000;
          if(!reset && tracking && ${b.effectQ} !== captured_effects)
            $$fatal(1,"CRC_BANK_EFFECT_CAPTURE_Q");
        end
      end end
      begin : kind_capture_watch forever begin
        @(posedge ${b.kindCapture}); #1;
        if(!reset && tracking) kind_captures=kind_captures+1;
      end end
      begin : retained_state_watch forever begin
        @(${b.stateQ} or ${b.effectQ} or ${b.kindQ}); #1;
        if(!reset && hold_banks && (${b.stateQ} !== held_state ||
          ${b.effectQ} !== held_effects || ${b.kindQ} !== held_kind))
          $$fatal(1,"CRC_BANK_CONTEXT_CHANGED_WHILE_HELD");
      end end
    join_none
    #2;
  """
  private def bdDeclarations(b: BdBindings): String = s"""
    integer state_captures=0,effect_captures=0,kind_captures=0,before_reset_replies=0;
    reg tracking=0,accounting_checks=0,hold_banks=0;
    reg [${b.stateWidth-1}:0] captured_state,held_state;
    reg [${b.effectWidth-1}:0] captured_effects,held_effects;
    reg [2:0] held_kind;
  """
  private def bdBegin: String = normal(false,1,0,frame(1,4,0,checksum,0x10000L,0,0,0,19),
    "if(reply_bits_state_mode !== 1 || reply_bits_state_loaderPending || reply_bits_state_received != 0) $fatal(1,\"CRC_CONTROL_BEGIN\");")

  // Deleted BD rendezvous forces are replaced by stalls at the surviving
  // request, source-return and result-publication boundaries. The oracle still
  // inspects actual state/effect captures; no payload or capture pin is forced.
  for(scenario <- Seq("offer","accept","return","reply")) {
    test(s"bd committed CRC bank: independent $scenario stall, retained frame and exact accounting") {
      val directory=fresh(s"bd-bank-$scenario")
      AsyncTest.run(top(false),Seq(1L,2L,19L),directory) { _ =>
        val b=bdBindings(directory)
        val forceBefore=scenario match {
          case "offer" => s"force ${b.outputGuard}=1'b0;"
          case "accept" => s"force ${b.requestGuard}=1'b0;"
          case _ => ""
        }
        val initialStall=scenario match {
          case "accept" => s"""
            #300000000;
            if(state_captures || effect_captures || kind_captures || command_ack || reply_req)
              $$fatal(1,"CRC_BANK_ACCEPT_STALL");
            release ${b.requestGuard};
          """
          case "offer" => s"""
            wait(state_captures==1 && effect_captures==1); #20000000;
            ${bdFields(b,b.stateQ,stored=false)}
            #300000000;
            if(reply_req || state_captures!=1 || effect_captures!=1 || kind_captures!=1)
              $$fatal(1,"CRC_BANK_OFFER_STALL");
            release ${b.outputGuard};
          """
          case "return" => s"""
            wait(command_ack); #2; force ${b.acknowledgeGuard}=1'b1;
            wait(!command_req); #2;
          """
          case _ => ""
        }
        val returnStall=if(scenario=="return") s"""
          reply_ack=1;wait(!reply_req);#300000000;
          if(!command_ack || state_captures!=1 || effect_captures!=1 || kind_captures!=1)
            $$fatal(1,"CRC_BANK_RETURN_STALL");
          reply_ack=0;#300000000;
          if(!command_ack || state_captures!=1 || effect_captures!=1 || kind_captures!=1)
            $$fatal(1,"CRC_BANK_SOURCE_RETURN_STALL");
          hold_banks=0;release ${b.acknowledgeGuard};
        """ else s"""
          reply_ack=1;wait(!reply_req);#37000000;
          if(state_captures!=1 || effect_captures!=1 || kind_captures!=1)
            $$fatal(1,"CRC_BANK_REUSED_BEFORE_REPLY_RETURN");
          hold_banks=0;reply_ack=0;#2;
        """
        s"""begin : committed_crc_test
          ${bdDeclarations(b)}
          ${bdObservers(b)}
          $bdBegin
          tracking=1;accounting_checks=1;$forceBefore
          fork
            begin : source_stream
              ${source(false,1,0,frame(2,0,word))}
              // The accepted WORD frame may now be overwritten. Stored must
              // use the retained loaderWord, never these later frame bytes.
              command_bits_frame_bytes_5=8'h5a;#2;
              ${source(false,1,1,frame(2,0,0x76543210L))}
            end
            begin : stalled_consumer
              $initialStall
              wait(reply_req);#20000000;
              ${stateChecks(stored=false)}
              if(reply_bits_kind!==0 || !reply_bits_programWrite)
                $$fatal(1,"CRC_CONTROL_WORD_REPLY");
              held_state=${b.stateQ};held_effects=${b.effectQ};held_kind=${b.kindQ};hold_banks=1;
              #300000000;
              if(state_captures!=1 || effect_captures!=1 || kind_captures!=1)
                $$fatal(1,"CRC_BANK_STALLED_EXACTLY_ONCE");
              $returnStall
              wait(reply_req);#20000000;
              ${stateChecks(stored=true)}
              if(reply_bits_kind!==1 || reply_bits_programWrite)
                $$fatal(1,"CRC_CONTROL_STORED_REPLY");
              ${finishReply(false,1)}
            end
          join
          #1000000000;
          if(state_captures!=2 || effect_captures!=2 || kind_captures!=2)
            $$fatal(1,"CRC_BANK_CAPTURE_EXACTLY_ONCE");
          ${normal(false,1,1,Seq.empty,stateChecks(stored=true))}
          ${normal(false,1,0,frame(3),stateChecks(stored=true,ended=true))}
          if(state_captures!=4 || effect_captures!=4 || kind_captures!=4 || delivered_reply!=5)
            $$fatal(1,"CRC_BANK_REPLY_EXACTLY_ONCE");
          tracking=0;disable bank_observers;
        end"""
      }
    }
  }

  for(abort <- Seq("before_capture","kind_capture","bank_capture","reply","return")) {
    test(s"bd committed CRC bank: POR at $abort aborts the transaction and restores cold accounting") {
      val directory=fresh(s"bd-bank-por-$abort")
      AsyncTest.run(top(false),Seq(1L,2L,19L),directory) { _ =>
        val b=bdBindings(directory)
        val before=if(abort=="before_capture") s"force ${b.requestGuard}=1'b0;" else ""
        val point=abort match {
          case "before_capture" => "wait(command_req);#300000000;if(state_captures || effect_captures) $fatal(1,\"CRC_BANK_POR_PRECAPTURE\");"
          case "kind_capture" => s"@(posedge ${b.kindCapture});#1;"
          case "bank_capture" => s"@(posedge ${b.stateCapture});#1;"
          case "reply" => "wait(reply_req);#20000000;"
          case "return" => s"""
            wait(command_ack);#2;force ${b.acknowledgeGuard}=1'b1;
            wait(!command_req);wait(reply_req);#2;reply_ack=1;wait(!reply_req);#2;
          """
        }
        val release=abort match {
          case "before_capture" => s"release ${b.requestGuard};"
          case "return" => s"release ${b.acknowledgeGuard};"
          case _ => ""
        }
        s"""begin : bank_por_test
          ${bdDeclarations(b)}
          ${bdObservers(b)}
          $bdBegin
          tracking=1;$before
          fork : abortable_source
            begin ${source(false,1,0,frame(2,0,word))} end
          join_none
          #2;$point
          before_reset_replies=delivered_reply;tracking=0;hold_banks=0;
          reset=1;disable abortable_source;command_req=0;reply_ack=0;
          #2;$release
          #1000000000;reset=0;#1000000000;
          if(command_ack || reply_req || ${b.stateQ}!==${b.stateWidth}'h${b.initialState.toString(16)} ||
             ${b.effectQ}!==0 || ${b.kindQ}!==0)
            $$fatal(1,"CRC_CONTROL_POR_STALE");
          ${normal(false,1,1,Seq.empty,stateChecks(stored=false,cold=true))}
          ${normal(false,1,0,frame(3),stateChecks(stored=false,cold=true)+
            "if(reply_bits_state_lastError !== 6) $fatal(1,\"CRC_CONTROL_POR_ACCOUNTING\");")}
          if(delivered_reply!=before_reset_replies+2)
            $$fatal(1,"CRC_CONTROL_POR_EXACTLY_ONCE");
          disable bank_observers;
        end"""
      }
    }
  }
}
