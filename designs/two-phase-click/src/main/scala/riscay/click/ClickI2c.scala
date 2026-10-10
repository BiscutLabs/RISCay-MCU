// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ClickTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation, PhaseRegister, XorGate}
import chiselasync.protocol.TwoPhase
import riscay.soc._

/** Native protocol state and serialization. The front owns an eight-slot
  * captured-edge ring; occupied payloads remain immutable until published head
  * Gray returns through its synchronizers. No live wire is a stage payload.
  */
class ClickI2c(address: Int, domain: ResetDomain) extends AsyncModule(domain) {
  val edges=IO(Input(Vec(8,new I2cEdge))); val tailGray=IO(Input(UInt(4.W)))
  val frame=twoPhaseOutput("frame",new I2cFrame)
  val snapshot=twoPhaseOutput("snapshot",UInt(8.W))
  val observed=IO(Output(new I2cState)); dontTouch(observed)
  private val timing=ClickTiming.Simulation
  val start=IO(Input(Bool()))
  private val state=asyncChild("state")(d => new PhaseDecoupledClickBuffer(new I2cState,timing,Some(I2cState.initial),d))
  state.start.get:=start; contract.endpoint("start",start)
  private val update=asyncChild("update")(d => new ClickStage(new I2cWork,new I2cResult,
    (w: I2cWork) => transition(w),timing,d))
  private val fork=asyncChild("fork")(d => new ClickFork(new I2cResult,d))
  private val publication=asyncChild("publication")(d => new I2cPublication(d))
  private val available=tailGray =/= state.out.bits.headGray
  update.in.bits.state:=state.out.bits
  update.in.bits.edge:=edges(state.out.bits.head(2,0))
  // Availability cannot withdraw: the occupied slot and head are retained
  // until this token is captured. Idle parity follows acknowledgement.
  update.in.req:=Mux(available,state.out.req,update.in.ack)
  state.out.ack:=update.in.ack
  TwoPhase.connect(fork.in,update.out)
  state.in.bits:=fork.left.bits.state; state.in.req:=fork.left.req; fork.left.ack:=state.in.ack
  dontTouch(fork.left)
  TwoPhase.connect(publication.in,fork.right)
  TwoPhase.connect(frame,publication.frame); TwoPhase.connect(snapshot,publication.snapshot)
  observed:=publication.observed
  contract.endpoint("reset",reset); contract.endpoint("tail_gray",tailGray)
  private val edgeSlots=WireDefault(UInt((8*(new I2cEdge).getWidth).W),edges.asUInt); dontTouch(edgeSlots)
  private val observedBits=WireDefault(UInt((new I2cState).getWidth.W),observed.asUInt); dontTouch(observedBits)
  contract.endpoint("edge_slots",edgeSlots); contract.endpoint("observed",observedBits)

