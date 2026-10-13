// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ControlGate, EventRegister, GateOperation, PhaseRegister, XorGate}
import riscay.soc.I2cFrame

/** Native two-phase four-bank capture. One global input phase owns the common
  * capture pulse; every bank retains an independent output phase. All banks
  * share the pulse, while unselected data/phase D inputs retain their own Q.
  * There is no global-phase-to-bank mux and no four-phase conversion.
  * The separate original offer receipt must observe O even when a bank is
  * unavailable. The store owns its modulo-four route independently of A;
  * publisher ACK joins native copy and the clocked receipt's acceptance.
  */
class ClickFrameStore(domain: ResetDomain) extends AsyncModule(domain) {
  val in=twoPhaseInput("in",new I2cFrame)
  val nextBank=IO(Output(UInt(2.W)))
  val banks=Seq.tabulate(4)(i => twoPhaseOutput(s"bank$i",new I2cFrame))
  val available=IO(Output(Vec(4,Bool())))
  dontTouch(available)
  val busy=IO(Output(Bool()))
  private val resetRef=contract.endpoint("reset",reset)
  private val cell=ModelTime.ps(1000)
  private def gate(id: String, data: UInt, width: Int, delay: ModelTime): UInt = {
    val g=Module(new ControlGate(width,GateOperation.Buffer,delay)); g.reset:=reset; g.a:=data; g.b:=0.U
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"OP"->BigInt(0),
      "DELAY_FS"->BigInt(delay.fs),"RESET_VALUE"->BigInt(0)),resetRef,
      "frame-bank capture/feedback digital bound; complete physical path unqualified")
    g.q
  }
  private def register(id: String, width: Int): EventRegister = {
    val g=Module(new EventRegister(width,cell)); g.reset:=reset
    contract.primitive(id,g,Map("WIDTH"->BigInt(width),"DELAY_FS"->BigInt(cell.fs),
      "RESET_VALUE"->BigInt(0)),resetRef,"common native capture; unselected bank retains its own payload and phase")
    g
  }
  private val payload=Seq.tabulate(4)(i => register(s"payload$i",337))
  private val phase=Seq.tabulate(4)(i => register(s"phase$i",1))
  private val route=register("route",2)
  nextBank:=route.q
  dontTouch(nextBank)
  private val accepted=Module(new PhaseRegister(cell)); accepted.reset:=reset
  contract.primitive("accepted_phase",accepted,Map("DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0)),
    resetRef,"one input phase per global capture, independent of each bank phase")
  private val delayedRequest=gate("request_delay",in.req.asUInt,1,ModelTime.ps(11000)).asBool
  private val pending=Module(new XorGate(cell)); pending.reset:=reset
  pending.a:=delayedRequest; pending.b:=accepted.q
  contract.primitive("pending",pending,Map("DELAY_FS"->BigInt(cell.fs)),resetRef,"native global phase comparison")
  private val offers=gate("output_guard",Cat(phase.reverse.map(_.q)),4,ModelTime.ps(110000))
  for(i <- 0 until 4) {
    banks(i).req:=offers(i)
    banks(i).bits:=payload(i).q.asTypeOf(new I2cFrame)
    available(i):=phase(i).q.asBool === banks(i).ack && banks(i).req === banks(i).ack
  }
  // Retain the pulse until pending itself returns. Selecting the next bank must
  // not reassert capture while accepted/phase/route Q feedback settles.
  private val capture=Module(new AsymmetricCElement(1,1,0,cell)); capture.reset:=reset
  capture.common:=pending.q.asUInt; capture.rising:=available(route.q).asUInt; capture.falling:=0.U
  contract.primitive("capture",capture,Map("COMMON"->BigInt(1),"RISING"->BigInt(1),"FALLING"->BigInt(0),
    "DELAY_FS"->BigInt(cell.fs),"RESET_VALUE"->BigInt(0),"COMMON_INVERT"->BigInt(0),
    "RISING_INVERT"->BigInt(0),"FALLING_INVERT"->BigInt(0)),resetRef,
    "selected-bank availability authorizes capture; pending alone completes pulse return")
  accepted.trigger:=capture.q
  private val transformed=Cat((route.q+1.U)(1,0),Cat((0 until 4).reverse.map(i => Cat(
    Mux(route.q === i.U,in.bits.asUInt,payload(i).q),
    phase(i).q.asBool ^ (route.q === i.U)))))
  private val data=gate("data_delay",transformed,1354,ModelTime.ps(10000))
  route.trigger:=capture.q; route.d:=data(1353,1352)
  for(i <- 0 until 4) {
    payload(i).trigger:=capture.q; phase(i).trigger:=capture.q
    payload(i).d:=data(i*338+337,i*338+1); phase(i).d:=data(i*338)
  }
  // <=11+10+10+10+32=73 ns from O to guarded copy acknowledgement.
  // A may precede capture. Joined publisher ACK retains its payload until both
  // copy and receipt complete; head validity prevents dispatch before capture.
  in.ack:=gate("acknowledge_guard",accepted.q.asUInt,1,ModelTime.ps(32000)).asBool
  busy:=in.req =/= in.ack || !available.asUInt.andR
  private val sourceBits=WireDefault(UInt(1691.W),Cat(route.q,in.bits.asUInt,
    Cat((0 until 4).reverse.map(i => Cat(payload(i).q,phase(i).q)))))
  private val capturedBits=WireDefault(UInt(1354.W),Cat(route.q,Cat((0 until 4).reverse.map(i => Cat(payload(i).q,phase(i).q)))))
  private val captureEvent=WireDefault(capture.q)
  private val registerDataProbe=WireDefault(UInt(1354.W),data)
  Seq(sourceBits,capturedBits,captureEvent,registerDataProbe).foreach(dontTouch(_))
  contract.endpoint("next_bank",nextBank); contract.endpoint("available",available); contract.endpoint("busy",busy)
  contract.endpoint("sources",sourceBits); contract.endpoint("register_data",registerDataProbe)
  contract.endpoint("captured",capturedBits); contract.endpoint("capture_event",captureEvent)
  contract.dataPathTiming("bank_transform","sources","register_data",BundledTiming.Simulation,
    "full selected source/unselected retained data and phase muxes, including every feedback bit")
  contract.setupHold("bank_aperture","in_request","sources","register_data","capture_event","captured",
    ModelTime.ps(100),ModelTime.ps(100))
  contract.capacity(4)
}
