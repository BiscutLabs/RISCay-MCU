// SPDX-License-Identifier: Apache-2.0
package riscay.desync

import java.nio.file.{Files, Path}
import circt.stage.ChiselStage

/** Preserve the reference's ideal-clock region and replace the source at the
  * existing chip boundary. This also keeps generator abstraction explicit for
  * sequential equivalence; no clock is hidden inside a datapath module.
  */
object DesyncChip {
  def write(base: Path): Unit = {
    val metadata=ujson.read(Files.readString(base.resolve("desync.json")))
    val ports=ujson.read(Files.readString(base.resolve("ports.json")))("nodes")(0)("ports").arr
    def name(p: ujson.Value): String=p("source").str.split('>').last.replace('.', '_').replace('[', '_').replace("]", "")
    val internal=Set("serviceClock","serviceClockEnable","watchdogClock")
    val declarations=ports.filter(p => !internal(name(p))).map(p =>
      s"${p("direction").str} wire [${p("width").num.toInt-1}:0] ${name(p)}")
    val connections=ports.map(p => s".${name(p)}(${name(p) match {
      case "reset" => "~porReleased"
      case n => n
    }})")
    val chip=base.resolve("chip");Files.createDirectories(chip)
    ChiselStage.emitSystemVerilogFile(new DesyncClock,
      args=Array("--target-dir",chip.toAbsolutePath.toString),
      firtoolOpts=Array("--disable-all-randomization","--strip-fir-debug-info"))
    // Existing reset-hold state is unchanged. Power-on clocks must run while
    // reset is held, so the generator itself resets on !powerGood, not CPU POR.
    Files.writeString(chip.resolve("DesyncSocChip.sv"),s"""// Prototype: physical primitive recipes are not available yet.
module DesyncSocChip(input wire powerGood, input wire watchdogClock,
${declarations.mkString(",\n")});
  wire serviceClock, serviceClockEnable, porReleased;
  DesyncClock fastRegion(.reset(!powerGood),
    .run(powerGood && (reset || !porReleased || serviceClockEnable)),
    .clockOut(serviceClock));
  riscay_reset_hold #(.HOLD_CYCLES(100000)) resetHold(.clk(serviceClock),
    .power_good(powerGood),.reset(reset),.released(porReleased));
  ${metadata("top").str} soc(${connections.mkString(",\n")});
endmodule
""")
    val stream=getClass.getResourceAsStream("/riscay/riscay_reset_hold.sv")
    val resource=try new String(stream.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8) finally stream.close()
    Files.writeString(chip.resolve("riscay_reset_hold.sv"),resource)
    val modelStream=getClass.getResourceAsStream("/riscay/desync_models.sv")
    try Files.write(chip.resolve("desync_models.sv"),modelStream.readAllBytes()) finally modelStream.close()
    // Explicit opt-in: the region's ordinary physical filelist never includes
    // simulation-only generator bodies (which disappear under SYNTHESIS).
    Files.writeString(base.resolve("filelist-simulation.f"),Files.readString(base.resolve("filelist.f"))+
      "chip/DesyncClock.sv\nchip/DesyncSocChip.sv\nchip/riscay_reset_hold.sv\nchip/desync_models.sv\n")
    Files.writeString(chip.resolve("README.txt"),
      "Prototype digital boundary; watchdogClock/powerGood come from existing analog IP.\n"+
      "Service/work clocks come only from DesyncClock; no service oscillator is emitted.\n"+
      "Generator physical leaves still require qualified registry recipes.\n"+
      "filelist-simulation.f opts into digital models; testbenches must set positive MIN_NS/MAX_NS on fastRegion.delay and fastRegion.mutex.\n"+
      "POR cancels pending digital events; physical reset pulse/discharge/release limits remain unqualified.\n"+
      "Those bounds are explicit simulation assumptions, not PVT characterization or physical sizing.\n"+
      "desync.json describes the ideal-clock region for comparison; chip/ contains generator integration.\n")
  }
}
