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

## Firmware and cold boot

The MCU contains no Groundlark power controller or power-policy ROM. Ordinary
Groundlark firmware, stored in external SPI boot flash, owns startup, shutdown,
halt qualification, hysteresis and minimum-off policy. The generic ROM only
validates and loads an image. Missing/corrupt flash falls back to I2C; it does not
power the Pi. Supplying a valid boot image is therefore part of board provisioning.

POR makes every GPIO an input. Existing external pulls define the safe power
state. Generic watchdog recovery may clear output enables (default) or retain
ordinary GPIO output/OE when explicitly configured. Boot SPI pins always release
during recovery. No profile label or register name changes this behavior.

This document records MCU-side integration requirements. It does not modify the
Groundlark board, reference firmware or policy configuration.

## RISCay signal budget

The external-SPI baseline has **ten application signals** before reset, supply
and physical test pads:

| Signal group | Count | Connection |
| --- | ---: | --- |
| Pi power enable, shutdown, halt | 3 | GPIO 0, 1, 2 |
| Shared SPI SCLK/MISO and ADC CS | 3 | Existing ADC interface; GPIO aliases 3/6 refer to SCLK/MISO, not extra pads |
| Boot flash MOSI and CS | 2 | GPIO 4 and 5; separate flash CS with an external pull-up |
| I2C host SCL/SDA | 2 | Existing loader/status bus |

External flash shares the ADC clock and MCU data-in/MISO wire. Flash adds MOSI
(MCU data-out) and its own chip select. ADC and flash must tri-state MISO when
unselected. A generic claim inhibits new ADC conversions, waits for complete
native transaction drainage, and switches SCLK to GPIO bit-banging. Release
requires inactive flash CS and idle SCLK; sampling then resumes with honest age.

The first ROM protocol is single-I/O SPI NOR mode 0 with 24-bit addresses, READ
03h, RDSR 05h, WREN 06h, PP 02h (256-byte pages), and SE 20h (4 KiB sectors).
A board must select compatible storage, verify voltage/timing and pull-up values,
and provision the generic image format. EEPROM-specific write protocols are not
implied. Ordinary GPIO access is not a tamper-proof flash write-protection scheme.

Host I2C remains the status/telemetry/update path. No separate PROGRAMMED or LOCK
pad is needed. Provisioning and optional write-through use the same image and
programming-lock contract; the Pi need not be running for normal external boot.

No dedicated BOOT pin is necessary: power-on always enters the generic loader.
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

Boot ROM, program RAM and working RAM are on-chip in both SoCs. External SPI boot flash is required for autonomous application startup;
there is no parallel external address/data bus. The present CPU memory ports
are internal integration interfaces. The serial loader pins above carry the
image into local RAM; execution does not fetch instructions from the Pi.

The existing board measures **battery voltage**, not Pi load current, consumed
watts or the switched 5 V rail. U133's unused power-good pin is grounded in the
current circuit. Those extra measurements are not implied by this interface and
are outside the present scope.

The current TI firmware uses battery measurements internally but provides no
Pi-readable telemetry transport; its Pi connections are the shutdown/halt GPIOs.
RISCay's I2C RTL adds that transport. The reference SoC emitter selects the
shared SPI ADC/boot-flash interface, for ten application signals total before
reset, clocks, supplies and physical test pads. See the [SoC contract](soc-contract.md).
Report the power-enable command as a commanded state, not
as proof that the Pi rail has reached voltage.

[circuit]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/hw/groundlark-fpga-hat/elec/hat_trenz.ato
[pins]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/hw/tools/pi_power_checks.py
[firmware]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/sw/supervisor/firmware/mspm0.c
[i2c]: https://cache.nxp.com/docs/en/user-guide/UM10204.pdf
