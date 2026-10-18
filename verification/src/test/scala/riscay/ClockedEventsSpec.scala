// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util.experimental.BoringUtils
import java.nio.file.Files
import org.scalatest.funsuite.AnyFunSuite
import scala.util.Random
import riscay.soc._

/** Inject at the documented six-source commit edge; all real producer paths
  * remain covered by the unchanged GPIO/ADC/housekeeping/host integration tests.
  */
class BdEventFixture(p: SocParameters) extends FabricFixture(p) {
  val injectedEvents=IO(Input(UInt(6.W)))
  BoringUtils.drive(fabric.events):=injectedEvents
  val eventView=IO(Output(UInt(6.W)));eventView:=BoringUtils.bore(fabric.eventPending)
  val eventCut=IO(Output(Bool()));eventCut:=BoringUtils.bore(fabric.mmioObserved)
  val eventCancel=IO(Output(Bool()));eventCancel:=fabric.io.applicationCancel
  val eventArriving=IO(Output(Bool()));eventArriving:=BoringUtils.bore(fabric.observingMmio)
  val eventReplace=IO(Output(Bool()));eventReplace:=BoringUtils.bore(fabric.replaceDeadline)
  val eventClear=IO(Output(Bool()));eventClear:=fabric.io.request.fire &&
    fabric.io.request.bits.operation === 2.U && fabric.io.request.bits.address === (MemoryMap.mmio+12).U &&
    !fabric.io.controlReply.bits.memory.error
}
class ClickEventFixture(p: SocParameters) extends ClickFabricFixture(p) {
  val injectedEvents=IO(Input(UInt(6.W)))
  BoringUtils.drive(fabric.events):=injectedEvents
  val eventView=IO(Output(UInt(6.W)));eventView:=BoringUtils.bore(fabric.eventPending)
  val eventCut=IO(Output(Bool()));eventCut:=BoringUtils.bore(fabric.mmioObserved)
  val eventCancel=IO(Output(Bool()));eventCancel:=fabric.io.applicationCancel
  val eventArriving=IO(Output(Bool()));eventArriving:=BoringUtils.bore(fabric.observingMmio)
  val eventReplace=IO(Output(Bool()));eventReplace:=BoringUtils.bore(fabric.replaceDeadline)
  val eventClear=IO(Output(Bool()));eventClear:=fabric.io.request.fire &&
    fabric.io.request.bits.operation === 2.U && fabric.io.request.bits.address === (MemoryMap.mmio+12).U &&
    !fabric.io.controlReply.bits.memory.error
}