  private def transition(w: I2cWork): I2cResult = {
    val s = w.state; val e = w.edge
    val r = WireDefault(0.U.asTypeOf(new I2cResult)); r.state := s
    val n = r.state
    n.head := s.head + 1.U
    n.headGray := n.head ^ (n.head >> 1)
    val assembled = Cat(s.receive(6,0), e.sda)
    r.frameValid := !e.timeout && (e.start || e.stop) && s.selectedWrite && s.length =/= 0.U
    r.frame.ingress.frame.length := s.length
    r.frame.ingress.frame.overflow := s.overflow || s.bit > 1.U || s.mode =/= 1.U
    r.frame.ingress.frame.bytes := s.bytes
    r.frame.resetEpoch := e.resetEpoch
    r.frame.ingress.resetActive := e.resetActive; r.frame.ingress.programBusy := e.programBusy
    r.snapshotValid := !e.timeout && s.mode === 1.U && e.rise && s.bit === 7.U &&
      s.addressByte && assembled(7,1) === address.U && assembled(0)
    r.snapshotTag := assembled
    when(e.timeout || e.start || e.stop) {
      n.mode := Mux(e.start && !e.timeout, 1.U, 0.U)
      n.active := e.start && !e.timeout; n.rejected := false.B
      n.addressByte := true.B; n.selectedWrite := false.B; n.reading := false.B
      n.drive := false.B; n.bit := 0.U; n.length := 0.U; n.overflow := false.B
    }.otherwise {
      switch(s.mode) {
        is(1.U) { when(e.rise) {
          n.receive := assembled; n.bit := s.bit + 1.U
          when(s.bit === 7.U) {
            n.mode := 2.U
            when(s.addressByte) {
              n.ack := assembled(7,1) === address.U
              n.rejected := assembled(7,1) =/= address.U
              n.reading := assembled(0)
              n.selectedWrite := assembled(7,1) === address.U && !assembled(0)
              when(assembled(7,1) === address.U && assembled(0)) { n.sent := 0.U }
            }.otherwise {
              n.ack := s.length < 33.U
              when(s.length < 33.U) { n.bytes(s.length) := assembled; n.length := s.length + 1.U }
                .otherwise { n.overflow := true.B }
            }
          }
        } }
        is(2.U) { when(e.fall) { n.drive := s.ack; n.mode := 3.U } }
        is(3.U) { when(e.rise) { n.mode := 4.U } }
        is(4.U) { when(e.fall) {
          n.drive := false.B; n.addressByte := false.B
          when(!s.ack) { n.mode := 0.U; n.active := false.B }
            .elsewhen(s.reading) { n.send := e.readWord; n.drive := !e.readWord(7); n.mode := 5.U }
            .otherwise { n.mode := 1.U }
        } }
        is(5.U) {
          when(e.rise) { n.bit := s.bit + 1.U; when(s.bit === 7.U) { n.mode := 6.U } }
          when(e.fall) { n.drive := !s.send(7,0)(7.U - s.bit) }
        }
        is(6.U) { when(e.fall) { n.drive := false.B; n.mode := 7.U } }
        is(7.U) { when(e.rise) { n.masterAck := !e.sda; n.mode := 8.U } }
        is(8.U) { when(e.fall) {
          when(s.masterAck && s.sent < 35.U) {
            val next = Mux(s.sent(1,0) === 3.U, e.readWord, Cat(0.U(8.W), s.send(31,8)))
            n.send := next; n.sent := s.sent + 1.U; n.drive := !next(7); n.mode := 5.U
          }.otherwise { n.drive := false.B; n.mode := 0.U; n.active := false.B }
        } }
      }
    }
    r
  }
}

/** Native sink/projection and independently held frame/snapshot effects.
  * All event registers share one capture pulse. A held effect never changes
  * payload; a second effect backpressures publication until the old one drains.
  */
class I2cPublication(domain: ResetDomain) extends AsyncModule(domain) {
  val in=twoPhaseInput("in",new I2cResult)
  val frame=twoPhaseOutput("frame",new I2cFrame)
  val snapshot=twoPhaseOutput("snapshot",UInt(8.W))
  val observed=IO(Output(new I2cState)); dontTouch(observed)

