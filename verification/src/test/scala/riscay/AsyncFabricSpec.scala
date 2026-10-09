// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import riscay.bd.FourPhaseFabric
import riscay.click.ClickFabric

/** Independent bus oracle. There is deliberately no service clock in this
  * fixture: ROM/fault replies and native routing must advance on handshakes.
  */
class AsyncFabricSpec extends AnyFunSuite {
  private val config = McuConfiguration(16, 16, 0, Vector.empty,
    ApplicationProfile(1, 1, "fabric", Vector.empty, Vector.empty))
  private case class Tx(op: Int, address: Long, data: Long, mask: Int,
      service: Boolean, answer: Long, error: Boolean = false)
  private val local = Seq(
    Tx(0,0,0,15,false,0x300000b7L), Tx(0,4,0,15,false,0x0000a103L),
    Tx(0,8,0,15,false,0x00010067L), Tx(2,0,0x55,15,false,0,true),
    Tx(0,12,0,15,false,0,true), Tx(0,0x20000000L,0,15,false,0,true),
    Tx(2,0x10000000L,0x55,15,false,0,true), Tx(1,0x10000010L,0,15,false,0,true),
    Tx(1,0x20000010L,0,15,false,0,true), Tx(1,0x3000004cL,0,15,false,0,true),
    Tx(1,0x30000011L,0,15,false,0,true), Tx(0,0x30000000L,0,15,false,0,true),
    Tx(1,0xfffffffcL,0,15,false,0,true), Tx(2,0x80000000L,0,15,false,0,true)) ++
    (0 until 15).flatMap(m => Seq(0L,16L).map(offset => Tx(1,0x30000000L+offset,0,m,false,0,true)))
  private val endpoints = Seq(
    Tx(0,0x10000000L,0,15,true,0xdeadbeefL),
    Tx(1,0x1000000cL,0,15,true,0,true), // Dynamic image protection is endpoint-owned.
    Tx(1,0x2000000cL,0,15,true,0x11223344L),
    Tx(2,0x20000000L,0xaabbccddL,5,true,0),
    Tx(1,0x30000010L,0,15,true,4), Tx(2,0x3000003cL,30000,15,true,0))
  private val transactions = local.zipWithIndex.flatMap { case(t,i) =>
    Seq(t, endpoints(i % endpoints.size), t, endpoints((i+1) % endpoints.size))
  }
  private def top(click: Boolean): AsyncModule = if(click)
    new ClickFabric(config, ClickTiming.Simulation, new ResetDomain("root"))
    else new FourPhaseFabric(config, BundledTiming.Simulation, new ResetDomain("root"))
  private def fresh(name: String) = {
    val root=Paths.get("build/async-fabric-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,name)
  }
  private def bit(value: Boolean) = if(value) 1 else 0
  private def phase(click: Boolean, n: Int) = if(click) (n+1)%2 else 1
  private def source(click: Boolean, ts: Seq[Tx], pause: Long = 1000000L): String = ts.zipWithIndex.map { case(t,n) =>
    val p=phase(click,n)
    s"""
      request_bits_operation=${t.op}; request_bits_address=32'h${t.address.toHexString};
      request_bits_data=32'h${t.data.toHexString}; request_bits_mask=${t.mask};
      #$pause; request_req=$p; wait(request_ack == $p); #$pause;
      ${if(click) "" else "request_req=0; wait(!request_ack); #1000000;"}
    """
  }.mkString
  private def sink(click: Boolean, ts: Seq[Tx]): String = ts.zipWithIndex.map { case(t,n) =>
    val p=phase(click,n)
    s"""
      wait(response_req == $p); #${(n%7+1)*37000000L};
      if(response_bits_data !== 32'h${t.answer.toHexString} || response_bits_error !== 1'b${bit(t.error)})
        $$fatal(1,"FABRIC_REPLY_$n data=%h error=%b",response_bits_data,response_bits_error);
      response_ack=$p;
      ${if(click) "#1000000;" else "wait(!response_req); #3000000; response_ack=0; #1000000;"}
    """
  }.mkString
  private def endpoint(click: Boolean, ts: Seq[Tx], fastest: Boolean = false): String = ts.filter(_.service).zipWithIndex.map { case(t,n) =>
    val p=phase(click,n)
    s"""
      wait(serviceRequest_req == $p); #${if(fastest) 2 else (n%5+1)*13000000L};
      if(serviceRequest_bits_operation !== 2'd${t.op} || serviceRequest_bits_address !== 32'h${t.address.toHexString} ||
         serviceRequest_bits_data !== 32'h${t.data.toHexString} || serviceRequest_bits_mask !== 4'd${t.mask})
        $$fatal(1,"FABRIC_ENDPOINT_$n");
      serviceRequest_ack=$p;
      serviceResponse_bits_data=32'h${t.answer.toHexString}; serviceResponse_bits_error=${bit(t.error)};
      #${if(fastest) 2 else 1000000}; serviceResponse_req=$p;
      fork
        begin
          wait(serviceResponse_ack == $p); #${(n%3+1)*43000000L};
          ${if(click) "" else "serviceResponse_req=0; wait(!serviceResponse_ack);"}
          #2; serviceResponse_bits_data=32'hbad0feed; serviceResponse_bits_error=1;
        end
        begin
          ${if(click) "#1000000;" else s"wait(!serviceRequest_req); #${(n%4+1)*53000000L}; serviceRequest_ack=0;"}
        end
      join
    """
  }.mkString
  private def releaseMonitor(directory: java.nio.file.Path, bypass: Boolean = false): String = {
    val design=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    def cell(id: String) = "dut." + design("primitives").arr.find(_("id").str == id).get("rtl_path")
      .str.split('.').drop(1).mkString(".")
    val guard=cell("acknowledge_guard")
    val apertures = Seq("payload", "accepted_phase", "service_response_phase").map { id =>
      val p = cell(id)
      s"""begin
        time rise=0, fall=0, changed=0;
        bit rose=0, fell=0, dataSeen=0;
        fork
          begin forever begin @(posedge $p.trigger or posedge reset);
            if(reset) begin rose=0; fell=0; dataSeen=0; end
            else begin
              if(fell && $$time-fall <= 100000) $$fatal(1,"FABRIC_PULSE_LOW_$id");
              ${if(id == "payload") s"if(dataSeen && $$time-changed <= 100000) $$fatal(1,\"FABRIC_SETUP\");" else ""}
              rise=$$time; rose=1;
            end
          end end
          begin forever begin @(negedge $p.trigger);
            if(!reset && rose) begin
              if($$time-rise <= 100000) $$fatal(1,"FABRIC_PULSE_HIGH_$id");
              fall=$$time; fell=1;
            end
          end end
          ${if(id == "payload") s"""begin forever begin @($p.d);
            if(!reset) begin
              if(rose && $$time-rise <= 100000) $$fatal(1,"FABRIC_HOLD");
              changed=$$time; dataSeen=1;
            end
          end end""" else ""}
        join
      end"""
    }.mkString("\n")
    s"""fork $apertures begin
      forever begin @($guard.q); #2;
        if(!reset && (${cell("capture")}.q || ${cell("dispatch")}.q))
          $$fatal(1,"FABRIC_RELEASE_BEFORE_CAPTURE_DRAIN");
      end
    end join_none
    ${if(bypass) s"force $guard.q=$guard.a;" else ""}"""
  }
  for(click <- Seq(false,true)) {
    val name = if(click) "click" else "bd"
    test(s"$name native fabric: ROM, static faults, alternating endpoint parity and independent backpressure") {
      val directory=fresh(name)
      AsyncTest.run(top(click), 1L to 64L, directory) { _ => s"""
        ${if(click) releaseMonitor(directory) else ""}
        fork
          begin ${source(click,transactions)} end
          begin ${sink(click,transactions)} end
          begin ${endpoint(click,transactions)} end
        join
        #1000000000;
        if(delivered_response != ${transactions.size} || delivered_serviceRequest != ${transactions.count(_.service)})
          $$fatal(1,"FABRIC_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native fabric: minimum source reuse and endpoint latency retain payloads") {
      val ts=Seq(local(0),endpoints(0),local(3),endpoints(3),local(2),endpoints(1))
      val directory=fresh(name+"-fast")
      AsyncTest.run(top(click), Seq(1L,2L,19L,81L), directory) { _ => s"""
        ${if(click) releaseMonitor(directory) else ""}
        fork
          begin ${source(click,ts,2L)} end
          begin ${sink(click,ts)} end
          begin ${endpoint(click,ts,fastest=true)} end
        join
        #1000000000;
        if(delivered_response != ${ts.size} || delivered_serviceRequest != ${ts.count(_.service)})
          $$fatal(1,"FABRIC_FAST_EXACTLY_ONCE");
      """ }
    }
    test(s"$name native fabric: reset cancels a stalled reply and HALT commits only once") {
      val after=local.take(3)
      AsyncTest.run(top(click), Seq(1L,2L,19L), fresh(name+"-held-reset")) { _ => s"""
        request_bits_operation=0; request_bits_address=0; request_bits_data=0; request_bits_mask=15;
        #1000000; request_req=1; wait(response_req); #100000000;
        if(response_bits_data !== 32'h300000b7) $$fatal(1,"FABRIC_STALLED_ROM");
        reset=1; request_req=0; serviceRequest_ack=0; serviceResponse_req=0; response_ack=0;
        #1000000000; reset=0; #1000000000;
        if(response_req || request_ack || serviceRequest_req || serviceResponse_ack)
          $$fatal(1,"FABRIC_STALE_REPLY_AFTER_RESET");
        request_bits_operation=3; request_bits_address=0; request_bits_data=0; request_bits_mask=0;
        #1000000; request_req=1; wait(serviceRequest_req); #1000000;
        if(serviceRequest_bits_operation !== 3) $$fatal(1,"FABRIC_HALT_ROUTE");
        serviceRequest_ack=1; #1000000000;
        if(response_req || request_ack || delivered_serviceRequest != 1)
          $$fatal(1,"FABRIC_HALT_COMPLETION_OR_REPLAY");
        reset=1; request_req=0; serviceRequest_ack=0;
        #1000000000; reset=0; #1000000000;
        fork
          begin ${source(click,after)} end
          begin ${sink(click,after)} end
        join
      """ }
    }
    test(s"$name native fabric: coordinated reset cancels an accepted endpoint request and restarts ROM without clocks") {
      val after=local.take(3)
      AsyncTest.run(top(click), Seq(1L,7L,19L), fresh(name+"-reset")) { _ => s"""
        request_bits_operation=1; request_bits_address=32'h20000000; request_bits_data=0; request_bits_mask=15;
        #100000000; request_req=1; wait(serviceRequest_req); #100000000; serviceRequest_ack=1;
        #100000000; if(response_req) $$fatal(1,"FABRIC_SPECULATIVE_REPLY");
        reset=1; request_req=0; serviceRequest_ack=0; serviceResponse_req=0; response_ack=0;
        #1000000000; reset=0; #1000000000;
        fork
          begin ${source(click,after)} end
          begin ${sink(click,after)} end
        join
        #1000000000;
        if(serviceRequest_req) $$fatal(1,"FABRIC_REPLAYED_ABORTED_REQUEST");
      """ }
    }
  }
  test("Click control rejects bypassed release guards") {
    val directory=fresh("click-guard-negative")
    val error=intercept[IllegalArgumentException] {
      AsyncTest.run(top(true), Seq(2L), directory) { _ =>
        s"""${releaseMonitor(directory,bypass=true)}
          fork
            begin ${source(true,transactions)} end
            begin ${sink(true,transactions)} end
            begin ${endpoint(true,transactions)} end
          join
        """
      }
    }
    assert(error.getMessage.contains("FABRIC_RELEASE_BEFORE_CAPTURE_DRAIN"),error.getMessage)
  }

}
