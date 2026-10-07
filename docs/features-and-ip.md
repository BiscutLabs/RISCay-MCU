# RISCay-MCU feature and IP plan

Draft, 2026-10-07. RISC-V is required. Build in Chisel and chisel-async, verify
first on an existing event simulator, then use the same application to qualify
Chiselator. The first RV32E core RTL and tests now exist in both design folders;
the remaining MCU features below are still planned. See the
[execution contract](execution-contract.md) for implemented behavior.

Scope decision: implement both four-phase bundled data and native two-phase
Click in separate design folders, with the same essential MCU features and
comparison workload. Optional features are on hold. See the shared
[board I/O contract](groundlark-io.md).

Groundlark is the first deployment profile. The [reusable interface](reusable-interface.md)
separates common MCU/loader/measurement resources from its battery/Pi behavior.
The inventory below includes both reusable IP and Groundlark's required bindings;
other profiles do not inherit its pin names, battery thresholds or power policy.

Both implementations are SoCs with on-chip boot ROM, executable RAM and working
RAM. No external memory chip is required. Host-assisted application reload after
power loss is in scope. Groundlark's bootstrap must start its Pi without the
missing application; each profile owns its boot policy. See the
[memory architecture](memory-architecture.md).

## Application and scope

The first target is the Groundlark DAQHAT-01 Pi power supervisor, U130,
MSPM0L1106TRHBR. It controls an external regulator/load switch; the MCU does not
carry the Pi supply current. The current HAT profile targets a Pi 4 stack and
has an always-on 3.3 V supervisor supply. The FPGA supply remains independent.
[Groundlark power design][groundlark-power]

The board uses three digital control signals and one battery measurement:

| Function | Current connection | RISCay requirement |
| --- | --- | --- |
| Pi power enable | PA3 / RUN | Defined output on power-on, CPU reset, watchdog and brownout |
| Shutdown request | PA4 through Q130 to Pi BCM6 | Request output compatible with the existing transistor interface |
| Halt acknowledgement | Pi BCM13 through Q131 to PA5 / ACK_N | Active-low MCU input, qualified for the current boot |
| Battery voltage | PA27 / ADC0.0 through R135/R136 | Numeric voltage measurement with validity and calibration |

These functions are confirmed by the [target firmware][groundlark-target] and
[supervisor guide][groundlark-supervisor]. Ready, heartbeat, user button, and RTC
alarm are useful extensions, but are not all connected in this existing interface.

Plan for a functional replacement with a possible HAT revision. A drop-in U130
replacement would additionally require its footprint, pinout, supply and analog
compatibility. ARM SWD programming compatibility is not implied by RISC-V.

## Essential feature and IP inventory

"Required" means the capability must exist in the system. It does not require
every analog or timing function to be integrated on the MCU die.

