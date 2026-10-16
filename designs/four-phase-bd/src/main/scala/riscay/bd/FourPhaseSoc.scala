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
    executeTiming: BundledTiming = OwnerTiming.execute, owners: OwnerTiming = OwnerTiming())
    extends FourPhasePlatform(p, board, clockedCpuResponse=false, owners=owners) {
  require(Seq(timing,executeTiming).forall(t =>
    (Seq(t.matchedDelay.fs,t.outputDelay.fs,t.dataDelay.max.fs,t.latchDelay.max.fs) ++
      t.controls.values.map(_.max.fs)).forall(_ <= ApplicationResetContract.digitalDelayLimitFs)),
    "custom stage timing exceeds supported digital timing-policy limit")
  val core = asyncChild("core")(d => new FourPhaseCore(d, timing=timing, executeTiming=executeTiming))
  val transactions = asyncChild("transactions")(d => new FourPhaseFabric(p.config, timing, d))
  val requestBridge = asyncChild("request_bridge")(d => new FourPhaseQuiescingReceipt(new MemoryRequest,d))
  transactions.reset:=nativeApplicationReset.asAsyncReset
  core.reset:=nativeCoreReset.asAsyncReset
  closeBridge(requestBridge)
  requestClosed:=requestBridge.closed; requestRebased:=requestBridge.rebased; requestRebaseIdle:= !requestBridge.rebased
  requestBridge.clock := serviceClock
  FourPhase.connect(transactions.request, core.request); FourPhase.connect(core.response, transactions.response)
  FourPhase.connect(requestBridge.in, transactions.serviceRequest)
  FourPhase.connect(transactions.serviceResponse, completion.response)
  fabric.io.request <> requestBridge.out
  trace := core.trace; trace.valid := core.trace.valid && !applicationIsolation
  traceEvent := core.traceEvent && !applicationIsolation
}
object EmitFourPhaseSoc extends App {
  require(args.length == 1, "Usage: EmitFourPhaseSoc output-directory")
  val p = SocParameters(Groundlark.configuration, staleMs = 3000, watchdogCycles = 32, watchdogHoldCycles = 2,
    adc = Some(AdcParameters(intervalCycles = 10000000)), lowPower = Some(LowPowerParameters.gf180Slow))
  ExportDesign.emit(new FourPhaseSoc(p, p => new GroundlarkBoard(p, PowerPolicy())), Paths.get(args(0)))
  SramInventory.write(Paths.get(args(0)), p.config)
  ChipWrapper.write(Paths.get(args(0)), p.lowPower.get)
}
