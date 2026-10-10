# Asynchronous SoC migration checklist

This checklist is the migration boundary, not a claim that all peripheral RTL is
asynchronous. Complete and verify one item, obtain a fresh independent agent
review, implement fixes, rerun affected checks, document, commit and push. Repeat
this review loop for each item. Continue only to an authorized next item; ask
when no next item has been chosen. Both implementations remain active throughout.

## Ownership and invariants

- Four-phase bundled-data implementation: `designs/four-phase-bd/src/main/scala/riscay/bd/`.
- Native two-phase Click implementation: `designs/two-phase-click/src/main/scala/riscay/click/`.
- Each owns its Fabric, Control, Telemetry, Supervisor, Housekeeping, SRAM sequencing, I2C and SPI ADC protocol,
  Services, Platform, ClockedPeripherals, ConstantScaling,
  I2cTarget, SleepTiming and SramBank code. Copying the former service island into
  these directories establishes ownership; it does not migrate its state machines.
- Share port schemas, parameter/ISA definitions, fixed macro models and verification
  utilities. Keep protocol controllers separate; Click must not use hidden RTZ adapters.
- Preserve the host/firmware ABI, programming lock, validated image, accepted SRAM
  effects and retention, retained sleep, application-reset isolation, and permanent
  Groundlark power supervision. Keep an independent timebase/watchdog even as
  service-clock work is removed. Never relax tests to accept implementation bugs.

## Items

- [x] **1. SocFabric routing - digitally verified, 2026-10-08.** Native request/response routing,
  clockless ROM/static faults, endpoint backpressure/return sequencing, coordinated
  reset and retained payloads. Keep stateful MMIO/SRAM behind explicit endpoint
  bridges. Expand focused and independent-service tests for both implementations;
  rerun affected SoC/sleep/firmware/SRAM, core/reference and Python controls and
  strict exports. Update contracts and evidence, then commit and push.
- [x] **2. MMIO and loader state - digitally verified, 2026-10-08.**
  Move state/serialization and validated-image
  accounting into each protocol; preserve full-width validation, atomic acceptance,
  upload arbitration, reset isolation and the POR-only programming lock.
  Implementation and fresh independent review fixes pass the final 107-case
  verification run, two core physical-policy tests, Python controls and both
  strict exports. See the exact scope below and the linked evidence.
- [x] **3. GPIO, events and telemetry - digitally verified, 2026-10-08.** Separate
  native state loops preserve board ownership, coherent snapshots, set-wins events,
  deadline replacement, retained samples and WAIT/lease behavior. Fresh independent
  review fixes, 121 verification cases, two core physical-policy cases, 69 Python
  controls and both strict exports pass. Exact clocked boundaries remain below.
- [x] **4. Scaling and CRC — digitally verified, 2026-10-09.** Independent native
  elapsed/sample pipelines and CRC feedback stages preserve fractional time,
  wrap/catch-up and image integrity. Fresh independent review fixes, all 145
  verification cases, two core physical-policy cases, 70 working-tree Python
  controls and both strict exports pass. Exact boundaries and evidence are below.
- [x] **5. Permanent supervisor — digitally verified, 2026-10-09.** Separate native
  state and safety-sample loops preserve firmware-independent Pi bootstrap and
  watchdog isolation, with disabled-by-default production policy. Fresh review
  fixes, 161 verification cases, two core policy cases, 71 working-tree Python
  controls and both strict exports pass. Scope and timing limits are below.
- [x] **6. SRAM access sequencing — digitally verified, 2026-10-09.** Separate
  native word ownership, byte sequencing and read assembly surround explicit
  synchronous GF180 macro crossings. No local clock generator is introduced.
  Fresh independent review, all 169 verification cases, two core policy cases,
  74 working-tree Python controls and both strict SoC exports pass. Scope,
  retained failure evidence and physical limits are documented below.
- [x] **7. I2C - digitally verified, 2026-10-09.** Separate native protocol
  loops preserve wire behavior, coherent reads, reset isolation, address-only wake
  and stuck/foreign-bus release. Fresh review fixes, 190 verification outcomes,
  two core policy cases, 80 Python controls, thirteen actual wiring mutation
  controls and both strict SoC exports pass. Scope and physical limits are below.
