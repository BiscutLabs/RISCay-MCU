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
CPU and common peripheral RTL have no Groundlark dependencies. Both SoCs include
the host interface, loader, memory protection and generic peripherals; the
Groundlark controller is a separate profile.

Both variants use **on-chip boot ROM, executable RAM and working RAM**. No external
memory chip is required. A host may reload firmware after complete power loss.
Groundlark's bootstrap must first qualify supply and power its Pi; other profiles
define their own startup behavior. Groundlark uses a baseline of 2 KiB application
RAM plus 256 bytes working RAM and a 12-byte boot ROM. Compiler-built RV32E
[sizing fixtures](firmware/README.md) support that budget, with a 128-byte stack
reserve and 16-byte guard inside working RAM. Capacities remain build parameters;
both writable banks use flip-flop storage. See the
[memory architecture](docs/memory-architecture.md).

The common host interface reports device/loader state, generic measurements and
application registers. Groundlark binds these to battery voltage and supervisor
state. Programming lock lasts until full MCU reset or power loss; status and
telemetry remain readable when locked. See the
[host status, telemetry and lock contract](docs/loader-status-and-lock.md).

**Status: complete baseline digital RTL.** Both async RV32E cores connect to the
same on-chip ROM/RAM and clocked peripheral island: I2C loader/status, GPIO,
timer/events, measurements, SPI ADC and independent watchdog. A permanent
Groundlark controller supervises power before upload and during application
stalls. Its default policy is disabled until qualified battery settings are
provided. Watchdog recovery resets the application and its CPU bridges while
preserving the power supervisor, sensing, timebase, validated image and programming
lock. The host can explicitly restart that image. Only manual/POR/brownout reset
or MCU power loss clears the lock and returns Groundlark to its off state.
**Tapeout must deliberately supply and qualify an enabled board policy**; the
reference emitters' disabled `PowerPolicy()` never enables Pi power.
Physical/analog, pin/package, board and Chiselator qualification remain.

Both reference emitters include **retained sleep with fast-clock shutdown** and a
nominal **7.7307 Hz** timebase matched to the
[GF180 LF oscillator candidate](analog/gf180-lf-osc/README.md). Gray CDC counts
single ticks; conversion to nominal milliseconds happens after synchronization.
Programmable sensing, bounded sleep leases, status and programming lock survive
sleep. Generated chip wrappers contain both oscillator boundaries and need no
external clock pins. An address-only I2C wake probe and 100 us wait restart the
fast source without another pin. The [clock/reset circuits](analog/gf180-clock-reset/README.md)
include a transistor-level fast oscillator and supply monitor, plus a synthesizable
5 ms minimum reset hold. Both wrappers connect these internally. Schematic SPICE
and digital integration tests are separate from layout, extracted qualification
and whole-chip power measurements, which remain outstanding. See
[sleep and clocks](docs/sleep-and-clock.md) for timing bounds and host requirements.
Stuck or abandoned I2C transfers time out and release the fast source. A held-low
bus cannot continuously wake it; traffic for another address releases the gate
after address rejection.

See the [implemented SoC contract](docs/soc-contract.md) for the wire protocol,
memory map and reset behavior. The [feature and IP plan](docs/features-and-ip.md)
covers essential peripherals, reusable library components, async design
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
folders. Complete SoC tops use internal memory; standalone core tests retain
independent memory models. Optional peripherals, compressed instructions and
additional architecture variants are on hold.

The [Groundlark I/O contract](docs/groundlark-io.md) maps battery sensing, shutdown,
halt acknowledgement, and power-on control. The reference digital build uses a
separate three-signal SPI ADC; physical pads and analog integration remain open.
Compiled memory budgets are recorded in the [memory architecture](docs/memory-architecture.md).
Physical power/area benefits are not yet measured.

Project licensing is recorded in [LICENSE](LICENSE). Reused third-party material
retains its own license and attribution.