class ClockedEventsSpec extends AnyFunSuite {
  private val p=SocParameters(McuConfiguration(16,16,7,Vector.empty,
    ApplicationProfile(1,1,"event-order",Vector.empty,Vector.empty)),watchdogCycles=10000000)
  private val tasks="""
    reg traceEnabled=0;
    integer edgeCancel,edgeArrive,edgeObserved,edgeMask,edgeClear,edgeReplace,edgeEvents,edgeStore;
    always @(posedge serviceClock) if(traceEnabled) begin
      edgeCancel=eventCancel;edgeArrive=eventArriving;edgeObserved=eventCut;
      edgeMask=request_bits_data & 63;edgeClear=eventClear;edgeReplace=eventReplace;edgeEvents=injectedEvents;
      edgeStore=request_bits_operation==2 && request_bits_address==32'h3000000c;
      #1;$display("EVENT_EDGE %0d %0d %0d %0d %0d %0d %0d %0d %0d",
        edgeCancel,edgeArrive,edgeObserved,edgeStore,edgeMask,edgeClear,edgeReplace,edgeEvents,eventView);
    end
    task offer(input [1:0] op,input [31:0] addr,input [31:0] data);
      begin @(negedge serviceClock);request_valid=1;request_bits_operation=op;
        request_bits_address=addr;request_bits_data=data;request_bits_mask=15;end
    endtask
    task accepted;
      begin @(posedge serviceClock);while(!request_ready) @(posedge serviceClock);#2;request_valid=0;end
    endtask
    task retire;
      begin wait(response_valid);@(negedge serviceClock);response_ready=1;
        @(posedge serviceClock);#2;response_ready=0;end
    endtask
    task clear_all;
      begin offer(2,32'h3000000c,63);accepted();retire();end
    endtask
    task raise_bits(input [5:0] bits,input integer count);
      begin @(negedge serviceClock);injectedEvents=bits;repeat(count) @(posedge serviceClock);
        #2;injectedEvents=0;end
    endtask
  """
  test("both event registers refine the arrival-cutoff oracle and produce identical random histories") {
    val random=new Random(271828)
    val checkpoints=Vector.newBuilder[Int]
    val stimulus=(0 until 96).map { i =>
      val model=new EventReferenceModel
      val before=if(i<6) 1<<i else random.nextInt(64)
      val after=if(i<6) 1<<i else random.nextInt(64)
      val mask=if(i<6) 63 else random.nextInt(64)
      val repeats=1+random.nextInt(4)
      for(_ <- 0 until repeats; bit <- 0 until 6 if (before & (1<<bit))!=0) model.raise(bit)
      val cut=model.arriveClear(mask)
      for(bit <- 0 until 6 if (after & (1<<bit))!=0) model.raise(bit)
      model.commitClear(cut);checkpoints+=model.pending
      s"""
        clear_all();raise_bits($before,$repeats);
        offer(1,32'hdeadbeec,0);accepted();wait(response_valid);
        // Offer behind an owned response. Raise at the first arrival edge and
        // again afterward; every late occurrence must survive the delayed clear.
        offer(2,32'h3000000c,$mask);#${1+random.nextInt(35)};injectedEvents=$after;
        @(posedge serviceClock);#2;injectedEvents=0;
        repeat(${2+random.nextInt(6)}) @(negedge serviceClock);
        raise_bits($after,${1+random.nextInt(3)});
        retire();accepted();retire();
        if(eventView!==${model.pending}) $$fatal(1,"EVENT_ORACLE_CHECKPOINT_$i actual=%d",eventView);
        $$display("EVENT_CHECKPOINT %0d",eventView);
      """
    }.mkString
    val expected=checkpoints.result()
    val histories=Seq(false,true).map { click =>
      val base=ClockedSimulation.run(if(click) new ClickEventFixture(p) else new BdEventFixture(p),
        if(click) "click-event-oracle" else "bd-event-oracle",
        "#100000;clear_all();traceEnabled=1;"+stimulus+"traceEnabled=0;",tasks,deadlineNs=10000000)
      val log=Files.readString(base.resolve("simulation.log"))
      val oracle=new EventReferenceModel
      var cut=Option.empty[EventReferenceModel.Clear]
      for(line <- log.linesIterator if line.startsWith("EVENT_EDGE ")) {
        val a=line.split(" ").drop(1).map(_.toInt)
        if(a(0)!=0) {oracle.beginReset();cut=None}
        else {
          oracle.endReset()
          if(a(1)!=0 && a(2)==0 && a(3)!=0) cut=Some(oracle.arriveClear(a(4)))
          if(a(6)!=0) oracle.replaceDeadline()
          for(bit <- 0 until 6 if (a(7)&(1<<bit))!=0) oracle.raise(bit)
          if(a(5)!=0) {oracle.commitClear(cut.getOrElse(fail("clear without arrival")));cut=None}
        }
        assert(oracle.pending==a(8),s"$base $line expected=${oracle.pending}")
      }
      val history=log.linesIterator.filter(_.startsWith("EVENT_CHECKPOINT ")).map(_.split(" ")(1).toInt).toVector
      assert(history==expected);history
    }
    assert(histories.head==histories.last)
  }
}
