// SPDX-License-Identifier: Apache-2.0
// Complements AsyncScalingSpec; independent arithmetic and bounded native work.
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite

class AsyncElapsedLoopSpec extends AnyFunSuite {
  private val mask = (BigInt(1) << 32) - 1
  private val normalMicros = Seq(1, 999, 129354, 83333, 200000)
  private def fresh(name: String): Path = {
    val base = Paths.get("build/async-elapsed-loop-tests")
    Files.createDirectories(base); Files.createTempDirectory(base, name)
  }
  private def top(click: Boolean, micros: Seq[Int]): AsyncModule =
    if(click) new riscay.click.ClickElapsed(micros, new ResetDomain("root"))
    else new riscay.bd.FourPhaseElapsed(micros, new ResetDomain("root"))

  private case class Expected(target: BigInt, delta: BigInt, turns: Int,
      fraction: Seq[BigInt], elapsed: Seq[BigInt])
  // Wide multiply/divide oracle is deliberately independent of radix hardware.
  private def expected(micros: Seq[Int], deltas: Seq[BigInt]): Seq[Expected] = {
    var target = BigInt(0); var fraction = Vector.fill(micros.size)(BigInt(0))
    deltas.map { delta =>
      require(delta >= 0 && delta <= mask)
      target = (target + delta) & mask
      val total = micros.indices.map(i => delta * BigInt(micros(i)) + fraction(i))
      fraction = total.map(_ % 1000).toVector
      Expected(target, delta, ((delta.bitLength + 3) / 4).max(1),
        fraction, total.map(n => (n / 1000) & mask))
    }
  }
  private def path(rtl: String): String = "dut." + rtl.split('.').drop(1).mkString(".")
  private def node(directory: Path): ujson.Value =
    ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
  private def child(n: ujson.Value, id: String): ujson.Value = {
    val found = n("children").arr.filter(_("id").str == id)
    require(found.size == 1, s"ELAPSED_BINDING_CHILD:$id"); found.head("contract")
  }
  private def field(directory: Path, n: ujson.Value, channel: String, name: String): String = {
    val channels = n("channels").arr.filter(_("id").str == channel)
    require(channels.size == 1, s"ELAPSED_BINDING_CHANNEL:$channel")
    val c = channels.head; val found = c("layout").arr.filter(_("field").str == name)
    require(found.size == 1, s"ELAPSED_BINDING_FIELD:$name")
    val f = found.head
    // Packed metadata anchors live in export probes, not in AsyncTest's DUT.
    // Resolve the actual retained channel port and check its independent ABI.
    val source = s"~|${n("module").str}>$channel.$name"
    require(f("source").str == source, s"ELAPSED_BINDING_SOURCE:$name")
    val nodes = ujson.read(Files.readString(directory.resolve("export/ports.json")))("nodes").arr
      .filter(_("rtl_path").str == n("rtl_path").str)
    require(nodes.size == 1, s"ELAPSED_BINDING_ABI_NODE:$name")
    val ports = nodes.head("ports").arr.filter(_("source").str == source)
    require(ports.size == 1 && ports.head("width") == f("width") &&
      ports.head("signed") == f("signed"), s"ELAPSED_BINDING_ABI_PORT:$name")
    s"${path(n("rtl_path").str)}.${s"$channel.$name".replace('.', '_')}"
  }
  private case class Bindings(capture: String, mode: String, index: String,
      ownerMode: String, ownerIndex: String)
  private def bindings(directory: Path, click: Boolean): Bindings = {
    val root = node(directory); val step = child(root,"step"); val owner = child(root,"owner")
    val found = step("primitives").arr.filter(_("id").str == "payload")
    require(found.size == 1, "ELAPSED_BINDING_STEP_PAYLOAD")
    val payload = found.head
    require(payload("model").str == (if(click) "ChiselAsyncEventRegister_v1" else "ChiselAsyncClosingLatch_v1"),
      "ELAPSED_BINDING_STEP_CAPTURE_KIND")
    Bindings(path(payload("rtl_path").str)+(if(click) ".trigger" else ".closed"),
      field(directory,step,"in","bits.state.mode"), field(directory,step,"in","bits.state.index"),
      field(directory,owner,"out","bits.mode"), field(directory,owner,"out","bits.index"))
  }
  private def hex(value: BigInt): String = "32'h" + value.toString(16)
  private def checks(x: Expected): String = {
    val fields = Seq("reply_bits_state_consumed" -> x.target,
      "reply_bits_single" -> BigInt(if(x.delta == 1) 1 else 0)) ++
      x.fraction.zipWithIndex.map { case(v,i) => s"reply_bits_state_fraction_$i" -> v } ++
      x.elapsed.zipWithIndex.map { case(v,i) => s"reply_bits_elapsed_$i" -> v }
    fields.map { case(name,value) =>
      s"if($name !== ${hex(value)}) $$fatal(1,\"ELAPSED_LOOP_ARITHMETIC:$name\");"
    }.mkString("\n")
  }
  private def observe(b: Bindings): String = s"""
    fork : turn_observer
      begin forever begin
        @(posedge ${b.capture});
        if(!reset && tracking && (${b.mode} == 0 || ${b.mode} == 1)) begin
          if(${b.mode} == 0 && turns != first_turn)
            $$fatal(1,"ELAPSED_LOOP_DUPLICATE_ADMISSION");
          if(${b.mode} == 1 && ${b.index} !== expected_index)
            $$fatal(1,"ELAPSED_LOOP_INDEX");
          expected_index=expected_index-1; turns=turns+1;
        end
      end end
    join_none
    #2;
  """
  private val declarations = """
    integer turns=0, first_turn=0, expected_index=0;
    reg tracking=0;
  """
  private def transactions(click: Boolean, xs: Seq[Expected], stall: Boolean = true): String =
    xs.zipWithIndex.map { case(x,i) =>
      val phase = if(click) (i+1)%2 else 1
      s"""
        first_turn=turns; expected_index=${x.turns-1}; tracking=1;
        command_bits=${hex(x.target)}; #2; command_req=$phase;
        wait(command_ack == $phase); #2;
        ${if(click) s"command_bits=${hex(x.target ^ mask)};" else "command_req=0;"}
        wait(reply_req == $phase); #2;
        ${checks(x)}
        if(turns-first_turn != ${x.turns} || expected_index != -1)
          $$fatal(1,"ELAPSED_LOOP_TURN_COUNT");
        ${if(stall) s"""
          repeat(3) begin
            #37000000;
            ${checks(x)}
            if(turns-first_turn != ${x.turns}) $$fatal(1,"ELAPSED_LOOP_WORK_DURING_REPLY_STALL");
          end
        """ else ""}
        tracking=0; reply_ack=$phase;
        ${if(click) "#2;" else "wait(!reply_req); #2; reply_ack=0; wait(!command_ack); #2;"}
        ${if(click) "" else s"""
          // Four-phase data stays held through full request/acknowledge return.
          // Poison the idle bus at the earliest legal reuse, before the next offer.
          command_bits=${hex(x.target ^ mask)}; #37000000; ${checks(x)}
        """}
      """
    }.mkString("\n")

