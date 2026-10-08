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
    val connections = ports.map(p => s".${name(p)}(${name(p) match {
      case "watchdogClock" => "lfClock"
      case "reset" => "~porReleased"
      case n => n
    }})")
    val chip = base.resolve("chip"); Files.createDirectories(chip)
    val file = chip.resolve(s"$top.sv")
    Files.writeString(file, s"""// Generated structural boundary; not a padframe or qualified analog implementation.
module $top #(parameter integer RESET_HOLD_CYCLES = 100000) (
${declarations.mkString(",\n")}
);
  wire lfClock, serviceClock, serviceClockEnable, powerGood, porReleased;
  riscay_supply_monitor supplyMonitor (.good(powerGood));
  // The fast source runs during reset hold, breaking the clock/reset dependency.
  wire fastEnable = powerGood && (reset || !porReleased || serviceClockEnable);
  riscay_reset_hold #(.HOLD_CYCLES(RESET_HOLD_CYCLES)) resetHold (
    .clk(serviceClock), .power_good(powerGood), .reset(reset), .released(porReleased));
  // Only POR resets LF bias; a watchdog reset must not stop its own clock.
  riscay_lf_osc oscillator (.rst_n(porReleased), .clk(lfClock));
  riscay_service_osc serviceOscillator (.rst_n(powerGood), .enable(fastEnable), .clk(serviceClock));
  $core soc (${connections.mkString(", ")});
endmodule
""")
    for(resource <- Seq("riscay_lf_osc.v", "riscay_lf_osc_model.sv", "riscay_service_osc.v", "riscay_service_osc_model.sv",
        "riscay_supply_monitor.v", "riscay_supply_monitor_model.sv", "riscay_reset_hold.sv")) {
      val stream = Option(getClass.getResourceAsStream("/riscay/" + resource)).getOrElse(sys.error(resource))
      val content = try new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8) finally stream.close()
      Files.writeString(chip.resolve(resource),content.replace("NOMINAL_HZ = 7.7307",s"NOMINAL_HZ = ${lp.referenceHz}"))
    }
    Files.writeString(chip.resolve("README.txt"),
      s"$top connects the on-die LF oscillator to both timebase and watchdog.\n" +
      "Compile the parent filelist, wrapper, riscay_reset_hold.sv and ONE view of EACH analog macro.\n" +
      "The .v files are synthesis black boxes requiring qualified GF180 analog IP.\n" +
      "The _model.sv files are executable contracts, not characterized physical macros.\n" +
      "No external clock or power-good pin. reset is an active-high manual reset input.\n" +
      "On-die supply monitor asserts reset; 100000 fast cycles qualify release (>=5 ms).\n" +
      "Fast oscillator: about 12 MHz nominal, 8..20 MHz, startup <=100 us, full final high pulse.\n" +
      "Wake via address-only I2C probe (ACK optional), STOP, wait 100 us, then START within 50 us.\n" +
      "LF analog POR requires >=5 ms after valid supply. No trim or runtime calibration.\n")
    file
  }
}