| Priority | Feature / IP block | Proposed minimum and purpose |
| --- | --- | --- |
| Required | RISC-V instruction engine | RV32E bring-up, RV32EC target; sequential execution with one instruction in flight. Sixteen 32-bit architectural registers, including constant x0. No cache or speculative execution. |
| Required | Datapath and register storage | Register file, PC, decoder/immediates, ALU, shifts/comparisons, branch/jump logic and load/store unit. Use the same simple 32-bit datapath in both initial implementations; datapath-width experiments are on hold. |
| Proposed target | Compressed instruction decoder | C extension and mixed 16/32-bit fetch to reduce firmware storage; measure total decoder-plus-ROM cost before freezing the choice. |
| Required | Program storage and boot | Permanent on-chip boot ROM with profile-specific startup and common image loading; size after linking. Configurable on-chip executable RAM, provisionally 2 KiB for Groundlark. A host supplies the image after power loss. No external memory chip; fixed ROM itself is not reprogrammable. |
| Required | Host firmware loader | I2C target initially; common device/loader ABI, explicit image/application compatibility, transfer bounds and validation. Groundlark shares its Pi's existing bus; other hosts use the same protocol. Profile bootstrap keeps required control functions active while loading. |
| Required | Loader status and programming lock | Readable mode, validated-image flag, running state, programming availability, lock and last error on the same host interface. Hardware lock blocks image/metadata modification until full MCU reset or MCU power loss; Pi reboot and I2C reset do not clear it. See the [loader contract](loader-status-and-lock.md). |
| Required | Data RAM | On-chip, provisional 256 bytes for application state and stack, separately from program RAM and architectural registers. Portable flip-flop implementation initially; evaluate SRAM for the combined writable-memory capacity. Explicit initialization, byte writes, alignment and access-error behavior. Size from measured stack/state use. |
| Required | Memory/MMIO fabric | Small address decoder and request/response interfaces with one outstanding transaction; defined ordering, byte enables, errors and commit points. Avoid a full bus fabric unless an actual peripheral requires it. |
| Required | Generic GPIO | Input, output and output-enable vectors with profile-defined roles, qualification and safe reset values. Groundlark binds three GPIOs to power enable, shutdown request and ACK_N; both protocols use identical bindings. |
| Groundlark required | Battery measurement frontend | One low-rate ADC channel with reference, settling, calibration and sample validity; provisionally 12-bit conversion. Publish through generic measurement channel 0. External ADC interface selection remains open; a different profile may have zero analog channels. |
| Required | Independent timebase and deadlines | Low-frequency tick input or oscillator/RTC subsystem, monotonic counter and next-deadline compare. Supports sampling, voltage confirmation, shutdown timeout and minimum off interval while the CPU is inactive. |
| Required | Event capture and wait | Pending event bits, atomic acknowledge and a blocking MMIO wait candidate; no lost wakeup when event, clear and sleep coincide. Defined pulse-width or held-level contracts at every input. |
| Required | Independent watchdog | Detect stalled CPU/firmware and recover while the core is quiescent or a transaction is stuck. To cover loss of the primary timebase, it needs a separate reference or an external watchdog. |
| Required | Reset and output policy | Power-on/brownout input, reset distribution and handshake initialization. Reset forces RUN off in the Groundlark compatibility profile; retained RUN is on hold. |
| Required | Validated configuration | Voltage thresholds, hysteresis, confirmation times, timeout and minimum off time. Bootstrap must contain sufficient qualified policy to start and supervise the Pi before upload; invalid/disabled policy cannot start it. Separate configuration updates remain on hold. |
| Required | Supervisor firmware | Battery recovery/start, run, shutdown request, acknowledgement, timeout, discharge/off wait and latched fault. Distinguish acknowledged shutdown from forced removal. |
| Required | Status and fault registers | Current mode, measurement validity, timeout count and reset/fault reason. Define which fields survive CPU reset; persistence across complete power loss is optional. |
| Required | Host-readable telemetry | Generic channels expose value, unit/scale, validity, age/sequence and calibration flags. Versioned application registers expose profile-specific state. Groundlark maps these to battery/supervisor data. Coherent read-only snapshots remain accessible while locked. |
| Required for development | Observation and test interfaces | Instruction retirement and committed MMIO trace, channel monitors, memory preload/readback and deterministic fault injection. Simulation visibility is not a promise of a hardware debug port. |

The [RV32E specification][rv32e] defines the reduced register set. Serialization
changes the internal datapath, not the 32-bit ISA semantics. Software multiplication
or division helpers may still be needed for voltage conversion; include them in
ROM and stack measurements rather than assuming the TI binary size transfers.

For the execution environment, freeze endianness, reset PC, memory map, supported
access sizes, misalignment, illegal instructions, ECALL/EBREAK and recovery. A
blocking MMIO wait avoids inventing a sleep opcode. Architectural WFI would need
an explicit privileged/interrupt contract; RV32EC alone does not specify one.

## Measurement and analog boundary

Battery measurement cannot simply disappear: the existing policy consumes a
numeric voltage and applies configurable thresholds. An external ADC preserves
that capability with a revised board. An integrated ADC would require analog IP,
reference and pad work beyond Chisel RTL. Comparator threshold inputs are a
possible reduced design, but change the configuration/measurement contract.

Define total battery-referred error, including divider, reference, ADC, offset,
temperature and settling, before choosing ADC resolution. Carry sample validity
and age into firmware; stale data must not silently authorize restart. Initial
simulation uses an ADC transaction model, not an invented digital connection to
the board's existing analog pin.

Keep the battery BMS/charger, buck regulator, load switch, power protection and
GPIO isolation external. Model voltage warnings and available shutdown time;
graceful shutdown requires sufficient remaining energy in the real system.

## Groundlark policy versus the earlier Chiselator draft

The [implemented Groundlark policy][groundlark-policy] is the initial compatibility
reference. Its existing native tests are useful porting fixtures. Some text in
the power guide still describes firmware as a placeholder; the firmware and its
README show that a prototype exists, with physical qualification still pending.