  for(click <- Seq(false,true)) {
    val variant = if(click) "click" else "bd"
    test(s"$variant elapsed loop: exact nibble counts, full-width arithmetic, held replies and source reuse") {
      val boundaries = (1 until 8).flatMap { i =>
        val p = BigInt(1) << (4*i); Seq(p-1,p,p+1)
      }
      // Starting with999 then1 exercises a retained999fraction and carry in
      // the1us lane. The original ScalingSpec retains its1000single-tick run.
      val deltas = Seq(BigInt(0),BigInt(999),BigInt(1),BigInt(999),BigInt(1),BigInt(2),BigInt(15)) ++ boundaries ++
        Seq(mask,BigInt(1)<<31,BigInt(0)) ++
        Seq.tabulate(8)(i => BigInt(1) << (4*i)) ++ Seq.fill(20)(BigInt(1))
      for(micros <- Seq(normalMicros, Seq(1000,1000,200000,Int.MaxValue))) {
        val directory = fresh(variant+"-nibbles")
        AsyncTest.run(top(click,micros),1L to 16L,directory) { _ =>
          val b = bindings(directory,click)
          s"""begin : loop_test
            $declarations
            ${if(click) "start=1;" else ""}
            ${observe(b)}
            ${transactions(click,expected(micros,deltas))}
            disable turn_observer;
            #1000000000;
            if(delivered_reply != ${deltas.size}) $$fatal(1,"ELAPSED_LOOP_EXACTLY_ONCE");
          end"""
        }
      }
    }

    test(s"$variant elapsed loop: POR at each arithmetic nibble aborts old work and restores fractions") {
      for(index <- 0 until 8) {
        val directory = fresh(variant+s"-por-nibble-$index")
        AsyncTest.run(top(click,normalMicros),Seq(1L,2L,19L),directory) { _ =>
          val b = bindings(directory,click)
          val selected = if(index == 7) s"${b.mode} == 0" else s"${b.mode} == 1 && ${b.index} == $index"
          s"""begin : reset_test
            $declarations
            ${if(click) "start=1;" else ""}
            command_bits=32'hffffffff; #2; command_req=1;
            begin : wait_selected_nibble
              reg selected_seen; selected_seen=0;
              while(!selected_seen) begin
                @(posedge ${b.capture}); selected_seen=($selected);
              end
            end
            #2;
            if(reply_req) $$fatal(1,"ELAPSED_LOOP_POR_NOT_MID_ARITHMETIC");
            reset=1; command_req=0; reply_ack=0; ${if(click) "start=0;" else ""}
            #1000000000; reset=0; #1000000000;
            if(command_ack || reply_req) $$fatal(1,"ELAPSED_LOOP_STALE_AFTER_POR");
            ${if(click) "start=1;" else ""}
            ${observe(b)}
            ${transactions(click,expected(normalMicros,Seq(BigInt(1),BigInt(2),BigInt(1))))}
            disable turn_observer;
            #1000000000;
          end"""
        }
      }
    }
  }

