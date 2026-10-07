# RISCay-MCU

A tiny reusable RISC-V SoC, built in Chisel with
[chisel-async](https://github.com/BiscutLabs/chisel-async).

RISCay-MCU is designed for reuse across projects, but its original purpose and
design priorities come from power management on the Groundlark HAT. Groundlark
is the first application profile and the reference workload for comparing the
two asynchronous implementations.

Its first application is replacing the TI MSPM0L1106 supervisor's role in the
[Groundlark HAT](https://github.com/naturalhazardscience/groundlark): monitor
battery voltage, request Raspberry Pi shutdown, observe halt acknowledgement,
and control the external Pi power switch.

The [reusable interface](docs/reusable-interface.md) separates common device,
loader and measurement services from [application profiles](profiles/README.md).
CPU RTL already has no Groundlark dependencies. A validated logical host schema
and a separate Groundlark profile are implemented; host/peripheral RTL is pending.

Both variants use **on-chip boot ROM, executable RAM and working RAM**. No external
memory chip is required. A host may reload firmware after complete power loss.
Groundlark's bootstrap must first qualify supply and power its Pi; other profiles
define their own startup behavior. Groundlark provisionally uses 2 KiB application
RAM plus 256 bytes working RAM and a separately sized boot ROM. Capacities are
build parameters and remain unmeasured; SRAM mapping is a later choice. See the
[memory architecture](docs/memory-architecture.md).

The common host interface reports device/loader state, generic measurements and
application registers. Groundlark binds these to battery voltage and supervisor
state. Programming lock lasts until full MCU reset or power loss; status and
telemetry remain readable when locked. See the
[host status, telemetry and lock contract](docs/loader-status-and-lock.md).

**Status: initial RTL.** Both async RV32E cores are implemented with a shared
combinational datapath and independent instruction/bus checks. ROM/RAM and
peripheral integration, RISC-V supervisor firmware, and board qualification
remain to be built. Pin, package and electrical compatibility are unresolved.

See the [feature and IP plan](docs/features-and-ip.md) for the proposed RV32EC
architecture, essential peripherals, reusable library components, async design
comparison, and verification requirements. The [execution contract](docs/execution-contract.md)
describes implemented behavior; [build and test](docs/build-and-test.md) has the
runnable commands.

The delivery sequence is:

1. Consume a pinned, qualified chisel-async version.
2. Build and verify RISCay-MCU using an existing event simulator.
3. Run the established MCU/firmware/test corpus in Chiselator.
4. Select and qualify physical cells, memories, analog interfaces, packaging,
   fabrication, and the real Groundlark integration.

Two implementations are active comparison targets:

- [Four-phase bundled data](designs/four-phase-bd/README.md).
- [Native two-phase Click](designs/two-phase-click/README.md).

For each profile, both use the same execution contract, firmware, memory sizes,
board I/O and acceptance tests. Shared material belongs in [shared/](shared/README.md);
protocol-specific controllers and storage belong in their respective design
folders. The cores currently connect to testbench memory models; their memory
ports will become internal SoC connections, not package memory buses.
Optional peripherals and additional architecture variants are on hold.

The [Groundlark I/O contract](docs/groundlark-io.md) maps battery sensing, shutdown,
halt acknowledgement, and power-on control. Physical pad numbers and the ADC
integration choice remain open. Memory budgets and power/area benefits are not
yet measured.

Project licensing is recorded in [LICENSE](LICENSE). Reused third-party material
retains its own license and attribution.
