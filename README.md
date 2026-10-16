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
Native SRAM requests retain full 32-bit byte offsets through upstream admission
validation and the macro controller's firing-lane range assertions.
The macro controller relies on that valid-offset contract and saves only the configured address width (11 program / 10
working-RAM bits for Groundlark), then selects a bank and its ten-bit macro
address; see the [C1f evidence](docs/sram-integration.md#c1f-saved-address-narrowing). Native loader metadata
retains capacity-sized byte counts and entry offsets: 12-bit length/received
counts and an 11-bit entry offset at 2 KiB. Host fields remain 32 bits and are
validated before narrowing; see the [loader contract](docs/loader-status-and-lock.md#retained-loader-metadata-a2b). Both
cores use a 171-bit control token and derive pending load fields from the saved
instruction, avoiding duplicate storage.

The common host interface reports device/loader state, generic measurements and
application registers. Groundlark binds these to battery voltage and supervisor
state. Programming lock lasts until full MCU reset or power loss; status and
telemetry remain readable when locked. See the
[host status, telemetry and lock contract](docs/loader-status-and-lock.md).

**Status: correcting excessive clocked coordination around native services;
physical timing is unqualified.**
Both design folders own independent native implementations of CPU/fabric routing,
MMIO and loader state, telemetry/events, arithmetic, permanent supervision,
SRAM word sequencing, I2C/SPI protocol and housekeeping. Click remains native
two-phase. Digital verification covers the documented scopes in the
[migration checklist](docs/async-soc-migration.md).

Clocked service coordination, observation and publication boundaries remain,
along with synchronous SRAM macro access, wire sampling and the independent
LF timebase/watchdog. The [remaining-state ledger](docs/async-residual-state.md)
tracks removal candidates; a smaller clocked-bit count does not establish lower
area or power. The [native area reduction plan](docs/native-area-reduction.md)
targets elapsed/CRC arithmetic, wide payload transport and duplicate storage,
with measured cost gates. The bounded native elapsed loop preserves the time ABI;
compact native CRC feedback removes redundant command storage. The I2C
observation projection removes 325 native storage bits per variant. The compact
[SPI player](docs/spi-player-contract.md) removes 90 clocked bits per variant;
the addressed [I2C receive store](docs/native-i2c-byte-store-contract.md) removes
another 513 native payload bits. CPU request receipts remove 70 duplicate
clocked bits per variant. Capacity-sized loader metadata removes
183 native payload bits and 40 periodic bits per variant.
The latest mapped logic area is **2.830967 / 3.596523 mm²**, excluding SRAM.
All 27 ordinal wake windows per variant remain unchanged; the 43-instruction firmware wakes still use 3,255 BD / 3,160 Click work-clock edges. A2b functional and strict export checks pass; physical timing remains unqualified.
The [A2b evidence](docs/reviews/loader-metadata-a2b-completion.md) records its
checks and measured costs.
An [opt-in Control buffer repair](docs/reviews/control-electrical-repair.md)
reduces the measured data-path maxima and fixes two selected net overloads
without changing native handshakes. Complete capture/hold timing remains open.
The [native Control characterization](docs/reviews/control-native-characterization.md)
retains physical feedback and all payload storage cells; unresolved simulator
sampling is an explicit gate before further timing claims.
The [relative-timing pilot](docs/reviews/control-relative-timing.md) resolves
local Control capture/ACK paths under explicit handshake states at five cell
corners. Source launch, full return/pulse behavior, electrical repair and routed
timing remain open; no hardware clock or shortened guard is introduced.
The [reusable stage survey](docs/reviews/native-stage-timing.md) applies those
local checks to execute, elapsed, SRAM and I²C update. Negative execute/elapsed
allowances remain visible; custom I²C publication and those stages' upstream launch stay open.
The [Control Join check](docs/reviews/control-join-timing.md) composes its actual
operand storage and update capture at all five corners under explicit admission states; full source
reuse, other transition histories and physical qualification remain open.
The same template now measures [execute's Join paths](docs/reviews/execute-join-timing.md).
Their conditional margins are positive; the 480 independent register-file bits
and elapsed's seeded owner remain uncomposed. Global electrical repair is now the
first gate in the default mapper; timing campaigns consume its proved graph.
The [electrical-first correction](docs/reviews/electrical-first-correction.md)
also adds independent owner timing policies and longer elapsed/execute request
guards plus a native BD Control ACK guard. These targets remain unqualified;
no clocked pipeline or shorter matched delay is introduced.
See the [elapsed](docs/native-elapsed-contract.md) and
[CRC](docs/native-crc-contract.md) contracts. Wider payload reductions remain
open. Self-timed SRAM access follows a separate
[candidate contract](docs/native-sram-clock-contract.md) and requires complete
macro timing qualification; the millisecond and scaled-value ABI remains unchanged.
The [experimental native byte owners](docs/experimental-native-sram-byte.md)
have a maintained digital verification campaign and are not instantiated in the SoC.
Each migration item requires fresh independent review, fixes,
verification, documentation and a separate commit/push.

The reset-domain and reset-interval corrections pass digital verification and
independent review. After receiver closure and rebase, native reset remains
asserted for 64 qualifying service edges; core reset and isolation remain for
another 64 edges after native release. The short-pulse qualifier is separate. The completed
[matched comparison](docs/gf180-matched-comparison.md) favors the smaller clocked
service island: migrated services substantially increase area, leakage estimates
and wake work. The subsequent correction targets duplicate storage and crossings
while keeping native BD/Click and all later correctness fixes. Native frame
stores now own bank rotation, and service replies use their retained native
payload at consumer acceptance. A further digitally verified cleanup
removes **538 duplicate clocked payload bits per variant** from peripheral and
SRAM receivers. Its matched mapped logic area falls **1.78% BD / 1.41% Click**;
measured wake clock counts and durations are unchanged. See the
[service capture contract](docs/service-reply-capture-contract.md) and
[peripheral/SRAM capture contract](docs/held-peripheral-capture-contract.md).
Complete native service scheduling and physical capture qualification remain open.
CPU request ingress captures the retained native payload directly, with zero
outside valid and unchanged gated capture/reset coordination. Its
[verification and cost results](docs/application-reset-boundary.md#c1e1-retained-cpu-request-receipt)
cover both protocols; smaller grant/drain payload copies remain a separate item.
Complete physical reset-tree and core-startup timing remain open; current guard
measurements exceed some digital assumptions.
See the [reset-boundary contract](docs/application-reset-boundary.md),
[guard contract](docs/physical-control-guard-contract.md),
[frame-admission contract](docs/frame-admission-contract.md) and
[physical export contract](docs/physical-export-contract.md). The matched P&R
runs preserve open timing violations and do not qualify either implementation.

Groundlark's permanent controller supervises power before firmware upload and
during application stalls. Application watchdog recovery must preserve power
supervision, sensing, timebase, validated image and programming lock; the host
can restart the retained image and distinguish crashes through `CRASH_COUNT`.
Only full MCU reset or power loss clears the lock. **Tapeout must deliberately
supply and qualify an enabled board policy**: the ordinary reference emitters'
disabled `PowerPolicy()` never enables Pi power. Physical/analog, pin/package,
board and Chiselator qualification remain outstanding.

Both variants have [experimental GF180 implementation inputs](docs/gf180-implementation.md):
preserved async bindings, native matched-delay cells, compact digital tops, SRAM
power bindings, and separate clocked/async checks. Five-corner cell and
whole-transform characterization informs the physical timing budgets. These
supported a [first P&R experiment](docs/gf180-first-pnr.md): both designs routed
on a common 1.44 mm square digital outline with zero detailed-router violations.
That experiment used the older `8637099` RTL and does not qualify this migration.
Extracted timing exposes reset and local capture-distribution problems; timing
closure, full physical verification, analog layouts and pads remain outstanding.

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
[GF180 planning estimates](docs/gf180-estimates.md) report the current mapped
candidate's area, listed-state leakage and simulated wake activity alongside
the historical baseline. They do not establish physical timing, measured
standby power or an overall area/power improvement from the migration. Each
correction retains its own matched cost and activity evidence.

Project licensing is recorded in [LICENSE](LICENSE). Reused third-party material
retains its own license and attribution.
