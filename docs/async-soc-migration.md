# Asynchronous SoC migration checklist

This checklist is the migration boundary, not a claim that all peripheral RTL is
asynchronous. Complete and verify one item, obtain a fresh independent agent
review, implement fixes, rerun affected checks, document, commit and push. Repeat
this review loop for each item. Continue only to an authorized next item; ask
when no next item has been chosen. Both implementations remain active throughout.

## Ownership and invariants

- Four-phase bundled-data implementation: `designs/four-phase-bd/src/main/scala/riscay/bd/`.
- Native two-phase Click implementation: `designs/two-phase-click/src/main/scala/riscay/click/`.
- Each owns its Fabric, Control, Telemetry, Supervisor, Services, Platform, ClockedPeripherals, ConstantScaling,
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
- [ ] **6. SRAM access sequencing.** Native request ownership/arbitration around the
  fixed synchronous GF180 macros; qualify any local clock generation explicitly.
  Preserve byte effects, accepted-store completion and uninitialized retention.
- [ ] **7. I2C.** Native controller implementation with the existing wire protocol,
  address-only wake probe, startup wait and stuck/foreign-bus release behavior.
- [ ] **8. SPI ADC.** Preserve conversion timing, invalid-first sample, cadence,
  reconfiguration boundaries, freshness and supervision independent of CPU progress.
- [ ] **9. Slow-domain housekeeping.** Native coordination where appropriate while
  retaining the independent LF reference/watchdog, Gray CDC and safe source gating.
- [ ] **10. Physical requalification.** New-controller timing contracts, mapped
  decode/data paths, pulse/fork/return timing, reset and CDC bounds, then new P&R
  and extracted validation. Digital passes alone cannot check this item.

Items 1–5 are digitally verified. Ask before SRAM access sequencing.
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
SRAM sequencing, I2C, SPI ADC, slow-domain housekeeping and physical qualification
remain unchecked.

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
and power decisions do not wait for native telemetry backpressure. GPIO synchronizers, NOW/deadline/mask/lease/watchdog timing, ADC
sequencing, I2C snapshots and peripheral ingress remain explicitly clocked under
their later items. This migration does not qualify new physical timing: native
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

Consumed time advances only on service publication, with NOW/age/lease effects.
New targets queue behind outstanding work. Busy covers arithmetic and bridge
return drainage, including updates that produce zero whole milliseconds. A
one-tick arithmetic result grants observation credit only if its target still
matches the synchronized live count. This prevents stale supervisor confirmation
after delayed publication. SPI framing, first-conversion discard, cadence and
signed offset/calibration projection remain clocked, as do timer consumers and
the independent LF timebase/watchdog. Their later checklist items are unchanged.

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
bank. ADC acquisition, elapsed request/publication boundaries, LF/watchdog and
board NOW remain clocked under their later items. Application reset neither aborts accepted
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
