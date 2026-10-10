# Native two-phase Click MCU

Required RISCay-MCU implementation using Chisel and chisel-async native Click
components. The core and complete digital SoC are implemented.
[ClickSoc.scala](src/main/scala/riscay/click/ClickSoc.scala) uses
[native toggle/clocked bridges](src/main/scala/riscay/click/ClockBridges.scala),
after native `ClickFabric` routing, with no four-phase adapters. ROM/static
faults are asynchronous. `ClickControl` uses a seeded native Click state token,
join, transform and fork for loader accounting/lock, MMIO validation and
selector/producer staging. Its POR-only toggle/clocked crossings, ingress,
snapshots, reset/status projection and peripheral effects remain explicit in
`ClickPlatform`/`ClickServices`. This directory owns its peripheral, scaling, sleep
and SRAM controller implementations. Its native Telemetry, Supervisor, SRAM and
I2C loops retain separate POR-owned state.
[ClickSpiAdc.scala](src/main/scala/riscay/click/ClickSpiAdc.scala) owns native
conversion/priming, frame assembly, scaling and retirement; explicit toggle
bridges surround a clocked immutable-recipe player and full-frame capture.
Cadence and independent LF/watchdog housekeeping remain clocked. Follow the
[migration checklist](../../docs/async-soc-migration.md). See the [SoC contract](../../docs/soc-contract.md).

The core is [ClickCore.scala](src/main/scala/riscay/click/ClickCore.scala), with
[native fork/join routing](src/main/scala/riscay/click/NativeRouting.scala).
Build instructions are in [build and test](../../docs/build-and-test.md).
The SoC emitter enables retained sleep and also emits `chip/ClickSocChip.sv`
with internal LF and stoppable service oscillator boundaries. See [sleep and clocks](../../docs/sleep-and-clock.md)
for simulation views and outstanding analog qualification.

Own the native two-phase CPU sequencing, Click storage, phase/reset initialization,
top-level integration, emission and protocol-specific tests in this directory.
Use native `ClickStage` and related components, with explicit pulse-width,
setup/hold and trigger-skew obligations.

The library's general `TwoPhase*` routing wraps four-phase cores. It is not a
native Click replacement. Any necessary peripheral-boundary conversion must be
identified and included in comparison costs. The current core uses native
two-phase fork/join and Click storage, with no phase converters.

For each profile, match the four-phase implementation's ISA, firmware image, datapath width,
memory capacities, MMIO map, board signals and supervisor policy.

Use the [reusable interface](../../docs/reusable-interface.md),
[common feature plan](../../docs/features-and-ip.md),
[board I/O contract](../../docs/groundlark-io.md), and
[shared ownership rules](../../shared/README.md). Optional features are on hold.
