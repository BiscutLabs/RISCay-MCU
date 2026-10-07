# Groundlark power-supervisor I/O contract

Draft, 2026-10-07. This logical interface is shared by the four-phase bundled-data
and native two-phase Click implementations. RISCay pad numbers and package are
not assigned yet. The existing HAT routes the three Pi-control signals; the new
Pi firmware-loading connection requires a board revision.

This is a [Groundlark profile](../profiles/groundlark/README.md), not a universal
MCU pinout. The [generic interface](reusable-interface.md) exposes GPIO roles,
measurement channels and application registers; this document assigns their
board-specific meaning. Both async variants use these same bindings.

## Required application signals

Directions below are relative to the MCU. Existing U130 pad numbers refer to the
TI MSPM0L1106TRHBR, not to a proposed RISCay pinout.

| Logical function | MCU direction | Existing HAT connection | Behavior |
| --- | --- | --- | --- |
| `pi_power_enable` | Output | U130 pad 7 / PA3 -> R141 -> SUP_RUN -> U132 EN and U133 ON | High enables the Pi regulator/load switch; low removes Pi power. External pulldown makes reset fail off. This is an enable signal, not the Pi's own RUN/reset pin. |
| `pi_shutdown_request` | Output | U130 pad 8 / PA4 -> Q130 -> BCM6, Pi header pin 31 | MCU high turns Q130 on and pulls the Pi shutdown input low. The configured Pi service/overlay initiates shutdown. |
| `pi_halted_n` | Input | BCM13, Pi header pin 33 -> Q131 -> U130 pad 9 / PA5 | Pi high turns Q131 on; MCU reads low. Qualify against the current boot and the configured kernel poweroff sequence. |
| `battery_voltage` | Analog input, or ADC transaction | R135/R136/C145 -> U130 pad 31 / PA27 / ADC0.0 | Divided upstream battery voltage, currently measured against a 2.5 V reference. A digital-only RISCay needs an external ADC and revised routing. |

The reference is Groundlark's authored circuit and independent pin fixture at
revision `3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3`:
[circuit][circuit], [pin fixture][pins], [firmware][firmware].

## Shutdown and power-on sequence

1. The always-on supervisor monitors battery voltage while Pi power is off.
2. Once voltage and minimum-off/restart confirmation policy permit it, assert
   `pi_power_enable`. The target Pi 4 cold-boots when its 5 V rail is restored.
   Following total supervisor power loss, permanent bootstrap code performs this
   step and maintains essential supervision while the Pi uploads the application.
3. When policy requests shutdown, assert `pi_shutdown_request` and keep power on
   while waiting for qualified `pi_halted_n` or the configured timeout.
4. Deassert `pi_power_enable` after halt, or after the explicit forced-off timeout
   policy. Wait the minimum off interval and voltage recovery before restarting.

No extra Pi wake pin is needed for this full power-cycle behavior. Waking an
already powered Pi from soft-off is a different feature and is on hold.
The supervisor and external ADC/timebase must remain powered upstream of the
switched Pi rail. Preserve the existing transistor interfaces so powered MCU
signals do not back-power the unpowered Pi.

## RISCay signal budget

There are **three required digital Pi-control pins** in either MCU implementation.
Battery monitoring then needs one of these alternatives:

| ADC architecture | Additional MCU application pins | Status |
| --- | --- | --- |
| Integrated ADC | One analog input; reference/supply pads depend on analog IP | Mirrors the existing board's sensing connection; analog implementation deferred |
| External I2C ADC | SDA and SCL | Five signals for Pi control and ADC, before the host loader connection |
| External SPI ADC | Typically SCLK, CS and MISO; MOSI if required by the selected ADC | Six or seven signals for Pi control and ADC, before the host loader connection |

Reserve **two additional MCU signals** for the proposed Pi I2C loader: `host_sda`
and `host_scl`. Connect to Pi BCM2/header 3 and BCM3/header 5 on the existing
Pi-side I2C1 bus, with an unused device address. This shares existing Pi GPIOs;
it needs new routing to RISCay, not two new dedicated Pi GPIOs. I2C uses SDA and
SCL for addressed bidirectional transfers. [I2C specification][i2c]

Use this same connection for status and battery/supervisor telemetry reads,
validated-image reporting and the programming-lock command. No additional
PROGRAMMED, LOCK, battery-data or status GPIO is
required; the Pi polls the [loader/status interface](loader-status-and-lock.md).
The status endpoint must operate independently of the uploaded application.

The resulting application-signal budget is five digital pins plus one analog
input with an integrated ADC, seven digital pins with a separate I2C ADC bus,
or eight/nine digital pins with a separate SPI ADC. Supply, reset, timebase and
test pins remain additional. Sharing ADC and host wires could reduce the count,
but requires resolving controller ownership and operation with the Pi unpowered;
do not assume that optimization in the baseline.

No dedicated BOOT pin is necessary: power-on always enters the permanent loader.
A Pi-controlled reset connection would be an optional extra Pi GPIO route, not
necessary for this cold-start flow. Full MCU reset still forces Pi power off.
Keep application handoff separate from full-chip reset so upload completion does
not power-cycle its own host.

Current U130 SWDIO/SWCLK/NRST go to J131, not to a Pi programming connection.
The shutdown/ACK transistor paths remain assigned to their original functions.
Use open-drain host I/O with pull-ups on the appropriate powered bus segment,
and verify isolation/leakage so the always-on supervisor cannot back-power the
Pi. The host bus must release during reset and power-off. Do not attach the
always-on ADC behind a Pi-powered interface and then rely on it for cold start.

These are application-signal counts, not package pin counts. Also budget supply
and ground pads, reset/brownout input, a low-frequency reference input if external,
the independent watchdog reference/interface as required, and physical test/debug
access. Do not claim a package fits until those choices and pad-cell voltages are
resolved. Both designs must use the same chosen external interface.

Boot ROM, program RAM and working RAM are on-chip in both SoCs. No external memory
address/data bus or boot-flash pins are required. The present CPU memory ports
are internal integration interfaces. The serial loader pins above carry the
image into local RAM; execution does not fetch instructions from the Pi.

The existing board measures **battery voltage**, not Pi load current, consumed
watts or the switched 5 V rail. U133's unused power-good pin is grounded in the
current circuit. Those extra measurements are not implied by this interface and
are outside the present scope.

The current TI firmware uses battery measurements internally but provides no
Pi-readable telemetry transport; its Pi connections are the shutdown/halt GPIOs.
RISCay's proposed I2C connection adds that transport. Telemetry and host RTL are
still unimplemented. Report the power-enable command as a commanded state, not
as proof that the Pi rail has reached voltage.

[circuit]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/hw/groundlark-fpga-hat/elec/hat_trenz.ato
[pins]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/hw/tools/pi_power_checks.py
[firmware]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/sw/supervisor/firmware/mspm0.c
[i2c]: https://cache.nxp.com/docs/en/user-guide/UM10204.pdf
