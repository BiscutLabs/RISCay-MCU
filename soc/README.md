# Shared SoC interfaces and fixed macros

The implementations live separately under `designs/four-phase-bd/` and
`designs/two-phase-click/`. This directory retains parameters, port schemas,
the pinned GF180 SRAM macro/model and inventory, and chip-wrapper utilities.
It no longer owns a common Services/Platform/SramBank implementation.
See the [migration checklist](../docs/async-soc-migration.md) and
[SoC contract](../docs/soc-contract.md).

Each design owns its Services, Platform, ClockedPeripherals, ConstantScaling,
I2cTarget, SleepTiming and SramBank, plus independent native Fabric, Control,
Telemetry, Supervisor, Housekeeping, SRAM, I2C and SPI ADC controllers. ROM/static faults are
clockless. Native loops own loader/MMIO state, software GPIO/events and sample
records, permanent supervision, word/byte sequencing, I2C protocol state and
SPI conversion ownership/assembly/priming/scaling, time/deadline/lease/wake-mask
policy, watchdog kick authorization and low-power cadence. Schemas share wire layouts
and reset literals, not state transitions. Clocked ingress, snapshots,
reset/status projection, GPIO sampling, individual synchronous SRAM byte
accesses, I2C wire sampling/timeout, SPI pin timing/full-frame capture and
legacy SPI idle delay remain explicit boundaries. An independent LF reference/watchdog
remains required. The full SoC is not clockless.

`ChipWrapper.scala` emits oscillator/reset boundaries and their simulation views.
See [sleep and clocks](../docs/sleep-and-clock.md) for source wake and reset scope,
and [SRAM integration](../docs/sram-integration.md) for pinned assets and retention.

Clocked helpers are inlined for strict export; native async modules keep their
registered contract hierarchy. The export adapter checks fixed SRAM identities,
views and inventory separately. Inlining does not change clocks or protocols.
Digital export validation is not physical timing qualification.
