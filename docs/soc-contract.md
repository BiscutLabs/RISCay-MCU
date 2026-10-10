# Implemented SoC contract

The four-phase and native Click SoCs implement the same RV32E execution, internal
storage and peripheral behavior. Compressed instructions remain deferred. The
CPU, transaction routing, Control, Telemetry, Supervisor, Housekeeping, I2C and SPI ADC protocol state
loops are asynchronous.
Each design owns its native loader/MMIO, software GPIO/application-word, event
and host measurement state. Ingress, snapshots, reset projections, GPIO sampling,
independent LF/watchdog and heartbeat delivery, individual synchronous SRAM byte
accesses, I2C wire sampling/timeout and SPI pin timing/full-frame capture remain
clocked. Native Housekeeping owns NOW/board time, deadline/lease/wake-mask state,
watchdog kick authorization and low-power acquisition cadence. Elapsed ingress
still feeds observation/freshness history independently of housekeeping stalls;
only final housekeeping publication advances consumedGray. Native SPI loops own conversion admission, frame definition, assembly,
priming, scaling and retirement; item 8 passes digital verification and strict exports.
Separate native SRAM word sequencing passes the
item 6 digital regressions and strict exports. Board policy and its safety sample view
use independent POR-only native loops with clocked ingress/output projection.
ROM/static faults complete in the native fabric. The Control integration passes
the digital regressions and strict exports documented in the current checklist.
See the [migration checklist and handshake contract](async-soc-migration.md). Its
default clock is 10 MHz. Reference emitters stop that source during retained sleep
and use nominal 7.7307 Hz for the always-on timer and watchdog (32-cycle timeout,
two-cycle reset hold). The portable tops expose both clocks and a service-source
enable; generated chip wrappers contain both on-die oscillator boundaries.
Legacy builds with `lowPower=None`
retain service-derived time and the independent watchdog input. Include the
islands, clock source, CPU admission and per-source completion crossings in comparisons.
Native completion assembly connects production replies directly from the
selected-input join to Fabric; checklist substep 10a passes digital verification,
independent review and both strict SoC exports.
Admission captures an immutable immediate response and completion mask. Selected
memory/Telemetry/Housekeeping tokens may arrive independently; only their native
join can publish the CPU reply. Application reset cancels this presentation path,
while existing POR effect owners finish accepted persistent work. A synchronized
retirement phase and full crossing/output drainage prevent premature reuse.
MMIO clear protection starts when a held request arrives, including events raised
while previous response return delays its dispatch. Existing events predating
that arrival remain clearable. Source-ready assertions reject completion loss.
These are digital RTL implementations, not qualified physical cells or pads.
See [sleep and clock integration](sleep-and-clock.md) for the exact gating scope.

## Memory and CPU interface

| Byte address | Region | Permissions |
| --- | --- | --- |
| `0x00000000..0x0000000b` | 12-byte constant boot ROM | Read/fetch only |
| `0x10000000` + configured capacity | Executable program RAM | Host loader writes; CPU reads/fetches only after validation, within image length |
| `0x20000000` + configured capacity | Working RAM | CPU data reads and byte-masked writes; no instruction fetch |
| `0x30000000..0x3000004b` | MMIO | Aligned 32-bit data accesses only |

All storage is on chip. Groundlark uses two 1 KiB GF180 SRAM macros for program
storage and one for its 1 KiB working RAM. Each variant's controller sequences four
byte operations per word through native rendezvous; macro inputs launch on falling
service-clock edges. Native execution credit waits for final response acceptance.
See [SRAM integration](sram-integration.md). RAM is not reset-cleared. POR/manual/brownout reset
clears image validity; watchdog recovery preserves it. Application startup must initialize
its data, BSS and stack before use. No simulator preload is necessary or used by
the serial upload tests. A successful store returns data zero; read responses are
aligned little-endian words. Unmapped/protected accesses return an access error.
One accepted CPU transaction produces one response, held stable under backpressure.
The service-clock `commit` observation pulse denotes endpoint request acceptance
(local ROM/static-fault replies do not pass that endpoint); SRAM writes finish
later, before successful completion. Watchdog reset discards CPU replies but
allows accepted stores to finish. Full POR/manual/brownout reset aborts remaining
bytes and may leave a partial word; it does not undo committed bytes. SRAM
controllers and loader accounting survive application reset. Sleep is inhibited
until all accepted memory operations finish.

