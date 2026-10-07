# Four-phase bundled-data MCU

Required RISCay-MCU implementation using Chisel and chisel-async four-phase
bundled-data components. Status: initial RV32E core RTL and tests implemented.
The complete supervisor MCU still needs memory/peripheral and firmware integration.

The core is [FourPhaseCore.scala](src/main/scala/riscay/bd/FourPhaseCore.scala).
Build instructions are in [build and test](../../docs/build-and-test.md).

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
