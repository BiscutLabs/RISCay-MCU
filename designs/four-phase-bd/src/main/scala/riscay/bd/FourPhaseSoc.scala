// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chiselasync.clocked.FourPhaseToDecoupled
import chiselasync.metadata.{BundledTiming, ExportDesign}
import chiselasync.protocol.FourPhase
import java.nio.file.Paths
import riscay._
import riscay.soc._
import riscay.profiles._

class FourPhaseSoc(p: SocParameters, board: SocParameters => BoardProfile = p => new GenericBoard(p),
    timing: BundledTiming = BundledTiming.Simulation,
    executeTiming: BundledTiming = BundledTiming.simulation(dataMax=RegisterTiming.executeData))
    extends FourPhasePlatform(p, board, clockedCpuResponse=false) {
  require(Seq(timing,executeTiming).forall(t =>
    (Seq(t.matchedDelay.fs,t.outputDelay.fs,t.dataDelay.max.fs,t.latchDelay.max.fs) ++
      t.controls.values.map(_.max.fs)).forall(_ <= ApplicationResetContract.nativeSettleFs)),
    "custom stage timing exceeds application reset-settlement budget")
  val core = asyncChild("core")(d => new FourPhaseCore(d, timing=timing, executeTiming=executeTiming))
  val transactions = asyncChild("transactions")(d => new FourPhaseFabric(p.config, timing, d))
  val requestBridge = asyncChild("request_bridge")(d => new FourPhaseToDecoupled(new MemoryRequest, 2, d))
  Seq(core, transactions, requestBridge).foreach(_.reset := systemReset.asAsyncReset)
  requestBridge.clock := serviceClock
  FourPhase.connect(transactions.request, core.request); FourPhase.connect(core.response, transactions.response)
  FourPhase.connect(requestBridge.in, transactions.serviceRequest)
  FourPhase.connect(transactions.serviceResponse, completion.response)
  fabric.io.request <> requestBridge.out
  trace := core.trace; traceEvent := core.traceEvent
}
object EmitFourPhaseSoc extends App {
  require(args.length == 1, "Usage: EmitFourPhaseSoc output-directory")
  val p = SocParameters(Groundlark.configuration, staleMs = 3000, watchdogCycles = 32, watchdogHoldCycles = 2,
    adc = Some(AdcParameters(intervalCycles = 10000000)), lowPower = Some(LowPowerParameters.gf180Slow))
  ExportDesign.emit(new FourPhaseSoc(p, p => new GroundlarkBoard(p, PowerPolicy())), Paths.get(args(0)))
  SramInventory.write(Paths.get(args(0)), p.config)
  ChipWrapper.write(Paths.get(args(0)), p.lowPower.get)
}
