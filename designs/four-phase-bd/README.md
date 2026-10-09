# Four-phase bundled-data MCU

Required RISCay-MCU implementation using Chisel and chisel-async four-phase
bundled-data components. The core and complete digital SoC are implemented.
[FourPhaseSoc.scala](src/main/scala/riscay/bd/FourPhaseSoc.scala) connects the core
through `FourPhaseFabric` to its own clocked `FourPhaseServices` endpoint via
explicit four-phase/clocked bridges. ROM/static faults are asynchronous; MMIO,
loader and peripheral state are still clocked. This directory owns its Platform,
peripheral, scaling, sleep and SRAM controller implementations.
Follow the [migration checklist](../../docs/async-soc-migration.md).
See the [SoC contract](../../docs/soc-contract.md) for behavior and qualification limits.

The core is [FourPhaseCore.scala](src/main/scala/riscay/bd/FourPhaseCore.scala).
Build instructions are in [build and test](../../docs/build-and-test.md).
The SoC emitter enables retained sleep and also emits `chip/FourPhaseSocChip.sv`
with internal LF and stoppable service oscillator boundaries. See [sleep and clocks](../../docs/sleep-and-clock.md)
for simulation views and outstanding analog qualification.

Own the four-phase CPU sequencing, long-hold storage, reset/token initialization,
top-level integration, emission and protocol-specific tests in this directory.
Use explicit request/acknowledge return-to-zero contracts and preserve their
matched-delay and storage timing obligations.

For each profile, match the native Click implementation's ISA, firmware image, datapath width,
memory capacities, MMIO map, board signals and supervisor policy. Shared logic
must not hide a protocol-specific implementation behind a mode flag.

Use the [reusable interface](../../docs/reusable-interface.md),
[common feature plan](../../docs/features-and-ip.md),
[board I/O contract](../../docs/groundlark-io.md), and
[shared ownership rules](../../shared/README.md). Optional features are on hold.
