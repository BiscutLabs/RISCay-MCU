# Groundlark profile

Application ID `0x474c524b` (GLRK), profile version 1. This is a project-assigned
identifier, not a standards allocation. Definitions live in
[Groundlark.scala](../src/main/scala/riscay/profiles/Groundlark.scala).

The profile builds 2 KiB executable SRAM, 1 KiB working SRAM, seven logical GPIO indices (three application
controls, two flash outputs and two shared-SPI aliases) and one measurement channel. Host I2C, the reference three-signal
SPI ADC interface, reset, timing and test pads are additional to that GPIO count.

| Generic resource | Groundlark meaning |
| --- | --- |
| GPIO 0, intended output | Pi regulator/load-switch enable |
| GPIO 1, intended output | Shutdown request driving Q130 |
| GPIO 2, input, active low | Halt acknowledgement through Q131 |
| Measurement 0 | Battery voltage: signed integer VALUE in millivolts; UNIT=Volt, SCALE10=-3 |

These are logical GPIO indices, not package pads or Pi BCM numbers. The
[board I/O contract](../../docs/groundlark-io.md) owns electrical mapping.

The application host service (`space=0x80`, `instance=0`) contains read-only words:

| Word | Register |
| --- | --- |
| 0 | SUPERVISOR_MODE |
| 1 | PI_POWER_ENABLE |
| 2 | SHUTDOWN_REQUESTED |
| 3 | HALT_ACK_QUALIFIED |
| 4 | SUPERVISOR_FAULT |
| 5 | SHUTDOWN_TIMEOUT_COUNT |

The SDK may name measurement 0's value `BATTERY_MV`; that is a profile alias,
not a battery-specific register in the generic MCU service. Sample validity,
calibration, age and sequence use the common measurement contract. Reset reason
comes from the common device service, and loader errors remain separate from
supervisor faults. Their application-level enums belong to firmware; the MCU does
not implement or constrain them.

Battery voltage must refer to the battery input after correcting for the divider
and reference. A nominal conversion is not calibrated. Failed/stale conversions
must not be presented as fresh. Power-enable status is a command, not a measured
5 V rail or evidence of Pi health. Current, watts and charge estimates remain
outside this profile's current sensing hardware.

Groundlark power decisions belong in ordinary application firmware loaded from
external SPI boot flash. RISCay does not implement these decisions in hardware or
mask ROM. All six application words are software-owned. GPIO direction labels in
this profile are documentation only: POR always disables all output drivers.

The generic watchdog returns to ROM. The default GPIO recovery option disables
outputs; `retainGpioOnWatchdog=true` retains ordinary application GPIO output/OE
state. Boot-bus pins still release during recovery. Neither setting contains a
Groundlark power policy. Board pulls and firmware determine the resulting behavior.

The MCU-side integration plan adds external boot flash sharing ADC SCLK/MISO,
with separate flash CS and MOSI. See the [I/O contract](../../docs/groundlark-io.md).
Groundlark firmware, board files and numerical policy are not modified in this
workstream. Missing/corrupt application leaves the generic loader waiting;
there is no promise that the Pi powers on without valid firmware.
