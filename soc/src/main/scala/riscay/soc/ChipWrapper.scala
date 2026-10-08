// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import java.nio.file.{Files, Path}

/** Physical oscillator boundary outside the portable async contract root.
  * Synthesizing a behavioral delay loop would silently invent oscillator IP;
  * emit an explicit black box and a separately selected simulation model instead.
  */
object ChipWrapper {
  def write(base: Path, lp: LowPowerParameters): Path = {
    val manifest = ujson.read(Files.readString(base.resolve("contract.json")))("manifest")
    val core = manifest("top").str
    val top = s"${core}Chip"
    val ports = ujson.read(Files.readString(base.resolve("ports.json")))("nodes")(0)("ports").arr
    def name(p: ujson.Value): String = p("source").str.split('>').last.replace('.', '_').replace('[', '_').replace("]", "")
    val internal = Set("watchdogClock", "serviceClock", "serviceClockEnable")
    val external = ports.filter(p => !internal(name(p)))
    val declarations = external.map(p => s"  ${p("direction").str} wire [${p("width").num.toInt-1}:0] ${name(p)}")
    val connections = ports.map(p => s".${name(p)}(${if(name(p) == "watchdogClock") "lfClock" else name(p)})")
    val chip = base.resolve("chip"); Files.createDirectories(chip)
    val file = chip.resolve(s"$top.sv")
    Files.writeString(file, s"""// Generated structural boundary; not a padframe or qualified analog implementation.
module $top (
${declarations.mkString(",\n")}
);
  wire lfClock, serviceClock, serviceClockEnable;
  // Only POR resets LF bias; a watchdog reset must not stop its own clock.
  riscay_lf_osc oscillator (.rst_n(~reset), .clk(lfClock));
  riscay_service_osc serviceOscillator (.enable(serviceClockEnable), .clk(serviceClock));
  $core soc (${connections.mkString(", ")});
endmodule
""")
    for(resource <- Seq("riscay_lf_osc.v", "riscay_lf_osc_model.sv", "riscay_service_osc.v", "riscay_service_osc_model.sv")) {
      val stream = Option(getClass.getResourceAsStream("/riscay/" + resource)).getOrElse(sys.error(resource))
      val content = try new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8) finally stream.close()
      Files.writeString(chip.resolve(resource),content.replace("NOMINAL_HZ = 7.7307",s"NOMINAL_HZ = ${lp.referenceHz}"))
    }
    Files.writeString(chip.resolve("README.txt"),
      s"$top connects the on-die LF oscillator to both timebase and watchdog.\n" +
      "Compile the parent filelist plus this wrapper and exactly ONE view of EACH oscillator.\n" +
      "The .v files are synthesis black boxes requiring qualified GF180 analog IP.\n" +
      "The _model.sv files are executable contracts, not characterized physical macros.\n" +
      "No external clock pin is needed. reset requires a qualified POR/brownout source.\n" +
      "Fast oscillator: 10 MHz nominal, 8..20 MHz, startup <=100 us, full final high pulse.\n" +
      "Wake via address-only I2C probe (ACK optional), STOP, wait 100 us, then START within 50 us.\n" +
      "LF analog POR requires >=5 ms after valid supply. No trim or runtime calibration.\n")
    file
  }
}
