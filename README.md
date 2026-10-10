# RISCay-MCU

Migration items use a fresh independent agent review, fixes, affected verification,
and a commit/push before completion. SocFabric, MMIO/loader,
GPIO/events/telemetry, scaling/CRC, permanent supervision, SRAM word sequencing and I2C protocol state are digitally verified; see the [migration checklist](docs/async-soc-migration.md).

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
CPU RTL is application-independent. Each SoC includes host services, memory
protection and generic peripherals, plus its own native controller selected by
the immutable Groundlark board profile.

Both variants use **on-chip boot ROM, executable RAM and working RAM**. No external
memory chip is required. A host may reload firmware after complete power loss.
Groundlark's bootstrap must first qualify supply and power its Pi; other profiles
define their own startup behavior. Groundlark uses a baseline of 2 KiB application
RAM plus 1 KiB working RAM and a 12-byte boot ROM. Compiler-built RV32E
[sizing fixtures](firmware/README.md) support that budget, with a 128-byte stack
reserve and 16-byte guard inside working RAM. Capacities remain build parameters;
both writable banks use three pinned GF180 1 KiB SRAM macros, with a shared
fixed macro model; each variant owns its byte-sequencing controller. See
[SRAM integration](docs/sram-integration.md) and
[memory architecture](docs/memory-architecture.md).
Native SRAM requests retain full byte offsets until the checked macro boundary
selects a bank and its ten-bit address. Native loader metadata
keeps full-width byte lengths, offsets and counts. Both
cores use a 171-bit control token and derive pending load fields from the saved
instruction, avoiding duplicate storage.

The common host interface reports device/loader state, generic measurements and
application registers. Groundlark binds these to battery voltage and supervisor
state. Programming lock lasts until full MCU reset or power loss; status and
telemetry remain readable when locked. See the
[host status, telemetry and lock contract](docs/loader-status-and-lock.md).

**Status: asynchronous SoC migration in progress.** Each design owns a separate
SoC implementation. SocFabric, MMIO/loader, GPIO/events/telemetry, scaling/CRC,
permanent supervision, SRAM word sequencing and I2C protocol state are digitally verified.
Separate native pipelines now own fractional elapsed-time
and ADC arithmetic, with CRC byte stages in each Control feedback loop.
Native fabrics route ROM and static access faults without a
service clock; stateful accesses use explicit endpoint bridges. Separate native
Control modules own loader state and MMIO validation/producer selectors.
Separate native Telemetry loops now own software GPIO/application words, pending
flags and host sample records; both variants pass regressions and strict exports. Clocked
ingress, snapshots, reset projections, GPIO sampling, timer/lease/watchdog logic,
supervisor input/output and scaling request/publication boundaries remain explicit.
Separate native SRAM controllers retain word ownership, sequence bytes and assemble
reads around explicit synchronous macro boundaries. Separate native I2C controllers
pass digital verification; wire sampling, timeout and host publication remain clocked.
SPI ADC remains clocked. The independent LF timebase/watchdog remains
necessary. See the [migration checklist](docs/async-soc-migration.md). A permanent
Groundlark controller supervises power before upload and during application
stalls. Its state, safety sample record and confirmation counters now reside
in independent native loops, with dedicated POR-only command/reply bridges. Its default policy is disabled until qualified battery settings are
provided. Watchdog recovery resets the application and its CPU bridges while
preserving the power supervisor, sensing, timebase, validated image and programming
lock. The host can explicitly restart that image and distinguish successive
recoveries through the retained `CRASH_COUNT` status word. Reset pins assert
immediately; ordinary service logic and clock-gate demand are synchronized.
Only manual/POR/brownout reset
or MCU power loss clears the lock and returns Groundlark to its off state.
**Tapeout must deliberately supply and qualify an enabled board policy**; the
reference emitters' disabled `PowerPolicy()` never enables Pi power.
Physical/analog, pin/package, board and Chiselator qualification remain.
The new Fabric, Control, Telemetry, arithmetic, Supervisor, SRAM and I2C controllers have
no physical timing qualification.
Earlier P&R results describe baseline `8637099` and do not qualify this migration.

Both variants have [experimental GF180 implementation inputs](docs/gf180-implementation.md):
preserved async bindings, native matched-delay cells, compact digital tops, SRAM
power bindings, and separate clocked/async checks. Five-corner cell and
whole-transform characterization informs the physical timing budgets. These
support a first floorplan/P&R experiment; extracted timing, analog layouts and
padframe qualification remain outstanding.

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
each SoC implementation and its protocol controllers/storage belong in its own
design folder. `soc/` shares schemas, fixed macros and wrapper utilities. Complete
SoC tops use internal memory; standalone core tests retain
independent memory models. Optional peripherals, compressed instructions and
additional architecture variants are on hold.

The [Groundlark I/O contract](docs/groundlark-io.md) maps battery sensing, shutdown,
halt acknowledgement, and power-on control. The reference digital build uses a
separate three-signal SPI ADC; physical pads and analog integration remain open.
Compiled memory budgets are recorded in the [memory architecture](docs/memory-architecture.md).
[GF180 planning estimates](docs/gf180-estimates.md) cover the `4b5d105` full-capacity
baseline: approximately 2.6 mm² of digital cells and 14–19 µW nominal retained
standby including the shared analog circuits, before pad/external-device power.
The subsequent reset/writeback review fixes require fresh mapping and wake
measurements before applying those numbers to current RTL. The baseline protocol
difference is smaller than the estimation uncertainty. Placement,
async-cell characterization and extracted timing/power remain outstanding.

Project licensing is recorded in [LICENSE](LICENSE). Reused third-party material
retains its own license and attribution.