The native Control loop serializes loader and MMIO commands using one retained
state token. Host frames carry their reset/busy context through a bounded ingress
mailbox; an operation received while busy is rejected, never deferred into an
upload side effect. Lock/image/accepted SRAM accounting and the control bridges
are POR-only. Application reset is a retained synchronized command; queued HALT
and unaccepted CPU work are canceled, and stale START replies cannot restart the
application. MODE still observes the synchronized reset on the third service
edge through a clocked status projection.

MMIO preparation performs native validation without mutating retained staging.
The service-clock `commit` accepts a successful write and creates a retained
native commit token. Accepted producer staging survives application reset;
unaccepted preparation has no state effect. A commit precedes reset recovery,
which clears the application word selector but preserves producer staging.
Software GPIO/application words, event flags and host sample records commit in
the separate native Telemetry loop. Accepted publications survive application
reset; application-owned GPIO/word/event effects and their CPU completions are
canceled by reset. Timer/peripheral effects, WAIT qualification, observation
ingress and coherent read snapshots remain clocked. MMIO still crosses those
explicit boundaries.

The ROM executes `lui x1,0x30000; lw x2,0(x1); jalr x0,x2,0`. The load blocks
until START, then returns the validated absolute entry address. Control transfer
does not reset the SoC or board outputs. Registers follow the core reset contract;
the ROM clobbers x1/x2. A separate permanent board controller handles startup and
supervision, including when no application exists. The loader is fixed hardware.

| MMIO offset | Read | Write |
| ---: | --- | --- |
| 0 | Wait for START; return entry address | Error |
| 4 | Milliseconds, wrapping unsigned 32-bit | Error |
| 8 | Deadline | Replace deadline, consume its previous pending event, and arm one-shot; use a future interval less than 2^31 ms |
| 12 | Pending events | Write-one acknowledge |
| 16 | Wait for an enabled pending event, without clearing; lease expiry and host wake always qualify | Error |
| 20 | Synchronized GPIO inputs | Error |
| 24 | Effective GPIO outputs | Set generic output latch; board-owned bits stay protected |
| 28 | Effective GPIO enables | Set generic enables; board-owned bits stay protected |
| 32 | Zero | `0x57444f47` services watchdog; other values error |
| 36 | Measurement producer index | Select an existing channel |
| 40 | Producer value staging register | Stage signed 32-bit value |
| 44 | Zero | Publish staged value: bit 0 valid, bit 1 calibrated; permanently acquired channels reject CPU publication |
| 48 | Application word index | Select a profile-declared word in 0..63; holes reject |
| 52 | Selected application word | Update firmware-owned word; board-owned words reject writes |
| 56 | Wake mask (reset `0x0f`) | Bits 0..5 only; tick can be masked independently of timekeeping |
| 60 | Remaining sleep lease, ms | Arm/cancel finite lease; does not kick watchdog; requires low-power build; default maximum 60000 ms |
| 64 | Applied ADC sample period, ms | Request new period; requires low-power build and ADC; applied between conversions |
| 68 | Timing status | Error |
| 72 | Service clock sleep-entry count | Error |

Blocking reads at offsets 0 and 16 apply only to valid aligned full-word accesses.
Unsupported byte/halfword reads return an access error immediately when the
fabric can accept a transaction; they do not park the CPU, authorize sleep,
consume pending events or cancel its sleep lease.

Events are bit 0 time-maintenance tick, bit 1 deadline, bit 2 any configured GPIO
change, bit 3 acquisition result, bit 4 sleep lease expired, bit 5 host wake.
Bits 4/5 bypass the wake mask. Events coalesce. Set wins a simultaneous
acknowledge. Events raised during a native MMIO validation window also win that
transaction's clear; a deadline replacement still consumes only its previous
deadline event. GPIO uses two sampling stages; pulses must last at least three
service cycles after oscillator startup and meet the eventual synchronizer implementation's constraints.
Blocking the CPU never blocks host status or the permanent controller.
Firmware acknowledges only consumed bits before processing the wake. The
`wait_events()` helper never clears pending bits; `acknowledge_events(bits)` is
explicit. Edges arriving during processing remain pending for the next wait.
Repeated edges on one already-pending bit still coalesce by design.
An accepted deadline write also suppresses the old deadline if it becomes due
on that same edge. Other pending/new events survive. A newly written deadline
that is already due can fire starting on the following edge; malformed or
rejected writes do not clear anything.