  private val resetRef = contract.endpoint("reset", reset)
  private val cell = ModelTime.ps(1000)
  // Conservative composed-control drain bound (1..10 ns cells). Simulation
  // only; characterize the complete feedback/pulse distribution before mapping.
  private val guard = ModelTime.ps(110000)
  private def gate(id: String, op: GateOperation.Value, a: UInt, b: UInt = 0.U,
      width: Int = 1, delay: ModelTime = cell, initial: BigInt = 0): UInt = {
    val g=Module(new ControlGate(width,op,delay,initial)); g.reset:=reset; g.a:=a; g.b:=b
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(op.id),
      "DELAY_FS"->BigInt(delay.fs),"RESET_VALUE"->initial),resetRef,
      "I2C publication control/data; preserved digital bounds, physically unqualified")
    g.q
  }
  private def and(id: String, a: Bool, b: Bool): Bool = {
    val na=gate(id+"_na",GateOperation.Invert,a.asUInt,initial=1)
    val nb=gate(id+"_nb",GateOperation.Invert,b.asUInt,initial=1)
    val either=gate(id+"_or",GateOperation.Or,na,nb,initial=1)
    gate(id,GateOperation.Invert,either).asBool
  }
  private def register(id: String, width: Int): EventRegister = {
    val g=Module(new EventRegister(width,cell)); g.reset:=reset
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"DELAY_FS"->BigInt(cell.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"common local capture pulse; hold through native output acknowledgement")
    g
  }
  private val observation=register("observation",(new I2cState).getWidth)
  private val frameData=register("frame_payload",(new I2cFrame).getWidth)
  private val snapshotData=register("snapshot_payload",8)
  private val delayedRequest=gate("request_delay",GateOperation.Buffer,in.req.asUInt,
    delay=ModelTime.ps(11000)).asBool
  private val accepted=Module(new PhaseRegister(cell)); accepted.reset:=reset
  contract.primitive("accepted_phase",accepted,Map("DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0)),
    resetRef,"native Click parity; toggles once on the common capture pulse")
  private val framePhase=register("frame_phase",1); private val snapshotPhase=register("snapshot_phase",1)
  private val pending=Module(new XorGate(cell)); pending.reset:=reset; pending.a:=delayedRequest; pending.b:=accepted.q
  contract.primitive("pending",pending,Map("DELAY_FS"->BigInt(cell.fs)),resetRef,"native phase comparator")
  private val available=(!in.bits.frameValid || frame.req === frame.ack) &&
    (!in.bits.snapshotValid || snapshot.req === snapshot.ack)
  private val capture=and("capture_gate",pending.q,available)
  accepted.trigger:=capture
  framePhase.trigger:=capture; snapshotPhase.trigger:=capture
  in.ack:=gate("acknowledge_guard",GateOperation.Buffer,accepted.q.asUInt,delay=guard).asBool
  frame.req:=gate("output_guard",GateOperation.Buffer,framePhase.q,delay=guard).asBool
  snapshot.req:=gate("return_guard",GateOperation.Buffer,snapshotPhase.q,delay=guard).asBool
  observation.trigger:=capture; frameData.trigger:=capture; snapshotData.trigger:=capture
  private val stateWidth=(new I2cState).getWidth
  private val frameWidth=(new I2cFrame).getWidth
  private val dataWidth=stateWidth+frameWidth+8+2
  private val dataSources=Cat(in.bits.state.asUInt,
    Mux(in.bits.frameValid,in.bits.frame.asUInt,frameData.q),
    Mux(in.bits.snapshotValid,in.bits.snapshotTag,snapshotData.q),
    (framePhase.q.asBool ^ in.bits.frameValid).asUInt,
    (snapshotPhase.q.asBool ^ in.bits.snapshotValid).asUInt)
  private val data=gate("data_delay",GateOperation.Buffer,dataSources,width=dataWidth,delay=ModelTime.ps(10000))
  framePhase.d:=data(1); snapshotPhase.d:=data(0)
  snapshotData.d:=data(9,2)
  frameData.d:=data(frameWidth+9,10)
  observation.d:=data(dataWidth-1,frameWidth+10)
  observed:=observation.q.asTypeOf(new I2cState)
  frame.bits:=frameData.q.asTypeOf(new I2cFrame); snapshot.bits:=snapshotData.q
  private val captureEvent=WireDefault(capture); dontTouch(captureEvent)
  private val registerData=WireDefault(UInt(dataWidth.W),data); dontTouch(registerData)
  private val capturedData=WireDefault(UInt(dataWidth.W),Cat(observation.q,frameData.q,snapshotData.q,framePhase.q,snapshotPhase.q)); dontTouch(capturedData)
  private val sources=WireDefault(UInt(((new I2cResult).getWidth+frameWidth+8+2).W),
    Cat(in.bits.asUInt,frameData.q,snapshotData.q,framePhase.q,snapshotPhase.q)); dontTouch(sources)
  contract.endpoint("capture",captureEvent); contract.endpoint("register_data",registerData)
  private val observedBits=WireDefault(UInt((new I2cState).getWidth.W),observed.asUInt); dontTouch(observedBits)
  contract.endpoint("observed",observedBits)
  contract.endpoint("sources",sources); contract.endpoint("captured",capturedData)
  contract.dataPathTiming("projection","sources","register_data",BundledTiming.Simulation,
    "complete I2C projection and retained-effect muxes; digital bound only")
  contract.setupHold("projection_aperture","in_request","in_data","register_data","capture","captured",
    ModelTime.ps(100),ModelTime.ps(100))
  contract.capacity(1)
}