  test("click elapsed loop: early next command cannot overwrite a parked reply") {
    val xs = expected(normalMicros, Seq(BigInt("12345678",16),BigInt(1),BigInt("10000",16)))
    val directory = fresh("click-early-next")
    AsyncTest.run(top(true,normalMicros),1L to 16L,directory) { _ => s"""
      start=1;
      command_bits=${hex(xs(0).target)}; #2; command_req=1; wait(command_ack); #2;
      command_bits=${hex(xs(1).target)}; #2; command_req=0;
      wait(reply_req); #2;
      repeat(8) begin
        #23000000;
        ${checks(xs(0))}
        if(!command_ack) $$fatal(1,"ELAPSED_LOOP_EARLY_NEXT_ACCEPTED");
      end
      reply_ack=1; wait(!command_ack); wait(!reply_req); #2; ${checks(xs(1))}
      command_bits=${hex(xs(2).target)}; #2; command_req=1;
      repeat(8) begin #23000000; ${checks(xs(1))}
        if(command_ack) $$fatal(1,"ELAPSED_LOOP_EARLY_NEXT_ACCEPTED");
      end
      reply_ack=0; wait(command_ack); wait(reply_req); #2; ${checks(xs(2))}
      reply_ack=1; #1000000000;
      if(delivered_reply != 3) $$fatal(1,"ELAPSED_LOOP_EARLY_NEXT_COUNT");
    """ }
  }

  test("bd elapsed loop: independent command and reply return stalls retain payload and admission") {
    val xs = expected(normalMicros, Seq(BigInt(1),BigInt("10000000",16)))
    val directory = fresh("bd-external-return")
    AsyncTest.run(top(false,normalMicros),1L to 16L,directory) { _ =>
      xs.zipWithIndex.map { case(x,i) => s"""
        command_bits=${hex(x.target)}; #2; command_req=1;
        wait(command_ack); wait(reply_req); #2; ${checks(x)}
        reply_ack=1; wait(!reply_req); #2;
        ${if(i == 0) "reply_ack=0;" else "command_req=0;"}
        repeat(8) begin #23000000; ${checks(x)}
          if(!command_ack || reply_req) $$fatal(1,"ELAPSED_LOOP_EARLY_BD_RETURN");
        end
        ${if(i == 0) "command_req=0;" else "reply_ack=0;"}
        wait(!command_ack); #2;
      """ }.mkString("\n") + "#1000000000; if(delivered_reply != 2) $fatal(1,\"ELAPSED_LOOP_RETURN_COUNT\");"
    }
  }

