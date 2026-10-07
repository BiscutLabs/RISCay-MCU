# Common SoC service island

Both CPU protocols use this identical clocked memory/peripheral implementation.
It supplies internal boot ROM, program/working RAM, I2C host framing, validated
image loading/protection, GPIO, timer/events, measurement snapshots, SPI ADC and
independent watchdog/reset distribution. Board factories keep application policy
outside the common block. See the [SoC contract](../docs/soc-contract.md).

CPU boundary bridges remain in each design folder (or use the four-phase library
bridges). Clock/reset sources, RAM banks and bridge costs belong in comparisons.
The CPU is asynchronous; the complete SoC is not entirely clockless.

Clocked helper modules are inlined into the SoC root for export. All asynchronous
cores/bridges retain registered contract hierarchy; no unregistered helper module
is left outside the strict export inventory. Inlining changes hierarchy, not the
clocks or protocol. Behavioral tests still exercise the complete emitted logic.
Complete exports use the MCU checker's explicit generated-reset option; see
[build and test](../docs/build-and-test.md). Constant GPIO outputs are described
by the port ABI rather than artificial asynchronous timing endpoints.