## Host wire protocol v1

Default I2C address is **0x35**, configurable at elaboration; verify address
availability on the intended board. SDA is represented by input plus open-drain
pull-low output. SCL is an input. No stretching or multimaster MCU operation.
Use standard-mode 100 kHz or fast-mode 400 kHz with the default service clock;
the digital sampling contract requires at least eight service cycles per SCL
period and four per high/low phase. Native protocol processing also requires an
absolute latency bound; the current 1..10 ns cell/10 ns data simulation envelope
is exercised at 400 kHz with 3.2 MHz and 20 MHz service clocks. A clock-cycle
ratio alone does not qualify arbitrary faster clocks. Electrical rise-time/pad
and physical native timing qualification remain.

**Source-stopping builds require a wake preamble before each new transaction:**
send an address-only write probe and STOP (ACK or NACK accepted), wait 100 us,
then start the actual transaction within 50 us. The probe carries no opcode/data.
Repeated STARTs inside an active transaction need no preamble. See
[sleep and clocks](sleep-and-clock.md) for adapter requirements and source bounds.

An inactivity timeout aborts an unfinished transaction after 262144 service
cycles without a synchronized SCL/SDA edge (13.1072..32.768 ms at 20..8 MHz).
It releases SDA and discards the buffered command without committing it.
This SMBus-style recovery bound is not a claim of SMBus protocol compliance.
STOP, final read NACK and foreign-address rejection release transaction activity.
The native state retains rejection for reliable CDC; the clocked boundary emits
one rejection event to source-wake policy, so an old rejection cannot cancel a
later START. The separate native BD/Click controllers own protocol/byte/serializer
state. SCL/SDA sampling, captured-edge ingress, inactivity timing, coherent host
bank capture and frame/read-start publication remain explicit clocked boundaries.
See the [migration contract](async-soc-migration.md#i2c-scope-and-timing-contract).

A write transaction begins with an opcode, followed by the exact payload below.
All multi-byte numbers are unsigned little-endian words unless described
otherwise. STOP or repeated START accepts a completed frame. An accepted WRITE then
commits its four SRAM bytes before advancing RECEIVED_BYTES and CRC.
Incomplete/oversize/unknown commands cause no image mutation. ACK means the byte
was received; read LAST_ERROR to determine command acceptance. Command completion
and service-domain status publication follow frame acceptance; STOP does not
promise an immediate status-pin update. Verification preserves the earliest
next on-wire status read, without extra SELECT transactions or polling delays.
There is no queue of pending writes and no deferred memory write after a command completes.

| Opcode | Payload after opcode | Effect |
| ---: | --- | --- |
| 0 SELECT | Three bytes: space, instance, starting word | Select read window; no loader-state/error clearing |
| 1 BEGIN | Eight words: length bytes, entry offset, expected CRC32, ABI, required working RAM bytes, required GPIO bitmask, required measurement count, image ID | Validate metadata, invalidate old image, start new upload |
| 2 WRITE | Two words: byte offset, data | Append exactly four bytes at next expected offset |
| 3 VERIFY | None | Validate completeness and CRC; enter READY |
| 4 LOCK | None | Lock validated image; repeat is idempotent |
| 5 START | None | Transfer to validated image without locking |
| 6 START_AND_LOCK | None | Atomically lock and start validated image |
| 7 SAMPLE_PERIOD | One word: nominal period ms | Validate and queue period for next eligible maintenance boundary between conversions; allowed while image locked |
| 8 WAKE | None | Set pending bit 5; never reset/unlock/start the CPU |

These are additive v1 commands. A sample-period acceptance queues peripheral
configuration, not an image write. Read timing status bit 3 and applied period to
observe completion. If CPU and host change the period on the same service edge,
the host command wins; multiple accepted changes before application coalesce to
the latest. The programming lock protects the image, not peripheral configuration.

BEGIN requires a nonzero four-byte-aligned length within capacity and an aligned
entry offset strictly below length. ABI must be `0x00010000`. Resource needs must
fit the built capacities. Image ID is descriptive and may differ from the board
profile ID; it is not an application whitelist. Header fields are immutable for
the upload. CRC-32/ISO-HDLC covers image bytes in increasing address order:
reflected polynomial `0xedb88320`, initial/xor-out `0xffffffff` (compatible with
Python `zlib.crc32`). CRC provides transfer integrity, not authenticity. Duplicate,
skipped and out-of-range WRITE offsets reject without advancing the image.

An I2C read returns a **36-byte coherent snapshot** captured when the read address
is accepted: eight consecutive 32-bit words, then a 32-bit supported-word bitmap
(bits 0..7). Unsupported words return `0xffffffff` with their bitmap bit clear;
they never wrap/alias into another resource. The master may read a shorter prefix
and must NACK its last byte. SELECT followed by repeated START is supported.
Do not use SMBus's one-byte command/block-length framing for this protocol.
The selected bank is captured once; one shared word selector feeds a 32-bit
serializer at word boundaries. Snapshot consistency spans the entire read.
Application storage exists only for declared firmware-owned words; Groundlark's
six hardware-owned words allocate no duplicate software register bank.

Service/word order comes from [HostSchema](../shared/src/main/scala/riscay/HostSchema.scala):

- Device 0, instance 0: ABI, build profile ID/version, actual memory/GPIO/channel
  capacities, reset reason (1 external reset/POR, 2 watchdog since external reset),
  then `CRASH_COUNT` at word 8. Read `(0,0,8)` to retrieve the new word with
  supported bitmap bit 0 set. This is an additive supported-word extension;
  existing v1.0 image compatibility and words 0..7 remain unchanged.
- Loader 1, instance 0: MODE, PROGRAMMED, PROGRAM_LOCKED, CAN_PROGRAM, BUSY,
  LAST_ERROR, IMAGE_ID, RECEIVED_BYTES. MODE is BOOT=0, LOADING=1, READY=2,
  RUNNING=3, FAULT=4. BUSY is one during an accepted loader SRAM write.
  RECEIVED_BYTES/CRC advance only at completion. Further mutating commands,
  including VERIFY, LOCK and START, reject with busy error 3 while the program
  memory is occupied; status reads, WAKE and SAMPLE_PERIOD remain available.
  LOADING describes an incomplete upload, not a queued operation.
- Measurements 2, instance channel: VALUE, FLAGS, AGE_MS, SEQUENCE, UNIT, SCALE10.
- Timing 3, instance 0: FEATURES, NOW_MS, SAMPLE_PERIOD_MS, WAKE_MASK,
  SLEEP_REMAINING_MS, PENDING, SLEEP_ENTRIES, TIMING_STATUS. FEATURES bit 0 indicates
  reference-derived time, bit 1 retained gating, bit 2 programmable ADC cadence,
  bit 3 service-source stopping (host wake preamble required).
  TIMING_STATUS bits 0..3 are low-power hardware present, clock gate closed,
  nonzero lease, and period update pending. Reading over I2C opens the gate, so
  the entry counter is the useful indication of previous sleep activity.
- Timing 3, instance 1: TICK_US, MIN_TICK_US, MAX_TICK_US, MIN_SAMPLE_MS,
  MAX_SAMPLE_MS, STALE_MS, HOST_WAKE_WAIT_US, WATCHDOG_TICKS. Source bounds are
  elaboration assumptions, not measured live frequencies. NOW_MS and leases use
  nominal time; measurement age uses the upper elapsed-time bound. Board minimum
  durations use the lower bound. Fractional milliseconds carry between updates.
- Application 128, instance 0: profile-defined read-only words.

Loader errors: 0 success, 1 malformed frame/opcode, 2 locked, 3 already started or application reset active,
4 range/offset, 5 incompatible ABI/resources, 6 wrong state, 7 incomplete image,
8 CRC mismatch. Rejected commands preserve protected memory/metadata. A rejected
BEGIN preserves the previous image; an accepted BEGIN invalidates it immediately.
Only LOADING can accept writes; READY requires a new BEGIN before replacement.
After START, a trap halts execution until application watchdog recovery or full
reset. Watchdog recovery returns RUNNING/FAULT to READY while preserving image
validity, bytes, metadata and lock. START/START_AND_LOCK explicitly restarts that
image; a locked image still rejects replacement. No automatic crash loop occurs.
The host may LOCK a running valid image. A bus recovery, host reboot or Pi rail
cycle never clears the lock. Full MCU reset clears both lock and image validity.
Working RAM and permitted peripheral writes remain available when locked.

An interrupted upload may remain LOADING indefinitely; fixed supervision keeps
running. The host can restart with BEGIN while unlocked. No host-boot detector,
upload-driven power cycling or heartbeat policy is implied.

## Measurements, ADC and timebase

Measurement FLAGS: bit 0 currently valid and fresh, bit 1 stale, bit 2 no
successful sample yet, bit 3 last acquisition failed, bit 4 calibration applied
to the current successful reading. AGE_MS saturates; before any success it reads
`0xffffffff`. Each result increments SEQUENCE, including failure. Failure retains
the old numeric value/age, clears valid/calibrated, and sets fault. Reads neither
refresh age nor acknowledge anything. The entire 36-byte read is one snapshot.

The Groundlark reference emitter includes a receive-only, 16-clock mode-0 SPI ADC
controller with ADC121S021 framing (four leading bits, 12-bit sample). It discards
the first conversion after reset and uses independent CS, SCLK and MISO signals.
Default SCLK is 1 MHz. Low-power builds immediately retry the discarded first
conversion, then schedule nominally 1000 ms start-to-start, independent of
conversion duration. Applying an accepted update starts a fresh conversion and
rebases the schedule; repeated updates cannot postpone sensing indefinitely.
Legal periods include conversion, coarse-tick and oscillator-error margins;
query timing instance 1 for the built limits. Periods round up to LF ticks.
The production freshness budget is 3000 ms with a conservative phase margin;
0 cannot disable sensing. The legacy 4 kHz fixture retains its 3..98 ms range.
Legacy builds retain the elaboration-time idle delay between conversions.
The nominal conversion is `raw * 25300 / 4095` mV, based on a 3.3 V
ADC reference/supply and the existing 23/3 divider ratio. Build parameters permit
gain/offset calibration; the default explicitly reports **uncalibrated**.
Scaling uses three native handshake stages of four radix-2 quotient/remainder
steps after a native input-capture stage. Each design owns its datapath. Explicit
POR-only clocked bridges transfer conversion commands, waveform tokens, complete
32-observation captures and scaled replies. Independent native loops own the
immutable mode-0 waveform definition, one conversion credit, extraction of the
twelve significant rising-edge bits, priming, scaling, offset and retirement.
The clocked player copies the recipe once and advances one slot per configured
half-period without waiting for native feedback. Busy extends from admission
through waveform, buffered capture, native computation, publication and return
drainage. The first complete conversion after POR is discarded; watchdog reset
preserves priming, the in-progress frame, any buffered reply and its age.
Upper-bound elapsed age starts at admission, saturates and includes a coincident
publication tick. Telemetry and supervisor histories retain it rather than
resetting it on a delayed publication. Signed offset/calibration is unchanged.
The unstalled digital start-through-drain allowance is 32 SPI half-periods,
32 additional service edges and 2 us of native processing. The focused maximum-delay
campaign checks 6.8 us at a 20 MHz service clock with two-cycle half-periods.
Cadence bounds
round the full SPI-plus-scaling allowance upward to milliseconds. This allowance
needs physical qualification. There is no combinational divider.
[ADC datasheet](https://www.ti.com/lit/ds/symlink/adc121s021.pdf)

This is a digital reference interface, not a selected/qualified replacement for
the TI's integrated ADC. Analog settling, reference error, divider loading,
buffering and board wiring must be qualified. SPI has no CRC/ready indication;
all-zero/all-one results are real possible codes and cannot diagnose every
disconnected/stuck ADC. Groundlark rejects out-of-range battery voltages for power
policy. Generic software producers can explicitly report acquisition failure.

The watchdog owns a separate reference clock and a held-toggle kick handshake.
An accepted key write while a heartbeat is crossing domains latches a pending
kick, dispatched after acknowledgement. Multiple busy kicks coalesce into one
pending kick. Lease-register writes, including zero, never count as kicks.
Permanent bootstrap services it while the application has not started. Afterward
firmware must write the key regularly; hardware services it during a blocked
event WAIT only while a finite sleep lease remains. WAIT completion cancels the
remaining lease. Lease expiry always wakes WAIT and stops automatic servicing;
an application that never resumes useful execution eventually resets. The
reference emitter expires after 32 raw LF ticks (nominal 4.14 s, 2.67..6.4 s
over the assumed 5..12 Hz envelope), plus kick-handshake timing effects.
Expiry asynchronously resets the CPU, both CPU bridges, pending CPU responses,
software GPIO/application words, event mask/pending/deadline and sleep lease.
Release is synchronized to the service clock. Raw `systemReset` drives reset
pins and the asynchronous fast-source wake request. Ordinary service logic uses
a separate POR-reset two-flop copy on both assertion and release, including mode
recovery, request admission and loader mutation guards. The retained clock gate
also synchronizes its complete demand before the falling-edge enable flip-flop,
covering indirect changes from application-reset registers. These crossings need
physical synchronizer placement and half-cycle gate-enable timing checks.
The permanent board controller
and its GPIO override, ADC, samples/ages, LF/elapsed timebase, I2C loader, image
validity/metadata and programming lock are POR-only. The supervisor retains its
RUN/SHUTDOWN state, deadlines and timeout count through application recovery.
Host mutations are rejected during application reset; coherent reads remain
available when the service clock runs. In-progress loader state is retained.
Watchdog reason survives until external reset and is synchronized for host reads.
`CRASH_COUNT` saturates at `0xffffffff` and counts rising watchdog-reset episodes
observed by the service synchronizer. It survives host START, bus recovery and
application reset; only full reset clears it. POR itself is not a crash. It is
a recovery-episode counter, not an LF expiration counter: multiple expirations
while the service clock is absent may coalesce or go unobserved. Normal repeated
crash/restart cycles increment separately even though RESET_REASON remains 2.
A stopped service source requests
restart but the board cannot observe new inputs while that source remains failed;
its outputs are retained, not asynchronously forced off by the watchdog. Elapsed
time catches up after recovery and sample ages expose staleness. Stopping both
clocks is outside this digital watchdog's coverage.

The emitted chip wrapper adds an on-die supply monitor and qualified POR around
these portable inner-SoC reset ports. Brownout or the manual reset input asserts
reset without either clock; release requires 100,000 consecutive fast cycles
after qualification (at least 5 ms). Fast-clock enable is forced during that
hold, while LF reset remains asserted. Watchdog resets do not reset the LF
oscillator or this POR counter. See [clock/reset circuits](../analog/gf180-clock-reset/README.md)
for supply thresholds, detection latency and physical limitations.

## Groundlark permanent policy

[GroundlarkBoard](../profiles/src/main/scala/riscay/profiles/GroundlarkBoard.scala)
selects an immutable power policy. `FourPhaseSupervisor` and `ClickSupervisor`
implement it in separate native state-token loops without uploaded firmware.
The native state, dedicated bridges, acquisition history and output projection
are POR-owned; no application watchdog reset clears them. GPIO 0/1 are permanently owned outputs;
GPIO 2 remains the halt input. Firmware cannot override their ownership. Stable
inactive ACK must be observed after each power-on before a subsequent stable
active ACK is accepted. A stale active ACK blocks initial startup.

Reusing the generator with `GenericBoard` permits firmware-owned GPIO and
application words. Reusing a fabricated Groundlark-specific build preserves its
immutable power policy and pin ownership; uploading a new image does not turn
those three pins into unrestricted GPIO.

States: OFF=0, RUN=1, SHUTDOWN=2, LATCHED=3. Qualified recovery permits startup;
low voltage requires confirmation. Invalid/stale/out-of-range sensing requests
shutdown immediately while running. Power stays on until qualified ACK or a
bounded timeout. Minimum-off timing applies before restart. Three unacknowledged
shutdown timeouts latch off until reset. Power-enable telemetry reports a command,
not measured 5 V or host readiness.

Fault codes: 0 none, 1 policy disabled, 2 confirmed low voltage, 3 invalid sensing,
4 forced timeout, 5 acknowledged halt. Timeout count is reset-scoped. Policy is
validated at elaboration against Groundlark's numeric bounds. **Default emission
uses a disabled policy and never powers the Pi.** Supply qualified values and
enable the policy deliberately for any tapeout build; the reference emitters
are not a deployment configuration. Tests use explicit enabled fixtures, with
accelerated milliseconds; these values are not a battery recommendation.

## Remaining qualification

Digital implementation and event simulation do not establish physical timing,
metastability, power/area, real Linux poweroff pulse compatibility or analog safety.
Both SoCs retain native CPU protocols and explicit boundary bridges. There are
no four-phase blocks inside Click's core or its toggle bridges. Strict export
checks, directed SoC tests and randomized core/routing tests have distinct scopes;
see [build and test](build-and-test.md). A compiler-built application corpus,
Chiselator runs and board/physical qualification are subsequent work.