  for(heldCommand <- Seq(false,true))
    test(s"bd elapsed loop: POR while ${if(heldCommand) "command" else "reply"} return remains outstanding") {
      val directory = fresh("bd-por-return")
      AsyncTest.run(top(false,normalMicros),Seq(1L,2L,19L),directory) { _ =>
        val b=bindings(directory,false)
        s"""begin : return_reset_test
          $declarations
          command_bits=32'h12345678; #2; command_req=1;
          wait(command_ack); wait(reply_req); #2; reply_ack=1;
          wait(!reply_req); #2;
          ${if(heldCommand) "reply_ack=0;" else "command_req=0;"}
          wait(${b.ownerMode} == 3); #17000000;
          if(!command_ack || reply_req) $$fatal(1,"ELAPSED_LOOP_POR_NOT_HELD_RETURN");
          reset=1; command_req=0; reply_ack=0;
          #1000000000; reset=0; #1000000000;
          if(command_ack || reply_req) $$fatal(1,"ELAPSED_LOOP_RETURN_SURVIVED_POR");
          ${observe(b)}
          ${transactions(false,expected(normalMicros,Seq(BigInt(1),BigInt(999),BigInt(1))))}
          disable turn_observer;
          #1000000000;
        end"""
      }
    }

  for(replyFalling <- Seq(true,false))
    test(s"bd elapsed loop: POR during ${if(replyFalling) "reply" else "command"} withdrawal cancels history") {
      val directory = fresh(if(replyFalling) "bd-por-reply-fall" else "bd-por-command-fall")
      AsyncTest.run(top(false,normalMicros),Seq(1L,2L,19L),directory) { _ =>
        val b=bindings(directory,false)
        s"""begin : withdrawal_reset_test
          $declarations
          command_bits=32'h12345678; #2; command_req=1;
          wait(command_ack); wait(reply_req); #2; reply_ack=1;
          ${if(replyFalling) "#2; if(!reply_req) $fatal(1,\"ELAPSED_LOOP_POR_NOT_REPLY_WITHDRAWAL\");"
            else "wait(!reply_req); #2; command_req=0; reply_ack=0; #2; if(!command_ack) $fatal(1,\"ELAPSED_LOOP_POR_NOT_COMMAND_WITHDRAWAL\");"}
          reset=1; command_req=0; reply_ack=0;
          #1000000000; reset=0; #1000000000;
          if(command_ack || reply_req) $$fatal(1,"ELAPSED_LOOP_WITHDRAWAL_SURVIVED_POR");
          ${observe(b)}
          ${transactions(false,expected(normalMicros,Seq(BigInt(1),BigInt(999),BigInt(1))))}
          disable turn_observer;
          #1000000000;
        end"""
      }
    }

  test("click elapsed loop: POR cancels a held phase-zero reply") {
    val directory=fresh("click-por-phase-zero")
    val before=expected(normalMicros,Seq(BigInt(1),BigInt(1)))
    AsyncTest.run(top(true,normalMicros),Seq(1L,2L,19L),directory) { _ =>
      val b=bindings(directory,true)
      s"""begin : zero_phase_reset_test
        $declarations
        start=1; command_bits=1; #2; command_req=1;
        wait(command_ack); wait(reply_req); #2; ${checks(before(0))} reply_ack=1;
        #2; command_bits=2; #2; command_req=0;
        wait(!command_ack); wait(!reply_req); #2; ${checks(before(1))}
        if(!reply_ack) $$fatal(1,"ELAPSED_LOOP_POR_NOT_HELD_PHASE_ZERO");
        #37000000;
        reset=1; command_req=0; reply_ack=0; start=0;
        #1000000000; reset=0; #1000000000;
        if(command_ack || reply_req) $$fatal(1,"ELAPSED_LOOP_PHASE_ZERO_SURVIVED_POR");
        start=1;
        ${observe(b)}
        ${transactions(true,expected(normalMicros,Seq(BigInt(1),BigInt(999),BigInt(1))))}
        disable turn_observer;
        #1000000000;
      end"""
    }
  }
}
