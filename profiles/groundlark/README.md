# Groundlark profile

Application ID `0x474c524b` (GLRK), profile version 1. This is a project-assigned
identifier, not a standards allocation. Definitions live in
[Groundlark.scala](../src/main/scala/riscay/profiles/Groundlark.scala).

The profile builds 2 KiB executable RAM, 256 bytes working RAM, three application
control GPIOs and one measurement channel. Host I2C, the reference three-signal
SPI ADC interface, reset, timing and test pads are additional to that GPIO count.

| Generic resource | Groundlark meaning |
| --- | --- |
| GPIO 0, output, reset low | Pi regulator/load-switch enable |
| GPIO 1, output, reset low | Shutdown request driving Q130 |
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
supervisor faults. Enums/flags are specified in the [SoC contract](../../docs/soc-contract.md).

Battery voltage must refer to the battery input after correcting for the divider
and reference. A nominal conversion is not calibrated. Failed/stale conversions
must not be presented as fresh. Power-enable status is a command, not a measured
5 V rail or evidence of Pi health. Current, watts and charge estimates remain
outside this profile's current sensing hardware.

The permanent bootstrap must measure voltage, apply a qualified minimum startup
policy, power the Pi without a programmed application and continue supervision
during upload. Manual/POR/brownout reset disables Pi power. Application watchdog
reset preserves the supervisor state, power/shutdown outputs, elapsed timers,
sensing, image and lock; the Pi can explicitly restart the retained image.
Pi-only reset also preserves MCU image and lock. The programming lock never
disables telemetry reads or acquisition.
Fixed hardware implements the complete baseline power policy and owns these
three GPIOs; uploaded firmware cannot override it. The default emitted policy
is disabled until battery/board settings are qualified and enabled at build time.
Tapeout must select that qualified policy deliberately; the default emitter is
intentionally latched off.

The current TI firmware uses battery readings internally and has no Pi-readable
telemetry transport. RISCay implements digital loader, telemetry and permanent
supervision. This profile does not assign physical ADC pads or establish qualified
battery thresholds.