| Topic | Current Groundlark implementation | Earlier Chiselator draft | Planning treatment |
| --- | --- | --- | --- |
| Pi profile | Pi 4 HAT | Pi 5 proposed first | Start with the actual Groundlark Pi 4 profile. |
| Supply sensing | ADC voltage measurement | External threshold/event input | Preserve voltage measurement; integration is a separate decision. |
| MCU reset | RUN falls off via pulldown | Retain RUN on CPU reset | Use fail-off for both implementations; retention is on hold. |
| Missing shutdown ACK | Cut power after timeout; latch off after three such timeouts | Preserve power by default; forced-off optional | Represent the current bounded forced-off behavior explicitly; no timeout is reported as graceful shutdown. |
| Host health | Halt acknowledgement; no separate ready/heartbeat path | Ready and heartbeat monitoring | Optional extensions requiring Pi/software/interface changes. |

Do not describe the existing timeout count as failed-boot detection: the current
interface does not establish successful boot. Add readiness/heartbeat only if
that behavior is required. Strengthen current-boot ACK qualification and test the
actual kernel poweroff pulse pattern before accepting either profile.

## Reuse from chisel-async

The inspected library has digital implementations and export contracts, not
qualified silicon cells. Reuse its public API and pin the consumed revision.
[Component catalog][async-components]

| Need | Existing library IP | MCU-specific work |
| --- | --- | --- |
| Module/protocol structure | `AsyncModule`, `ResetDomain`, `Channel[T]`, `DesignContract` | CPU/peripheral composition, reset topology, exported IDs |
| Four-phase storage/control | `FourPhaseStage`, `LongHoldBuffer`, FIFO, fork/join, mux/demux and exclusive merge | Instruction sequencing, feedback initialization and datapath transforms |
| Native two-phase storage | `ClickStage`, `ClickBuffer`, Click FIFOs and phase-decoupled variants | Equivalent CPU experiment; account for routing and conversion overhead |
| Clocked peripheral bridge | `DecoupledToFourPhase`, `FourPhaseToDecoupled`, `AsyncMemoryPort` | Timer/ADC/memory backends with explicit local clock and latency |
| Event delivery | `PendingEventBridge` | Sampling qualification, event/clear races, optional pulse capture; this bridge coalesces sampled rising edges and is not an arbitrary pulse catcher |
| Arbitration | Arbiter and finite digital MUTEX model, only where concurrent sources require it | Arbitration policy and later physical metastability qualification |
| Verification/export | `AsyncTest`, primitive views, timing metadata, `ExportDesign` | MCU scoreboards, retirement trace, board models and Chiselator fixtures |

`AsyncMemoryPort` bridges transactions; it is not RAM/ROM storage. A sequential
CPU with one memory master need not acquire a general arbiter merely because the
library supplies one. Avoid empty, free-running token loops during event wait.

## Two implementations to compare

Both designs are required. Neither is selected as the final winner. Keep their
protocol-specific implementations separate:

| Directory | Ownership |
| --- | --- |
| `designs/four-phase-bd/` | Four-phase controllers, storage, core integration, top-level emission and protocol-specific checks |
| `designs/two-phase-click/` | Native Click controllers, storage, core integration, top-level emission and protocol-specific checks |
| `shared/` | Common ISA/MMIO and board contracts, pure datapath functions where appropriate, firmware and independent test inputs/oracles |

Both core RTL implementations exist. The shared datapath has no protocol state;
four-phase uses long-hold composition and Click uses native storage and native
fork/join routing. Memory/peripheral integration and supervisor firmware remain.

| Candidate | Why it belongs in the comparison | Cost or obligation |
| --- | --- | --- |
| Four-phase bundled data | Broad existing composition support and explicit return-to-idle behavior | Request/data timing, latch/control assumptions and extra handshake transitions must be checked. |
| Native two-phase Click | Local handshake pulses and edge-triggered registers; worth testing for control overhead and implementation cost | Data setup/hold, pulse width, local trigger skew and reset must close. MCU-specific native fork/join routing needs its own verification and later physical closure. |

Use actual native Click components for the two-phase experiment. The library's
general `TwoPhase*` components wrap four-phase implementations, so their external
protocol alone does not establish a native two-phase comparison. The current
Click timing-export flow also lacks complete physical pulse/aperture analysis.
[Click implementation and limitations][async-click]; [original Click paper][click-paper]

Compare a fixed ISA, firmware, memory capacities, peripheral policy and workload
in both designs. Keep the same datapath width so its effect is not mistaken for
a protocol benefit. Use idle/battery polling, normal shutdown/restart,
slow peripherals, simultaneous events and fault recovery as workloads.

