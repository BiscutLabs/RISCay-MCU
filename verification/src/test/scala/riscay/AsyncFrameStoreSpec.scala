// SPDX-License-Identifier: Apache-2.0
package riscay

import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.testing.AsyncTest
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite

/** The payload owner has no periodic clock. The testbench models the original
  * offer O and admission A separately: copy ACK never postpones A=O+100 ns.
  * Its independent two-credit ledger releases a credit only at destination D.
  * Four physical banks therefore do not give the producer four logical credits.
  */
class AsyncFrameStoreSpec extends AnyFunSuite {
  private def top(click: Boolean): AsyncModule = if(click)
    new riscay.click.ClickFrameStore(new ResetDomain("root"))
    else new riscay.bd.FourPhaseFrameStore(new ResetDomain("root"))
  private def fresh(label: String): Path = {
    val root=Paths.get("build/async-frame-store-tests"); Files.createDirectories(root)
    Files.createTempDirectory(root,label)
  }
  private final class Ports(context: AsyncTest.Context) {
    val banks=context.channels.filterNot(_=="in").sorted
    require(banks.size==4 && context.channels.contains("in"),"FRAME_STORE_CHANNEL_INVENTORY")
    private val leaves=context.ports.filter(_.name.startsWith("in_bits_")).sortBy(_.name)
    require(leaves.map(_.width).sum==337,"FRAME_STORE_PAYLOAD_WIDTH")
    def packed(channel: String): String = leaves.map { p =>
      val name=channel+p.name.drop(2)
      require(context.ports.exists(q => q.name==name && q.width==p.width),"FRAME_STORE_LEAF_SCHEMA")
      name
    }.mkString("{",",","}")
    def available(i: Int): String = {
      val name=s"available_$i"
      require(context.ports.exists(p => p.name==name && p.width==1),"FRAME_STORE_AVAILABLE_SCHEMA")
      name
    }
    def cases(index: String)(f: (String,Int) => String): String =
      s"case($index)\n"+banks.zipWithIndex.map { case(p,i) => s"$i: begin ${f(p,i)} end" }.mkString("\n")+
        "\ndefault: $fatal(1,\"FRAME_STORE_BANK_INDEX\"); endcase\n"
  }
  private final class Pins(directory: Path) {
    private val root=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    def apply(id: String): String = {
      val parts=id.split('.').toList
      def descend(node: ujson.Value, path: List[String]): ujson.Value = path match {
        case cell :: Nil => node("primitives").arr.find(_("id").str==cell).getOrElse(
          throw new IllegalArgumentException("FRAME_STORE_CAPTURE_PIN_MISSING: "+id))
        case child :: tail => descend(node("children").arr.find(_("id").str==child).get("contract"),tail)
        case _ => throw new IllegalArgumentException("FRAME_STORE_CAPTURE_PIN_EMPTY")
      }
      "dut."+descend(root,parts)("rtl_path").str.split('.').drop(1).mkString(".")
    }
  }
  /** Actual primitive D/trigger/closed/Q pins, including all unselected Click
    * self-feedback inputs. Reset exemptions belong to the measured register.
    * The 100 ps aperture is a digital experiment, not physical qualification.
    */
  private def captureMonitors(directory: Path, click: Boolean): String = {
    val pin=new Pins(directory)
    val registers=if(click) (0 until 4).flatMap(i => Seq((s"payload$i",337),(s"phase$i",1))) :+ ("route" -> 2)
      else Seq("route"->2)
    val events=registers.map { case(id,width) =>
      val p=pin(id)
      s"""begin : monitor_$id
        time rise=0,fall=0,change=0,last_reset=0,check_at=0;
        bit rose=0,fell=0,seen=0;
        reg [${width-1}:0] captured;
        fork
          forever begin @(posedge reset); last_reset=$$time;rose=0;fell=0;seen=0; end
          forever begin @(posedge $p.trigger); if(!$p.reset) begin
            if(fell && $$time-fall<=100000) $$fatal(1,"FRAME_STORE_PULSE_LOW_$id");
            if(seen && $$time-change<=100000) $$fatal(1,"FRAME_STORE_SETUP_$id");
            rise=$$time;rose=1;
          end end
          // Delayed Q observation must not block the pulse/setup observer.
          forever begin @(posedge $p.trigger); if(!$p.reset) begin
            check_at=$$time;captured=$p.d;#10000001;
            if(!$p.reset && last_reset<check_at && $p.q!==captured) $$fatal(1,"FRAME_STORE_CAPTURE_$id");
          end end
          forever begin @(negedge $p.trigger); if(!$p.reset && rose) begin
            if($$time-rise<=100000) $$fatal(1,"FRAME_STORE_PULSE_HIGH_$id");fall=$$time;fell=1;
          end end
          forever begin @($p.d); if(!$p.reset) begin
            if(rose && $$time-rise<=100000) $$fatal(1,"FRAME_STORE_HOLD_$id");change=$$time;seen=1;
          end end
        join
      end"""
    }
    val extra=if(click) {
      val common=pin("capture")+".q"
      val accepted=pin("accepted_phase")
      val destinations=(registers.map { case(id,_) => pin(id)+".trigger" } :+ (pin("accepted_phase")+".trigger"))
      s"""begin : capture_distribution
        forever begin @($common); #1;
          if(!reset && {${destinations.mkString(",")}}!=={10{$common}})
            $$fatal(1,"FRAME_STORE_CAPTURE_DISTRIBUTION");
        end
      end
      begin : accepted_phase_pulse
        time rise=0,fall=0,last_reset=0,check_at=0;bit rose=0,fell=0,expected_phase;
        fork
          forever begin @(posedge reset);last_reset=$$time;rose=0;fell=0;end
          forever begin @(posedge $accepted.trigger);if(!$accepted.reset) begin
            if(fell && $$time-fall<=100000) $$fatal(1,"FRAME_STORE_PULSE_LOW_accepted_phase");
            rise=$$time;rose=1;
          end end
          forever begin @(posedge $accepted.trigger);if(!$accepted.reset) begin
            check_at=$$time;expected_phase=~$accepted.q;#10000001;
            if(!$accepted.reset && last_reset<check_at && $accepted.q!==expected_phase)
              $$fatal(1,"FRAME_STORE_CAPTURE_accepted_phase");
          end end
          forever begin @(negedge $accepted.trigger);if(!$accepted.reset && rose) begin
            if($$time-rise<=100000) $$fatal(1,"FRAME_STORE_PULSE_HIGH_accepted_phase");
            fall=$$time;fell=1;
          end end
        join
      end"""
    } else (0 until 4).map { i =>
      val p=pin(s"storage$i.payload")
      s"""begin : latch_$i
        time close_time=0,change=0,last_reset=0,check_at=0; bit closed=0,seen=0;
        reg [336:0] captured;
        fork
          forever begin @(posedge reset);last_reset=$$time;closed=0;seen=0;end
          forever begin @(posedge $p.closed);if(!$p.reset) begin
            if(seen && $$time-change<=100000) $$fatal(1,"FRAME_STORE_LATCH_SETUP_$i");
            close_time=$$time;closed=1;
          end end
          forever begin @(posedge $p.closed);if(!$p.reset) begin
            check_at=$$time;captured=$p.d;#10000001;
            if(!$p.reset && last_reset<check_at && $p.closed && $p.q!==captured)
              $$fatal(1,"FRAME_STORE_LATCH_CAPTURE_$i");
          end end
          forever begin @($p.d);if(!$p.reset) begin
            if(closed && $$time-close_time<=100000) $$fatal(1,"FRAME_STORE_LATCH_HOLD_$i");
            change=$$time;seen=1;
          end end
        join
      end"""
    }.mkString("\n")
    s"fork\n${events.mkString("\n")}\n$extra\njoin_none\n"
  }
  private def consume(ports: Ports, click: Boolean, index: String, holdReturn: Long): String =
    ports.cases(index) { (p,i) => s"""
      wait(${p}_req === expected_phase[$i]); #2;
      if(!pending[$i] || ${ports.packed(p)}!==expected[$i]) $$fatal(1,"FRAME_STORE_DESTINATION_IDENTITY_$i");
      ${p}_ack=expected_phase[$i];pending[$i]=0;logical_count=logical_count-1;
      if(logical_count<0 || logical_count>2) $$fatal(1,"FRAME_STORE_LOGICAL_CREDIT_RELEASE");
      #2;
      ${if(click) "" else s"""wait(!${p}_req);#$holdReturn;
        if(${ports.available(i)} || ${ports.packed(p)}!==expected[$i]) $$fatal(1,"FRAME_STORE_FULL_RETURN_$i");
        ${p}_ack=0;#2;"""}
    """ }

  for(click <- Seq(false,true)) {
    val name=if(click) "click" else "bd"
    test(s"$name native frame banks: all 337 bits, independent phases, earliest source reuse and two-credit rotation") {
      val directory=fresh(name+"-rotation")
      AsyncTest.run(top(click),1L to 24L,directory) { context =>
        val ports=new Ports(context); val pin=new Pins(directory)
        val frames=32+4*(2+2*337)
        val snapshots=ports.banks.zipWithIndex.map { case(p,i) =>
          s"snapshot[$i]=${ports.packed(p)};"
        }.mkString("\n")
        val unselected=if(click) ports.banks.zipWithIndex.map { case(p,i) =>
          s"""if(bank!=$i && ${ports.packed(p)}!==snapshot[$i]) $$fatal(1,"FRAME_STORE_UNSELECTED_PAYLOAD_$i");
            if(${pin(s"phase$i")}.q!==expected_phase[$i]) $$fatal(1,"FRAME_STORE_UNSELECTED_PHASE_$i");"""
        }.mkString("\n") else ""
        val copyCounters=if(click) s"""begin forever begin @(posedge ${pin("payload0")}.trigger);
          if(!reset) begin copy_count[nextBank]=copy_count[nextBank]+1;global_copies=global_copies+1;end
        end end""" else (0 until 4).map { i => s"""begin forever begin
          @(posedge ${pin(s"storage$i.payload")}.closed);
          if(!reset) begin copy_count[$i]=copy_count[$i]+1;global_copies=global_copies+1;end
        end end""" }.mkString("\n")
        val copyCheck=ports.cases("bank") { (p,i) => s"""
          if(${ports.packed(p)}!==value || ${ports.available(i)}) $$fatal(1,"FRAME_STORE_COPY_AT_A_$i");
          ${if(click) s"if(${pin(s"phase$i")}.q!==expected_phase[$i]) $$fatal(1,\"FRAME_STORE_INDEPENDENT_BANK_PHASE_$i\");" else ""}
        """ }
        val sourceReturn=if(click) s"${ports.packed("in")}=~value;" else s"""
          // Native route retains the selected bank while the old publisher REQ is high.
          // It retains data through the source's complete return, then reuses it.
          #110999998;in_req=0;wait(!in_ack);#2;${ports.packed("in")}=~value;
        """
        val finish=ports.banks.zipWithIndex.map { case(p,i) => s"""
          if(delivered_$p!=${frames/4} || !${ports.available(i)}) $$fatal(1,"FRAME_STORE_BANK_COUNT_$i");
        """ }.mkString("\n")
        s"""begin : rotation
          reg [336:0] expected[0:3],snapshot[0:3],value;
          reg [3:0] expected_phase=0,pending=0;
          integer n,bank,previous,bit_index,logical_count=0,global_copies=0;
          integer copy_count[0:3];
          time offered_at=0,next_offer=0;
          for(n=0;n<4;n=n+1) copy_count[n]=0;
          ${captureMonitors(directory,click)}
          fork $copyCounters join_none
          #100000000;
          for(n=0;n<$frames;n=n+1) begin
            bank=n%4;previous=(n+3)%4;
            if(nextBank!==bank) $$fatal(1,"FRAME_STORE_NATIVE_ROUTE_ORDINAL");
            if(n>0) begin
              if($$time+1000000>next_offer) $$fatal(1,"FRAME_STORE_EARLIEST_REUSE_BUDGET");
              #(next_offer-$$time-1000000);
            end
            ${ports.cases("bank") { (_,i) => s"if(!${ports.available(i)} || pending[$i]) $$fatal(1,\"FRAME_STORE_ROTATION_AVAILABILITY_$i\");" }}
            // Distinct identities and repeated identical complete frames precede
            // the bit campaigns. Copy counters use native events, not payloads.
            if(n<16) value=337'h143597bdf02468ace123456789abcdef01234567890abcdef01234567890abcdef1234567890abcdef01234567 ^ (337'b1<<(n*19)) ^ n;
            else if(n<32) value=337'h17af053912468acef02468acf13579bdf01234567890abcdef01234567890abcdef01234567890abcdef12345;
            else if(n<36) value=0;
            else if(n<40) value={337{1'b1}};
            else begin
              bit_index=(n-40)/8;
              value=337'b1<<bit_index;
              if(((n-40)/4)%2) value=~value;
            end
            $snapshots
            expected[bank]=value;expected_phase[bank]=${if(click) "~expected_phase[bank]" else "1'b1"};
            ${ports.packed("in")}=value;#1000000;offered_at=$$time;
            ${ports.cases("bank") { (_,i) => s"if(!${ports.available(i)} || copy_count[$i]!=n/4) $$fatal(1,\"FRAME_STORE_ORIGINAL_O_AVAILABILITY_$i\");" }}
            if(global_copies!=n) $$fatal(1,"FRAME_STORE_ORIGINAL_O_COPY_ORDINAL");
            in_req=${if(click) "~in_req" else "1'b1"};
            // A is fixed independently of the copy handshake. A late copy fails.
            #100000000;
            if(in_ack!==in_req || delivered_in!=n+1) $$fatal(1,"FRAME_STORE_COPY_MISSED_ORIGINAL_A");
            if(copy_count[bank]!=n/4+1 || global_copies!=n+1) $$fatal(1,"FRAME_STORE_ONE_NEW_COPY_PER_OFFER");
            $copyCheck
            $unselected
            pending[bank]=1;logical_count=logical_count+1;
            if(logical_count<1 || logical_count>2) $$fatal(1,"FRAME_STORE_TWO_LOGICAL_CREDITS");
            if(nextBank!==(bank+1)%4) $$fatal(1,"FRAME_STORE_NATIVE_ROUTE_ADVANCE");#2;
            fork
              begin $sourceReturn end
              begin if(n>0) begin #10000000;${consume(ports,click,"previous",120000000L)} end end
            join
            next_offer=offered_at+${if(click) 214000000L else 600000000L};
          end
          #10000000;
          ${consume(ports,click,"bank",120000000L)}
          #1000000000;
          if(logical_count!=0 || pending!=0 || busy || delivered_in!=$frames || global_copies!=$frames)
            $$fatal(1,"FRAME_STORE_ROTATION_DRAIN");
          $finish
          $$display("FRAME_STORE_ROTATION frames=$frames per_bank=${frames/4} width=337 max_logical_credits=2");
        end"""
      }
    }
    for(resetAt <- Seq("route","captured","offered","acknowledged","return")) {
      test(s"$name native frame banks: POR at $resetAt cancels old phases and permits fresh rotation") {
        val directory=fresh(name+"-por-"+resetAt)
        AsyncTest.run(top(click),Seq(1L,2L,7L,19L),directory) { context =>
          val ports=new Ports(context);val pin=new Pins(directory);val p=ports.banks.head
          val copyCounters=if(click) s"""begin forever begin @(posedge ${pin("payload0")}.trigger);
            if(!reset) global_copies=global_copies+1;
          end end""" else (0 until 4).map { i => s"""begin forever begin
            @(posedge ${pin(s"storage$i.payload")}.closed);if(!reset) global_copies=global_copies+1;
          end end""" }.mkString("\n")
          val point=resetAt match {
            case "route" => s"@(posedge ${pin(if(click) "pending" else "route")}.${if(click) "q" else "trigger"});#2;"
            case "captured" => s"@(posedge ${pin(if(click) "payload0" else "storage0.payload")}.${if(click) "trigger" else "closed"});#2;"
            case "offered" => s"wait(${p}_req);#2;"
            case "acknowledged" => s"wait(${p}_req);#20000000;${p}_ack=1;#2;"
            case "return" => if(click) s"wait(${p}_req);#20000000;${p}_ack=1;#120000000;"
              else s"wait(${p}_req);#20000000;${p}_ack=1;wait(!${p}_req);#2;"
          }
          val resetInputs=ports.banks.map(p=>s"${p}_ack=0;").mkString("\n")
          val resetCheck=ports.banks.zipWithIndex.map { case(p,i) =>
            s"if(${p}_req || ${p}_ack || !${ports.available(i)}) $$fatal(1,\"FRAME_STORE_POR_QUIET_$i\");"
          }.mkString("\n")
          val fresh=(0 until 12).map { n =>
            val i=n%4;val b=ports.banks(i);val phase=if(click) (n/4+1)%2 else 1
            val inputPhase=if(click) (n+1)%2 else 1
            val value=(BigInt(1)<<336) ^ (BigInt(1)<<(n*23)) ^ BigInt(0x83a7+n)
            s"""
              if(nextBank!==$i) $$fatal(1,"FRAME_STORE_POR_ROUTE_ORDINAL");${ports.packed("in")}=337'h${value.toString(16)};#1000000;
              if(!${ports.available(i)} || global_copies-base_copies!=$n) $$fatal(1,"FRAME_STORE_POR_ORIGINAL_O");
              in_req=$inputPhase;
              #100000000;
              if(in_ack!==$inputPhase || ${ports.packed(b)}!==337'h${value.toString(16)} ||
                  global_copies-base_copies!=${n+1})
                $$fatal(1,"FRAME_STORE_POR_FRESH_COPY");
              if(nextBank!==${(i+1)%4}) $$fatal(1,"FRAME_STORE_POR_ROUTE_ADVANCE");
              fork
                begin ${if(click) s"#2;${ports.packed("in")}=0;" else "#111000000;in_req=0;wait(!in_ack);#2;"} end
                begin wait(${b}_req===$phase);#20000000;
                  if(${ports.packed(b)}!==337'h${value.toString(16)}) $$fatal(1,"FRAME_STORE_POR_FRESH_IDENTITY");
                  ${b}_ack=$phase;#2;
                  ${if(click) "" else s"wait(!${b}_req);#20000000;${b}_ack=0;"}
                end
              join
              #500000000;
            """
          }.mkString("\n")
          s"""begin : por_test
            integer base_in,base_bank0,base_bank1,base_bank2,base_bank3,global_copies=0,base_copies;
            ${captureMonitors(directory,click)}
            fork $copyCounters join_none
            ${ports.packed("in")}={337{1'b1}};#1000000;
            if(!${ports.available(0)} || global_copies!=0) $$fatal(1,"FRAME_STORE_POR_FIRST_O");
            fork
              begin in_req=1;#211000000;
                ${if(click) "" else "in_req=0;"}
              end
              begin $point reset=1;in_req=0;$resetInputs end
            join
            #1000000000;reset=0;#1000000000;
            if(in_ack || busy) $$fatal(1,"FRAME_STORE_POR_STALE_OWNER");
            $resetCheck
            base_in=delivered_in;base_copies=global_copies;
            ${ports.banks.zipWithIndex.map { case(b,i) => s"base_bank$i=delivered_$b;" }.mkString("\n")}
            $fresh
            if(delivered_in-base_in!=12 || busy) $$fatal(1,"FRAME_STORE_POR_INPUT_COUNT");
            ${ports.banks.zipWithIndex.map { case(b,i) => s"if(delivered_$b-base_bank$i!=3 || !${ports.available(i)}) $$fatal(1,\"FRAME_STORE_POR_BANK_COUNT_$i\");" }.mkString("\n")}
          end"""
        }
      }
    }
  }
}
