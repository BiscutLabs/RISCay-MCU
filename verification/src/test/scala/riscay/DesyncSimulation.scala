// SPDX-License-Identifier: Apache-2.0
package riscay

import java.nio.file.{Files, Path}
import circt.stage.ChiselStage

/** Explicit digital assumptions; never inputs to STA or physical mapping. */
object DesyncSimulation {
  def sources(base: Path): Seq[String] = {
    val directory=base.resolve("prototype");Files.createDirectories(directory)
    if(!Files.exists(base.resolve("DesyncClock.sv"))) ChiselStage.emitSystemVerilogFile(new riscay.desync.DesyncClock,
      args=Array("--target-dir",directory.toString),
      firtoolOpts=Array("--disable-all-randomization","--strip-fir-debug-info"))
    val models=directory.resolve("desync_models.sv")
    val stream=getClass.getResourceAsStream("/riscay/desync_models.sv")
    try Files.write(models,stream.readAllBytes()) finally stream.close()
    (if(Files.exists(base.resolve("DesyncClock.sv"))) Seq.empty else Seq(directory.resolve("DesyncClock.sv").toString)) :+ models.toString
  }
  def bounds(path: String, halfPeriod: Double): String = s"""
    // SIMULATION ONLY: retain the suite's minimum pulse width; randomize up to
    // 10% above it. These are workload test points, not measured PVT bounds.
    defparam $path.delay.MIN_NS=$halfPeriod;
    defparam $path.delay.MAX_NS=${halfPeriod*1.1};
    defparam $path.mutex.MIN_NS=0.01;
    defparam $path.mutex.MAX_NS=0.1;
  """
  def directClock(halfPeriod: Double, clock: String="serviceClock",
      run: String="clockEnabled && (reset || serviceClockEnable)"): String = s"""
    reg prototypePor=1;
    initial begin #${halfPeriod*3}; prototypePor=0; end
    DesyncClock prototypeClock(.reset(prototypePor),.run($run),.clockOut($clock));
    ${bounds("prototypeClock",halfPeriod)}
  """
}