Rank correctness and bounded response first. Then compare active work per wake,
quiescent switching, storage/control cost, bridge overhead and verification effort.
Later, with a selected process, measure mapped/routed area, timing over operating
corners, energy per action and total standby current including ADC, timebase,
regulator, divider and interfaces. Simulator delay presets and switching counts
do not establish watts, leakage, or battery life. Peak instruction rate is secondary.

## Optional and excluded IP

Pi-assisted volatile application reload after power loss is required. It does
not imply embedded flash, persistent updates or a general diagnostic interface.

Manual wake, RTC scheduling, ready/heartbeat monitoring, a serial diagnostic
interface, external configuration EEPROM, persistent firmware update and warm-reset output
retention are explicitly on hold. Do not implement or allocate dedicated pins
for these optional functions in either variant. QDI, a separate GALS comparison,
and serialized-datapath experiments are also outside the current two-design scope.

The first implementation does not need DMA, caches, MMU, floating point, vector,
hardware multiply/divide, a general interrupt controller, USB, Ethernet, CAN,
sensor acquisition, PWM banks, battery charging, or embedded flash. Physical
debug/programming access, scan/test, pad cells, brownout/POR circuitry, memory
macros and characterized async cells remain necessary later implementation work;
they are not supplied merely by generating RTL.

## Verification and next design gates

1. Freeze the Groundlark signal/policy profile and MCU execution environment.
   Use identical fail-off reset and bounded shutdown-timeout behavior in both designs.
2. Compile the actual supervisor policy for RV32E/RV32EC. Retain ELF, image, map,
   disassembly, helper routines and stack measurements; adjust provisional memory
   budgets to fit complete tested firmware.
3. Implement CPU and peripheral contracts with independent instruction and
   supervisor-policy references. Reused production C tests establish porting
   consistency, not an independent oracle by themselves.
4. Verify normal and OS-initiated shutdown, voltage hysteresis, ADC timeout/stale
   samples, missing/stale ACK, repeated timeout lockout, timer wrap, watchdog,
   reset at every handshake phase and simultaneous event/clear/wait. Pin firmware
   and stimuli; check committed MMIO effects exactly once and never assume reset
   can undo a switch command that already committed.
5. Exercise randomized legal delays and backpressure, and demonstrate checkers
   reject dropped events, duplicate writes and premature power cuts. Compare
   architectural effects, not internal cycles. Test both binary and compressed
   instruction execution before claiming RV32EC support.
6. Establish the external event-simulator corpus, then replay it in Chiselator.
   Real Pi behavior, analog accuracy, physical timing and power remain later
   board/silicon qualification gates.

The initial core and native-routing suites are implemented; see
[build and test](build-and-test.md). Full ISA qualification, the supervisor policy
and MCU peripheral suites remain. Do not treat core tests as whole-chip acceptance.

## Source snapshot

Inspected local Groundlark revision `3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3`,
chisel-async revision `468b12eb362f368e0ff25e376ec3a4489de242a3`, and the earlier
Chiselator `docs/async-mcu.md` at revision
`033119785600d8b7427adf6dfad275f4d80aaa49`. These are research snapshots, not yet
build dependency locks. Groundlark's existing supervisor code is MIT licensed;
chisel-async is Apache-2.0. Preserve attribution when reusing implementation.

[groundlark-power]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/docs/power-supplies.md
[groundlark-supervisor]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/sw/supervisor/README.md
[groundlark-target]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/sw/supervisor/firmware/mspm0.c
[groundlark-policy]: https://github.com/naturalhazardscience/groundlark/blob/3f92e1b4b9a7f5af35dec87e5f9ff2f32aac84f3/sw/supervisor/firmware/power.c
[rv32e]: https://docs.riscv.org/reference/isa/v20240411/unpriv/rv32e.html
[async-components]: https://github.com/BiscutLabs/chisel-async/blob/468b12eb362f368e0ff25e376ec3a4489de242a3/docs/components.md
[async-click]: https://github.com/BiscutLabs/chisel-async/blob/468b12eb362f368e0ff25e376ec3a4489de242a3/docs/click.md
[async-qdi]: https://github.com/BiscutLabs/chisel-async/blob/468b12eb362f368e0ff25e376ec3a4489de242a3/docs/dual-rail.md
[click-paper]: https://arc.cecs.pdx.edu/wp-content/uploads/2023/04/Peeters_Click_ASYNC2010.pdf
