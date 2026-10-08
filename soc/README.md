# Common SoC service island

Both CPU protocols use this identical clocked memory/peripheral implementation.
It supplies internal boot ROM, program/working RAM, I2C host framing, validated
image loading/protection, GPIO, timer/events, measurement snapshots, SPI ADC and
independent watchdog/reset distribution. Board factories keep application policy
outside the common block. See the [SoC contract](../docs/soc-contract.md).

CPU boundary bridges remain in each design folder (or use the four-phase library
bridges). Clock/reset sources, RAM banks and bridge costs belong in comparisons.
The CPU is asynchronous; the complete SoC is not entirely clockless.

`SleepTiming.scala` supplies the single-step Gray LF timebase, retained work gate
and event-set service-source wake control. `ChipWrapper.scala` emits internal LF
and restartable fast oscillator boundaries with separate black-box and behavioral
views. The slow timing scale and LF POR interface now match the
[analog candidate](../analog/gf180-lf-osc/README.md). A physical fast source, POR
generator and qualified macro/layout bindings remain outstanding. See
[sleep and clocks](../docs/sleep-and-clock.md), especially the I2C wake probe.

Clocked helper modules are inlined into the SoC root for export. All asynchronous
cores/bridges retain registered contract hierarchy; no unregistered helper module
is left outside the strict export inventory. Physical SRAM instances have their
own pinned inventory and view checks in the MCU export adapter. Inlining changes hierarchy, not the
clocks or protocol. Behavioral tests still exercise the complete emitted logic.
Complete exports use the MCU checker's explicit generated-reset option; see
[build and test](../docs/build-and-test.md). Constant GPIO outputs are described
by the port ABI rather than artificial asynchronous timing endpoints.

`Sram.scala` supplies the byte-sequenced GF180 SRAM banks, shared by both cores.
Groundlark allocates two 1 KiB macros for program memory and one for working RAM.
See [SRAM integration](../docs/sram-integration.md) for asset fetching, physical
views, reset ordering and verification limits.
