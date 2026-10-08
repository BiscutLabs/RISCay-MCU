// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chiselasync.metadata.{ClickTiming, ExportDesign, ModelTime}
import chiselasync.protocol.TwoPhase
import java.nio.file.Paths
import riscay.soc._
import riscay.profiles._
import riscay._

class ClickSoc(p: SocParameters, board: SocParameters => BoardController = p => new GenericBoard(p),
    timing: ClickTiming = ClickTiming.Simulation,
    executeData: ModelTime = RegisterTiming.executeData)
    extends SocTop(p, board) {
  val core = asyncChild("core")(d => new ClickCore(d, timing=timing, executeData=executeData))
  val requestBridge = asyncChild("request_bridge")(d => new ClickToDecoupled(new MemoryRequest, d))
  val responseBridge = asyncChild("response_bridge")(d => new DecoupledToClick(new MemoryResponse, d))
  Seq(core, requestBridge, responseBridge).foreach(_.reset := systemReset.asAsyncReset)
  requestBridge.clock := serviceClock; responseBridge.clock := serviceClock
  core.start := !systemReset
  TwoPhase.connect(requestBridge.in, core.request); TwoPhase.connect(core.response, responseBridge.out)
  fabric.io.request <> requestBridge.out; responseBridge.in <> fabric.io.response
  trace := core.trace; traceEvent := core.traceEvent
}
object EmitClickSoc extends App {
  require(args.length == 1, "Usage: EmitClickSoc output-directory")
  val p = SocParameters(Groundlark.configuration, staleMs = 3000, watchdogCycles = 32, watchdogHoldCycles = 2,
    adc = Some(AdcParameters(intervalCycles = 10000000)), lowPower = Some(LowPowerParameters.gf180Slow))
  ExportDesign.emit(new ClickSoc(p, p => new GroundlarkSupervisor(p, PowerPolicy())), Paths.get(args(0)))
  SramInventory.write(Paths.get(args(0)), p.config)
  ChipWrapper.write(Paths.get(args(0)), p.lowPower.get)
}