- [x] **8. SPI ADC - digitally verified, 2026-10-10.** Separate native conversion,
  assembly, priming and scaling loops preserve exact wire timing, cadence,
  reconfiguration, freshness and supervision independent of CPU progress. Fresh
  review fixes, 206 verification cases, two core policy cases, 83 Python controls,
  22 actual RTL mutation controls and both strict SoC exports pass. Clocked wire
  playback and full-frame capture remain explicit boundaries below; item 9 owns cadence.
- [x] **9. Slow-domain housekeeping - digitally verified, 2026-10-10.** Separate
  native time/deadline/lease/wake-mask, kick policy and low-power cadence loops retain
  independent LF/watchdog, observation/freshness ingress, Gray CDC and safe gating.
  Fresh review fixes, all 227 verification cases across 28 suites, both core policy
  cases, 84 Python controls and both strict exports pass. Exact boundaries are below.
- [ ] **10. Physical requalification.** New-controller timing contracts, mapped
  decode/data paths, pulse/fork/return timing, reset and CDC bounds, then new P&R
  and extracted validation. Digital passes alone cannot check this item.

Items 1-9 are digitally verified. Ask before item 10, physical requalification.
Each item requires both implementations, invariant-focused
tests and a fresh independent review before it can be checked off.

## SocFabric handshake and timing contract

ROM read/fetch and statically invalid addresses/permissions/widths terminate in
the native fabric without a service clock. Valid program reads/fetches, working
RAM accesses, full-word MMIO and HALT route to the clocked endpoint. Dynamic image
length/validity, writable MMIO permissions, WAIT, loader arbitration and SRAM
side effects remain endpoint responsibilities. HALT commits once and parks
without a response until coordinated reset, as in the existing core contract.

Four-phase holds the source payload through request acknowledgement return.
The reply uses long-hold storage. Endpoint response acknowledgement must stay
asserted until its request falls; source acknowledgement return waits for the
reply input and both endpoint channels to drain. A stalled downstream response
retains its payload independently of the next source request.

Click keeps separate source/reply, endpoint-request and endpoint-response phases.
Local transactions do not toggle endpoint phases. Dispatch fires once per pending
endpoint transaction; reply capture waits for endpoint acceptance and a fresh
response phase. Source and output guards must cover the actual composed control
network, including the three-cell De Morgan ANDs. Standard single-AND ClickStage
bounds alone do not cover that network. The release guard is at least
`inputPhase.max + 7*fire.max + skew + max(pulseLow, hold) + 1 fs` (80.200001 ns
for the 1..10 ns simulation envelope), as well as the supplied standard guard.
The seven cells are one comparator and two serial AND networks. The bound is
checked at source acknowledgement. Endpoint response parity samples its request
on the common capture pulse; local transactions keep that phase unchanged.
There is no separately gated capture pulse that can be filtered by unequal delays.
ClickFabric currently accepts only `ClickTiming.Simulation`: custom stage timing
policies are rejected until their composed-controller bounds can be exported and
exercised. Its strict adapter independently checks the fixed 1..10 ns envelope,
nominal cells, request/data guards, strict return-guard minima and guard pin
connections. Required mux and capture-aperture obligations cannot be omitted.
Focused tests monitor setup/hold and high/low pulse widths at all capture registers.
Source payload reuse must follow capture
pulse drainage. Exported data-path budgets include
the complete ROM/decode/response mux, not an extra physical data buffer.

Both endpoint bridges synchronize control and allow payload settling. Reset all
connected CPU/fabric/bridge phases together on application reset; permanent
service state stays POR-only except its explicitly application-owned registers.
Independent LF/watchdog logic remains live when the service source stops.

These controllers are digital models with ideal combinational glue/forks.
New decode, return paths, endpoint crossings, local pulse widths/distribution,
setup/hold and reset recovery need physical characterization. Historical P&R
under `build/pnr-first/bd-v5` and `click-v2` is for baseline `8637099`, has open
violations, and does not qualify this migration.

## Evidence

The inherited `build/async-fabric-migration/regression.log` records 48 tests,
41 passes and seven four-phase failures. Preserve it and the original lock error
in `native-first.log`. The first focused run (`focused-initial.log`) failed to
bind endpoint port names; `focused-ports-fixed.log` then exposed handshake errors.
`focused-return-ack.log` retains the Click maximum-cell-delay failure after the
first BD return fix. Later strict path/scope and unsized-alias elaboration failures
are also retained rather than overwritten.

