# Working-RAM native return contract

Status: item 10b2d1 is digitally verified, with fresh independent review and
production integration/strict-export qualification. Evidence is recorded under
`build/async-ram-return-migration/`. No physical timing or minimum synchronous
state claim follows from those checks. Program/loader return remains item 10b2d2.

## Ownership and drainage

Each design owns its RamAccess, RamCaptureReceipt and RamReturn implementation.
Schemas are shared; controller logic is separate. Click uses native toggle phases
throughout. Working RAM no longer passes its 32-bit result through a clocked
reply bridge or Services. Its source publication is a direct native connection.
Completion has an immutable plan and separate program and RAM inputs; at most
one memory input is selected. Telemetry and Housekeeping effects may join either.

RamReturn captures the whole word in POR-owned event storage and acknowledges
SRAM independently of publication. Three branches then return independently:
source publication, a temporary clocked capture receipt, and application
presentation. Publication carries retained data bit zero, not a fabricated token.
The capture receipt is control-only. Its ACK means the clocked access owner
cleared active on that edge; it never waits for owner idle, debt or publication.
It retains two request synchronizers, one ACK/phase bit and two POR release bits.

`effectsDrained` joins inactive access, original command/word/byte crossing return
and capture-receipt return. `RamSource.wordDrained` joins that with retained
presentation settlement. It excludes return-owner occupancy and publication
itself: adding either would create a wait cycle. Full admission/sleep busy also
includes synchronized native return-owner idle. Reservation occupancy does not
block its own commit. Temporary access active, return synchronizers, reset debt
and previous-safe state remain explicit and tracked for later removal.

The Groundlark low-power reference SoC comparison against commit `666af18`
removes a 39-bit RAM reply
crossing and an eight-bit publication crossing per variant. It adds the five-bit
capture receipt, two return-idle synchronizers and one completion-plan bit:
net **39 fewer clocked RTL bits** per variant. Nonprimitive state changes from
8,724 to 8,685 bits for BD and 8,725 to 8,686 for Click; each includes one unchanged
SDA-edge capture bit, separately classified from periodic-clock state. Async
primitive state and fixed SRAM arrays are excluded. This inventory is neither
a physical area estimate, whole-chip/configuration-complete audit, nor proof
of minimal synchronous state. All 34 public
ports are unchanged.

## Application reset boundary

POR owns the payload, SRAM effects, publication/capture transport and receive,
issue and completion history. Qualified application reset revokes captured
presentation permission immediately. It resets application request/ACK history
and, in Click, the saved application target. A word armed while reset is held
cannot become eligible merely because reset is released. Permission is sampled
once; late live-eligibility changes neither revive nor revoke that captured word.

The raw response bundle deliberately spans lifetimes. It is not described as an
ordinary single-reset library channel. The supplemental `riscay-reset-boundary-v1`
record closes its native protocol, exact reset pins, complete primitive ownership,
actual data/capture pins and literal error=false leaf against emitted RTL.
All dynamic payload bits retain mapping activity checks. The only new impossible
polarity masks are the proven error leaf and its exact Completion aliases.

The receiver must share the qualified application reset. Reset assertion may
cancel presentation; payload remains stable through remaining POR branches.
Application-reset D buffers are POR-owned so reset release cannot manufacture a
late data transition at an event register. The platform's continuous 350 ns
minimum qualified hold and 250 ns output-settlement bound remain unchanged.

## Native handshake and digital timing obligations

BD retains input withdrawal before dropping input ACK. A producer may offer the
next REQ immediately after ACK falls without erasing the old return proof.
Each branch remembers actual acceptance and full request/ACK return. ACK history
outlives offer shutdown using a 200 ns guarded history interval. The next word
cannot overwrite retained payload while any old branch is returning.

Click maintains separate POR received, issued and completed phases. Every
captured word receives an unconditional issue event. Actual issue history and
the modeled phase comparator qualify terminal proof; transient old phase equality
cannot mean cancellation. Eligible presentation toggles an independent application
phase; cancellation leaves it unchanged. There is no return-to-zero adapter.

Component experiments use fixed 10 ns data paths, 1–10 ns control delays,
100 ps setup/hold/pulse/distribution limits, and 200 ns cleanup guards. Directed
opposing delays and actual capture-pin skew supplement randomized seeds. Offers
must appear within 800 ns after accepted input when receivers are stalled; after
all external returns, cleanup must finish within 1 microsecond. These are
conservative digital test bounds, not mapped cell timing. The four-source Click
Completion guard is 240.200001 ns; its expanded payload mux and complete feedback
cone still require physical qualification.

## Required qualification

Run AsyncRamReturnSpec, AsyncCompletionSpec, RamSourceSpec and SramSpec. Preserve
independent count, payload, ordering and retention oracles. Exercise full BD RTZ,
Click parity divergence, every capture/reset stage, repeated reset, late eligibility,
real capture-receipt stalls across reset release, stopped work-clock recovery,
and exact macro effects. Keep POR and application handshake monitors separate.

Run closed contract/reset and actual RTL functional controls, actual-pin capture
campaigns across every frozen seed/skew fixture, strict native and full SoC exports,
ABI comparison, core/reference and firmware/sleep regressions. Missing activity,
compile failure and a global timeout do not count as a successful negative control.
An isolated redundant-proof mutation may survive functionally; reject invalid
structure independently and label coordinated bypass controls accurately.

Production wiring controls must start from completed strict exports. The
executed-probe attestation binds the exact compiled probe, source inventory,
executable, simulation log, mapping count and semantic contract. Reject stale
or edited positive evidence. Every wiring fault must compile and fail its own
unchanged probe assertion at the recorded Icarus source line and scope;
unrelated or mixed failures, display-only diagnostics and timeouts are failures
of the control campaign, never successful mutation detection.

The final item evidence must inventory removed and temporary clocked bits,
include fresh independent review and preserve actual failed/interrupted attempts.
Earlier physical runs apply to older RTL and do not qualify this migration.
