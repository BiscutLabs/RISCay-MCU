# Shared MCU contracts and verification

This directory is reserved for material used unchanged by both implementations:

- RISC-V execution environment, memory map and generic host/peripheral definitions.
- Pure instruction decoding and datapath functions where sharing preserves
  each design's independent protocol/storage implementation.
- Common startup/linker support; board policy and firmware bindings live in `profiles/`.
- Identical workload inputs and independent ISA/supervisor reference models.
- Common test vectors, result schemas and comparison tooling.

Protocol controllers, state storage and protocol-specific timing/reset logic
belong under their respective `designs/` directories. Expected test results
must not come from the same shared datapath used to implement the CPU.

Shared combinational RV32E logic is implemented in
[Architecture.scala](src/main/scala/riscay/Architecture.scala). Independent tests
are in `verification/`; the interpreter does not call production datapath code.

[HostSchema.scala](src/main/scala/riscay/HostSchema.scala) defines and validates
the generic logical host catalog, measurement descriptors and build parameters.
It supplies no I2C transport, peripheral RTL or physical memory. Board-specific
registers and pin roles belong in [profiles/](../profiles/README.md), never in the
shared CPU or common device/loader services.
The firmware build, power-policy and event-integrity suites remain. Both designs
must pass the same functional tests; each also
needs its own protocol/timing negative controls. Compare committed instruction
and I/O effects rather than internal cycles. Optional features are on hold.