SocFabric baseline results: 89 distinct verification cases and two core
physical-policy cases pass; 64 working-tree Python controls pass (six belong to the preserved earlier
P&R work), and all 11 SRAM assets verify. Both production-capacity SoCs pass strict
`--soc --vector-coverage --sleep-clock` exports with three macros each and native
Click throughout. Exact logs, hashes, counts and qualification limits are in
[build and test](build-and-test.md#asynchronous-socfabric-migration).

The final MMIO/loader run passes all 107 verification cases across fourteen suites
and two core physical-policy cases, with no skipped/canceled/pending tests.
All 68 working-tree Python controls pass (six belong to the preserved P&R work),
and all 11 SRAM assets verify. Both production exports pass strict validation
with unchanged 34-port public ABIs and three SRAM macros each. See
[MMIO/loader evidence](build-and-test.md#asynchronous-mmio-and-loader-migration)
for logs, hashes, independent review fixes and retained failures.

SocFabric and the scoped MMIO/loader and GPIO/events/telemetry items are digitally
complete. Item 3 passes 121 verification cases across sixteen suites, two core
physical-policy cases, 69 working-tree Python controls and both strict exports.
The 28 affected focused cases pass again after preserving the registered export
boundary. See [item 3 evidence](build-and-test.md#asynchronous-gpio-events-and-telemetry-migration).
Item 4 passes all 145 verification cases across nineteen suites, two core
physical-policy cases, 70 working-tree Python controls and both strict exports.
See [scaling/CRC evidence](build-and-test.md#asynchronous-scaling-and-crc-migration).
Item 5 passes 161 verification cases across 21 suites, two core policy cases,
71 working-tree Python controls and both strict exports. Its strengthened six-case
boundary rerun also passes. See [supervisor evidence](build-and-test.md#asynchronous-permanent-supervisor-migration).
Item 6 passes 169 final verification outcomes, two core policy cases, 74 working-tree
Python controls and both strict exports after independent review. See
[SRAM evidence](build-and-test.md#asynchronous-sram-access-sequencing-migration).
Item 7 passes 190 verification outcomes, two core policy cases, 80 working-tree
Python controls, thirteen actual wiring mutations and both strict exports after
independent review. See [I2C evidence](build-and-test.md#native-i2c-migration---digitally-verified-2026-10-09).
Item 8 passes 206 verification cases, two core policy cases, 83 working-tree
Python controls, 22 actual RTL mutations and both strict exports after independent
review. See [SPI ADC evidence](build-and-test.md#native-spi-adc-migration---digitally-verified-2026-10-10).
Item 9 passes 227 verification cases, two core policy cases, 84 Python controls
and both strict exports after independent review. See
[Housekeeping evidence](build-and-test.md#native-slow-domain-housekeeping---digitally-verified-2026-10-10).
Physical qualification remains unchecked.

## GPIO/events/telemetry scope and contract

`FourPhaseTelemetry` and `ClickTelemetry` own separate native seeded state-token
loops for software GPIO output/enable, firmware-owned application words, pending
events and host measurement records. Empty channel/application sets omit those
payload fields; Groundlark does not allocate a duplicate software application bank.
The native loops and their command/reply bridges reset only on POR. Click uses
native Click storage, join, transform, fork and endpoint bridges throughout.

Clocked ingress captures GPIO edges, timer/lease/deadline/host events and acquisition
publications. Event sets coalesce. Accepted clears mask only eligible old bits;
events observed during MMIO validation or on the acceptance edge win. Deadline
replacement removes the old expiry from both queued ingress and native pending
state. A newly armed expiry enters a later batch and survives that replacement.
Captured and dispatched event sets remain visible to host snapshots until native
commit, without a temporary disappearing flag. CPU effects serialize against
outstanding telemetry; background observations cannot starve CPU validation.

Acquisition ingress is POR-owned and compacts an arbitrary stalled batch into
an attempt count (modulo the ABI's 32-bit sequence), latest validity/calibration,
last successful value and its elapsed age. Upper elapsed time saturates rather
than wrapping. Software publication enters this retained ingress on CPU acceptance,
even if application reset cancels its outstanding CPU completion. Native sample
records survive application reset. Host snapshots conservatively include queued
and dispatched elapsed time and suppress fresh-valid for a channel with an
uncommitted publication. The existing 36-byte I2C snapshot remains coherent.

Application GPIO, application-word and event projections have immediate raw
application-reset pins. Retained recovery commands clear their native state;
stale replies cannot restore pre-reset values. Accepted CPU effects wait for
native completion before replying. Buffered work and recovery inhibit sleep.

Item 5 replaces the permanent supervisor's clocked safety sample view with a
separate native record. Safety and host records consume the same acquisition
publication stream through independent retained ingress; supervisor freshness
and power decisions do not wait for native telemetry backpressure. Later items
move SPI conversion state and low-power time/deadline/mask/lease/cadence policy
into their own native loops. GPIO synchronizers, LF/watchdog, I2C snapshots,
SPI wire timing and peripheral ingress remain explicit clocked boundaries. This migration does not qualify new physical timing: native
transform data paths, compacted ingress crossings, reset recovery, forks and
capture pulses still require item 10 characterization.

## MMIO/loader scope and contract

`FourPhaseControl` and `ClickControl` own separate state-token feedback loops,
using each native protocol's seeded storage, join, transform and fork. They own
image length/entry/ID, received bytes/CRC, validity, programming lock, loader
mode/error/start state, host selector, producer index/value and application word
selector. Native MMIO preparation validates full-width accesses and permissions.
Its retained staging changes only on a separate commit command created at the
existing service-clock request acceptance. Abandoned preparation has no effect;
an accepted producer-staging commit survives watchdog reset and precedes recovery.

At item 2 completion the service domain retained bounded host ingress and its
busy/reset context, command arbitration, CPU acceptance, coherent snapshots,
MODE/start reset projection, GPIO/event/timer/peripheral effects, I2C and SRAM
byte sequencing. Item 3's separate scope above moves GPIO/event/sample state
behind another native loop. MMIO accesses still cross clocked endpoints. Two explicit,
POR-only native/clocked bridges connect each Control loop. The Click loop and
bridges contain no four-phase adapter. Item 4 replaces the shared combinational
CRC word function with separate four-byte native pipelines inside each Control
feedback loop, with separate candidate and architectural accounting state.

One outstanding command preserves order. SRAM completion, accepted MMIO commit,
reset recovery, HALT and host/CPU commands have explicit arbitration. Host frames
remember reset and loader-busy conditions, including same-edge loader admission;
a busy command is rejected instead of executing later. A retained reset request
cannot disappear behind a stalled reply. Queued HALT and unaccepted MMIO are
application-reset-owned; stale START replies and pre-reset queued START frames
cannot restart an application. MODE retains its third-service-edge synchronized
reset behavior through a clocked status projection. Any pending command/reply,
commit or accounting token inhibits retained work-clock shutdown.
Reply acceptance requires that outstanding command. Period candidate bits are
separate from their validated update flag, which alone permits a peripheral effect.

Independent review found and prompted fixes for lost reset pulses, stale HALT,
pre-commit staging mutation, and busy-context loss (including simultaneous host
arrival/admission). `ControlResetSpec` targets these with independently stalled
command/reply bridges; its boundary test verifies that the simultaneous event
actually occurred. The original clear/event race and strict MODE reset assertions
remain unchanged. Full-width loader/CRC/lock, native backpressure and POR abort
also have independent clockless `AsyncControlSpec` oracles for both protocols.

These are digital controllers. The complete command/decode/CRC transforms use
declared simulation budgets; newly mapped paths, state feedback forks, pulse
distribution, CDC/reset and physical implementation require item 10 qualification.

### Fresh SocFabric review

An independent agent reviewed `7f07f01` and found two export-validation gaps:
positive-but-undersized Click guards were accepted, and removing a fabric's mux
timing obligation and marker bypassed its custom checks. Both now fail closed,
with independent negative controls, actual guard/capture pin comparisons and
capture-aperture observations. The reviewer found no default-policy handshake
counterexample. See the review evidence in [build and test](build-and-test.md).

## Scaling/CRC scope and contract

Each design owns its native elapsed and sample datapaths and clocked boundary
wrappers in `ConstantScaling.scala`. Four elapsed stages consume eight radix-2
bits apiece; three sample stages consume four bits apiece after input capture.
Elapsed fraction and target state remain in a seeded native feedback loop.
Interfaces and payload schemas alone are shared. Click stays native throughout.
The explicit wrappers capture requests and publish replies; no service clock
advances the arithmetic. All stages, fractions and both crossings are POR-only.

The scaler publishes ordered elapsed observations to independent aging/history
ingress and native Housekeeping. Final Housekeeping publication advances
consumedGray with NOW/lease effects. New targets queue behind outstanding work. Busy covers arithmetic and bridge
return drainage, including updates that produce zero whole milliseconds. A
one-tick arithmetic result grants observation credit only if its target still
matches the synchronized live count. This prevents stale supervisor confirmation
after delayed publication. Item 8 moves SPI framing, first-conversion discard and
signed offset into native conversion loops; item 9 moves low-power cadence and
timer consumers into native Housekeeping. Independent LF/watchdog, pin timing,
legacy idle delay and ingress/publication remain clocked boundaries.

Four native CRC byte stages precompute a candidate in each Control feedback
branch. The internal token pairs architectural state with pendingCrc; the public
reply ABI is unchanged. Host/MMIO replies retain their original path, while the
next command waits for all four byte stages. Only Stored with an accepted pending
loader word commits the completed candidate to architectural CRC, received bytes
and loaderPending together. Intermediate candidates cannot appear in public
state. Duplicate/early completions with no pending word are inert. Watchdog
recovery queues behind accepted work; POR aborts it and reinstalls cold state.

Fresh independent review identified stale one-tick observation credit and
required the live-target guard above. Keep arithmetic, stall, reset, maximum-delay,
sleep and independent Java CRC oracles. Regression fixes fused the first/last
elapsed arithmetic steps with preparation/finalization and made maintenance
return drainage explicit. The unchanged seven-edge ordinary activity/reset guard
can now count down while tracked native maintenance holds the gate open. BD
telemetry return uses the bridge's clocked ACK falling edge, which follows its
synchronized request return; Click reply acceptance already restores bridge idle.
New commands/outstanding work bridge those handoffs without an idle gap. CRC
precomputation moved to feedback to keep byte stages out of the immediate host
reply path. The original sleep and brownout assertions remain intact.
Digital stage budgets describe entire
transforms, including the quotient/remainder and CRC logic; no mapped timing or
physical signoff is implied. Old P&R results remain inapplicable.

## Permanent supervisor scope and contract

`FourPhaseSupervisor` and `ClickSupervisor` own independent native seeded state
loops for OFF/RUN/SHUTDOWN/LATCHED, faults/timeouts, four confirmation counters,
current-boot acknowledgment qualification, dwell epochs and the safety sample
record. `GroundlarkBoard`/`PowerPolicy` are immutable descriptors in `profiles/`;
no shared clocked board controller remains. Disabled production defaults cannot
energize the Pi. Native Click storage, join, transform, fork and bridges contain
no four-phase conversion. Both complete transforms currently use digital
simulation budgets; physical data, pulse, fork, CDC and reset timing is unqualified.

Each supervisor has dedicated POR-only command/reply bridges. The service island
retains GPIO synchronization, generic acquisition/time history and coherent output
projection, but no power-policy qualification counters or shadow safety sample
bank. ADC pin timing/capture, elapsed request/publication boundaries and LF/watchdog
remain clocked. Housekeeping owns native board NOW; its service projection includes
pending lower time so supervisor progress does not depend on Housekeeping stalls. Application reset neither aborts accepted
supervisor commands nor resets native state, input history or applied GPIO outputs.
Control or Telemetry stalls cannot block this independent loop. Pending input,
outstanding work and bridge return drainage inhibit service-clock shutdown.

Ingress compacts all publication attempts, last validity/calibration, last good
value, first-publication elapsed age, largest inter-publication gap, last-good age,
voltage extrema, any failed acquisition, GPIO changes and any zero-credit time
observation. Ages saturate; publication sequence wraps at 32 bits. A publication
resets current sample age but includes its coincident upper elapsed tick in the
preceding freshness interval. Ambiguous or interrupted batches cancel confirmation
credit; a recovered last sample cannot erase invalid/stale/out-of-range history.
While RUN is active, sensing faults consumed between ticks remain latched until
the next policy evaluation, even if recovery arrives in a separate command.
This is conservative under stalls. Native sample and power decisions do not wait
for host telemetry publication. The ABI still reports the same six board words.

Power transitions wait for feedback from the applied service-domain GPIO projection
before recording minimum-off/shutdown epochs or granting current-boot inactive-ACK
credit. Stalled crossings therefore defer recording the epoch until feedback
and cannot count pre-power ACK history. Minimum-off records the published lower-time count
after power removal feedback; shutdown records it after request feedback. These
are quantized logical-time epochs, not timestamps of the GPIO edges. The tests
preserve configured dwell in that model. LF phase, fractional rounding and elapsed
publication-latency bounds still require timing qualification before asserting
absolute physical durations; that limitation predates this migration. RUN clears previous
ACK observations through the first applied-power command. Later stable inactive,
then stable active-low observations qualify halt. The fixed independent timebase
and watchdog remain necessary even though native state has no service clock.


## SRAM access sequencing scope and contract

`FourPhaseSram` and `ClickSram` retain each accepted word, generate its four
little-endian byte commands and assemble read data through independent native
fork/join/stage pipelines. A seeded execution credit joins each word request;
the final consumer's acknowledgment returns that credit. The final internal
result is acknowledged only after credit capture. The credit payload carries
that retained word's operation bit; it is stable before the response offer and
held through feedback capture. Credit availability, not this payload's value,
controls execution. This serializes byte effects
through response acceptance, including an early next request and stalled replies.
Each disabled store lane still completes a native rendezvous but never enables
a macro. Store replies are zero; reads retain uninitialized bytes as unknown.
Click uses native phase storage, fork, join and crossings without RTZ adapters.

Each bank has explicit POR-only word ingress/reply and four byte request/reply
crossings. The clocked `SramBank` now performs one synchronous byte launch,
access and capture, retaining only that byte and its response-port tag. Its
one-hot port mux is not a word scheduler: native credit and lane rendezvous
guarantee exclusive requests. Service admission still validates addresses,
permissions and loader/CPU eligibility, with loader priority for simultaneous
admissible work. RAM payload bits are offered independently of valid; invalid
cycles are don't-care and cannot authorize a bridge capture or macro effect.
These clock-domain acceptance and status boundaries remain
explicit. Native control owns loader accounting after the completed word.

Macro CLK remains the service clock. Falling-edge launch gives input setup/hold;
the access rising edge is followed by a separate rising capture edge, leaving a
full cycle for Q. CEN is inactive between accesses and in retained sleep. No local
clock generator is introduced. The four sequential crossings increase word
latency; the former eight-service-cycle completion bound no longer applies.
Busy covers the admitted word, final reply and every crossing return before
another admission or sleep. Watchdog reset discards CPU replies while native
tokens, byte accesses and loader accounting survive. POR cancels pending tokens
without clearing or replaying already-written macro bytes.

The complete native transforms and acknowledgment/credit feedback currently
have digital simulation bounds only. Macro duty cycle, input/Q paths, native
feedback/fork/capture paths and CDC/reset placement need physical qualification.
The older baseline P&R results do not qualify these controllers.


## I2C scope and timing contract

`FourPhaseI2c` and `ClickI2c` own independent native protocol state: address
selection, receive/ACK sequencing, byte storage and length/overflow validation,
STOP/repeated-START frame formation, read serialization and master-NACK release.
Their feedback loops, publication storage and frame/snapshot channels use their
respective native protocols. Click contains no four-phase adapters.

Each separate `I2cTarget` retains a clocked wire boundary: two-flop SCL/SDA
sampling, edge detection, an eight-entry captured-edge ring, and the independent
inactivity counter. Slots include sampled SDA/read-word and admission context;
occupied slots remain immutable until the native published head returns through
two Gray-pointer synchronizers. Both binary pointers have an extra wrap bit and
registered Gray representations. Full-ring overwrite is a contract violation,
with a simulation assertion. Physical pointer skew/metastability qualification
is still required. The protocol loop consumes retained observations, never live
wire levels. Inactivity is counted from the sampled wire change so native
publication latency does not extend the configured timeout.

A common native capture projects the open-drain drive and protocol state, and
stores independent frame and snapshot effects. A held effect retains its own
payload while unrelated observations advance; a second effect of the same kind
backpressures publication. BD offers remain asserted through input return and
output acknowledgment, preventing a second offer from a delayed source return.
Click captures output phase feedback on that same event as all payloads.

POR-only frame/read-start bridges publish into the service domain only after
the target's two-edge local POR release. Coherent host-bank capture, word selection,
Control mailbox arbitration, the wire sampler,
startup wake qualification, timeout clock, LF/watchdog and source gating remain
clocked boundaries. Native I2C does not replace the independent timebase.
A POR-owned 64-bit reset epoch travels with completed frames; a mismatch on
service delivery retains an intervening watchdog episode, even if it ended
before delivery. Epoch wrap is outside the supported lifetime and asserted in
simulation. Current and sampled reset/busy context are also retained. POR aborts
pending effects; watchdog reset does not reset this hierarchy.

Busy combines synchronized native activity and held effects, bridge publication,
and START/STOP activity. Arbitrary inactive ring traffic does not retain service
clock demand, preserving foreign-address release. The existing seven-edge drain
and address-only source-start probe remain in force. Read-bank capture must
finish before the first data launch after address ACK; completed SELECT frames
must publish before the following read snapshot. ACK is byte reception, not
loader command completion. Internal status projection can follow STOP later
than the old clocked target's incidental testbench delay; architectural state,
error assertions and the earliest legal on-wire status observation remain checks.

The complete projection mux (including Click phase feedback) has one fixed
10 ns digital data-path model, an 11 ns request guard, 1..10 ns storage/control
cell experiments and 110 ns source/output guards. All event/phase registers
share the capture event; setup/hold and high/low pulse checks cover each register.
These composed-controller guards, primitive inventory, actual mux/storage pins,
phase pins, internal composed-AND connections and reset ownership are strict-export
obligations. They are digital simulation assumptions, not characterized physical paths. Bus-rate qualification
must bound absolute native latency as well as the existing >=8 service cycles
per SCL period and >=4 cycles per phase; a cycle ratio alone is insufficient.
The focused wire campaign targets 400 kHz at 3.2 MHz and 20 MHz service clocks
with maximum native delays, including adjacent sampled SDA changes. Physical
SDA setup, feedback/fork timing, Gray CDC, reset recovery and output pads remain
unqualified. Older P&R artifacts do not apply.

## SPI ADC scope and contract

Item 8 passes digital verification and strict export validation after fresh
independent review. Each design has its own native conversion loop and clocked boundary
in `FourPhaseSpiAdc.scala` or `ClickSpiAdc.scala`. Shared code contains only the
wire schemas and parameter/budget definitions. Click stays native throughout.

The native controller owns a single conversion credit, an immutable mode-0 pin
recipe, the primed state, frame assembly, exact integer scaling, signed offset
and retirement. Its waveform token and retained conversion context fork together;
the capture rendezvous joins all 32 MISO observations with that context. Assembly
selects sixteen rising-edge observations and ignores the first four, leaving the
twelve-bit sample. The first complete frame after POR primes the converter but
does not publish; an incomplete frame cannot prime it. The feedback credit returns
only after the consumer accepts the reply. All four crossings and all native
state are POR-only; application watchdog reset cannot discard or replay them.

The clocked boundary admits a conversion, copies the native recipe, emits exactly
32 half-period slots and buffers every MISO observation. It never waits for a
native per-edge acknowledgement while CS is low. CS asserts with SCLK low; the
first rising edge follows one complete half-period. The sixteenth falling edge
releases CS after the final complete high phase. Clocked state contains a shift
mask, pin vectors, divider and retained observations, not ADC field extraction,
priming or scaling state. Native backpressure can delay admission or publication,
but cannot stretch a half-period. Busy includes every phase through complete
command/wave/capture/reply return. Neither another start nor retained sleep may
interrupt that lifetime.

Item 9 moves low-power cadence into separate native Housekeeping loops. Periods remain
start-to-start, accepted updates apply on an eligible between-conversion tick,
first-discard retry is immediate and repeated updates cannot starve acquisition.
Legacy mode retains its idle delay between conversions. The digital budget is
`32 * halfPeriodCycles + 32` service edges plus 2 us of native processing, rounded
up to milliseconds for cadence limits. The focused maximum-delay experiment uses
20 MHz service, two-cycle half-periods and the 1..10 ns native cell envelope; it
requires exact 100 ns phases and completion/drainage within 6.8 us. Those are
simulation obligations, not ADC electrical or physical path qualification.
That stress case produces 5 MHz SCLK, above the ADC121S021's specified 1..4 MHz
electrical-performance range; see its [datasheet, section 7.5](https://www.ti.com/lit/ds/symlink/adc121s021.pdf).
Production emitters retain 1 MHz SCLK.

Age accumulates saturated upper-bound elapsed time from admission, excluding an
elapsed interval coincident with that initial admission and including a tick
coincident with publication. Both telemetry and supervisor ingress copy the
result's age into their retained `tailAge`; a long-held conversion cannot become
fresh on release. Supervisor first-age and maximum-gap history survive an old
frame followed by a fresh frame before batch consumption. Independent LF time
and watchdog supervision remain necessary.

The strict checker asserts immutable native recipe values and native-to-recipe
wire bindings while preserving every existing dynamic endpoint activity check.
Separate actual exported-player mutation controls check register loads, pin
timing and MISO capture using the unchanged wire oracle. New 33-bit capture
storage/bridges preserve their declared ABI names against structural compiler
deduplication with 33-bit CPU responses. These preservation annotations do not
change the handshake or datapath. The public SoC ABI is unchanged.

Physical requalification must cover the composed ownership/assembly/offset paths,
native reset and return timing, all CDC/bundled-data crossings, clock gating,
SCLK/CS/MISO setup/hold and board/ADC electrical limits. The old P&R artifacts
neither qualify this controller nor establish timing closure.

## Housekeeping scope and timing contract

Separate `FourPhaseHousekeeping` and `ClickHousekeeping` state loops own nominal
NOW, lower-bound board time, consumed-target publication, application deadlines,
sleep lease and wake mask, kick authorization, and low-power ADC cadence. State
credit returns only after the publication consumer accepts the reply. Click
uses native phase storage and feedback throughout. Shared code defines schemas
and reset literals only. Digital model timing still requires physical qualification.

The service boundary accumulates immutable elapsed observations and orders them
with accepted CPU/host updates. It retains modulo nominal/lower time, a nominal
overflow indication and saturated upper age. An accepted write freezes all older
queued time; later observations cannot overtake it. Deadline replacement clears
only the old event and evaluates the new deadline against post-elapsed time.
An old deadline also expires when a large batch crosses its unsigned distance,
including complete nominal wrap; deadline offsets remain below 2^31 ms. Lease
expiry and cadence recognize nominal overflow even when the accumulated low word
is zero. No complete LF source-counter wrap can be reconstructed after an outage.

Elapsed-scaler publication feeds measurement aging, GPIO observation history and
permanent supervision independently of housekeeping stalls. The board-time view
includes retained queued, ordered and in-flight lower time. Observation credit
still comes only from a fresh single-source-tick scaler publication; delayed
housekeeping replies do not manufacture observations. Only final housekeeping
state publication advances consumedGray. Queued work, native replies and bridge
return drainage retain the work clock, with the existing seven-edge ordinary
drain guard and synchronized demand unchanged.

CPU admission gets a bounded turn between background updates even when legacy
service-derived ticks occur every service edge. Deadline writes join housekeeping
and telemetry completion before issuing one CPU response. Published period state
and dispatched/ordered updates all contribute to host period-pending status.
Cadence coalesces missed acquisitions, retries the initial discarded frame and
applies the old pending interval before recording a coincident new update.

Native housekeeping and both crossings are POR-only. Application reset immediately
resets visible application projections (lease/deadline to zero and wake mask to
15), cancels the CPU completion,
and retains reset notification until native recovery publishes. Older replies
cannot restore application state. Time, pending elapsed history and acquisition
cadence persist. The LF counter, watchdog, two-flop Gray/ACK synchronization,
clock gate, source wake, input sampling and ingress/publication registers remain
explicit clocked boundaries. Native policy emits authorized watchdog kicks;
the POR heartbeat phase and application-reset pending bit coalesce delivery at
the LF crossing. Waiting for its ACK neither creates a housekeeping transaction
nor independently holds the gate. Legacy SPI idle-delay timing remains clocked.

Physical work must qualify the complete time/deadline/cadence transforms, native
state-credit return, reset recovery/removal, all bundled-data/phase crossings,
Gray skew, independent watchdog crossing and retained clock-gate timing. Existing
P&R results do not qualify this migration and do not establish timing closure.
