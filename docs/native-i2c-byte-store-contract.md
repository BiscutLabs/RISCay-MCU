# Native I2C receive-byte ownership

This is the A5b receive-store change. BD and Click retain separate native
implementations. A single addressed 33-byte scratch bank replaces bytes carried
through the protocol state and update result. The native state narrows from
340 to 76 bits and the update result from 687 to 174 bits. Adding the 264-bit
scratch bank gives a net reduction of 513 declared native payload bits per
variant before accounting for control and mapped logic. No periodic state is
added or removed by this step.

## Capture and publication

The protocol transform produces a byte write only after receiving a complete
accepted data byte. It carries a six-bit index and eight-bit value. The publisher
validates the full index against 33 and forbids a simultaneous byte write and
frame publication before admitting the token. Illegal combinations receive no
acknowledgment. Nonselected bytes feed back from the scratch bank. All scratch
bits use the existing native publication capture event; it is not a service
clock or a per-byte clock-domain crossing.

A frame token contains metadata only. At its native capture the publisher
combines this metadata with the completed scratch bytes into the existing
337-bit retained frame payload. Frame publication and byte writes are mutually
exclusive, so copying a frame never depends on the same capture changing its
bytes. Unused tail bytes retain the prior behavior. Snapshot capture and the
15-bit observation retain their existing independent projections.

State feedback may acknowledge before publication. The fork and update owner
must keep the pending result immutable until publication accepts it. BD also
waits for both branches to return before reusing the result. Click retains
independent input, frame and snapshot phase histories. A held frame blocks
another frame publication while the native protocol may still advance through
nonconflicting work. The composed ordering test holds a first frame, stalls a
second STOP after state acceptance, queues the next START, then checks all
three frames and exactly-once byte captures after release.

The publisher's existing 110 ns modeled acknowledgment/output guards remain.
They delay acknowledgment/publication; they do not protect initial capture.
Initial capture follows the existing 11 ns modeled request path and admission.
The scratch transform has its own explicit 10 ns data allowance and 100 ps
modeled setup/hold obligation. These are digital contracts, not measured cell
or route guarantees. No delay was added to the periodic service path.

## Preserved boundaries

The byte bank, protocol state, publisher and frame-bank ownership remain
POR-owned. Watchdog reset does not reset them. O/C/A/D ordering, four physical
frame banks, two logical admission credits, modulo-four routes, reset/busy
context, retained 64-bit epochs, overflow and loader ABI remain unchanged.
The wire sampler and edge ring still use the front clock. The 32-bit sampled
read word, frame publication copy, frame banks and descriptor epochs remain
separate reductions; this step does not claim to remove them.

## Verification and measurement gates

Run AsyncI2cByteStoreSpec, AsyncI2cPublicationOrderingSpec, AsyncI2cSpec and
AsyncI2cObservationSpec, then the serial I2C, frame/admission, loader, sleep,
firmware and core-reference regressions. Use the original independent byte,
frame, context, overflow and retention oracles. Publication fixtures must preload
bytes through legal native write tokens rather than force a removed payload.

Strict wiring controls retain the generic export campaigns and all observation
lanes. Additional actual-RTL faults cover disconnected scratch data/capture,
each of 33 byte positions and the remaining seven bit positions. This is not a
claim of a 264-case Cartesian mutation sweep. Exact fatal source locations and
the executed binary are required; a structural rejection is separate evidence.

The full native-owner maps include state, update, fork and publication. A
publication-only map is insufficient because the scratch bank moves into that
module. Compare common feedback capture with selective byte capture using the
same pinned tools, corners and preserved cell graphs. Measure whole-SoC cost,
periodic state and matched wake activity separately before acceptance.

Physical analysis must include input-to-scratch D, scratch Q-to-scratch D,
scratch Q-to-frame D, held frame/snapshot feedback, capture distribution and
earliest source release. Module-input-only stage analysis omits the two new
internal scratch paths. Preserve measured setup/hold, pulse, slew/load, reset
and bundling failures; pre-layout measurements do not close routed timing or
establish reachable deep-sleep power.

## Implementation and verification evidence

The r4 focused cohort passes 19 tests and the actual wiring controls pass.
The matched complete-owner maps are 0.1731859136 mm² BD and 0.1774467968 mm²
Click, approximately 24% below their respective original I2C owners. These
are block results, not whole-chip savings. The common feedback bank is smaller
and has lower TT listed-state leakage than the selective candidate. The
selective Click candidate has a slightly lower FF125 maximum, so common does
not dominate every corner bound. No switching-energy result has been measured.

The r3 ordering test failed because it treated equality in the previous idle
phase as acceptance of a new request, then waited a fixed 20 ns. Passive
diagnostics confirmed the new request had arrived but its ACK was still old.
The r4 test waits for the actual matching request/ACK phase; all original
fatal conditions remain, with an additional phase-stability assertion. Candidate
RTL did not change. Earlier unresolved endpoint and test failures remain in
their original evidence directories.

The integrated run passes 141 affected tests and four physical-export/timing
tests. The seven standing fabric/control/telemetry/scaling suites add 65 passes,
for 210 distinct ScalaTest cases. The 570 Python controls pass. Production
source and compiled classes remain bound to the fresh export cohort.

The first complete frame-control run stopped after 74 passing cases when the
20 MHz continuous all-bit positive exceeded its 60-second host allowance. Its
unchanged compiled binary passes in 75.778 seconds with a 300-second host
allowance. The r2 rerun changes only this subprocess wall limit and preserves
that failed run. It then exposes a separate synthetic ring deadline failure:
the old 58,600 ns budget at 20 MHz omitted 32 × 33 new byte-loading handshakes.
A passive trace shows five admissions and three correct last-legal-dispatch
frontiers before that deadline expires during frame six, byte 12.

The repaired supplemental feeder retains all frame, admission, frontier,
capacity, period and overflow assertions. Its conservative bound is 300 ns per
byte, including setup, acknowledgment and BD return; a per-byte watchdog catches
both stuck and overlong handshakes. The ring's existing service-cycle budget
adds exactly 32 × 33 × 300 ns, becoming 375,400 ns at 20 MHz. Four targeted ring
positives and four exact watchdog fault controls pass across both variants.
Original real-wire deadlines and testbench oracles are unchanged. The complete
344-case r3 campaign passes (292 positive cases and 52 exact-fault
controls), applying this bounded feeder repair and the 300-second host allowance.
Original r1/r2 failures and executed helper bytes remain archived.

All four fresh portable/physical strict SoC exports pass, including all four
mandatory generic mapping campaigns and exactly three SRAM macros per export.
A fresh independent review and the final evidence collector gate the
acceptance commit. The collector rechecks source, compiled/export, oracle,
actual-binary and exact-fatal bindings; its accepted status is explicitly
`PASS_DIGITAL_SCOPE_PHYSICAL_OPEN`. The retained evidence is:

- `build/async-i2c-addressed-bytes/production-handoff-r1/final-evidence-r1.json`
- `build/async-i2c-addressed-bytes/production-handoff-r1/frame-controls-r3/receipt.json`
- `build/async-i2c-addressed-bytes/closing-independent-review-r1/review-final-r1.json`

The complete A5 item remains open: frame publication/banks, sampled readWord
and reset epochs are not removed by this accepted receive-store substep.

## Matched cost

The full SoC comparison uses the same mapper, five pinned Liberty corners and
accounting as C1d (`b0a9fac`). The intervening A4b commit adds isolated experiments
without changing the production SoC. Historical source bytes are rebound to the
exact baseline Git blobs and recorded hashes; current inputs bind to the fresh
compiled/export cohort. Evidence is under
`build/async-i2c-addressed-bytes/production-handoff-r1/`.

| Measurement | BD before → after | Click before → after |
| --- | ---: | ---: |
| Logic area, excluding SRAM (mm²) | 2.9310398208 → 2.8748822144 | 3.6994805568 → 3.6434217344 |
| Change | −1.91596% | −1.51532% |
| TT listed-state leakage, including SRAM (µW) | 7.752528–10.033946 → 7.607764–9.867172 | 9.222217–12.361046 → 9.079021–12.144499 |
| Native payload bits | 11,967 → 11,454 | 12,120 → 11,607 |
| Portable periodic bits | 5,910 → 5,910 | 5,911 → 5,911 |
| Physical-export periodic bits | 5,920 → 5,920 | 5,921 → 5,921 |
| Work-clock storage pin load (pF) | 14.514997 → 14.514997 | 14.686423 → 14.686423 |
| Retained guard area (mm²) | 0.569961728 → 0.569961728 | 1.1059505408 → 1.1059505408 |

Within the complete SoC map, the I2C owner changes from 0.2280681088 to
0.1730739584 mm² BD and 0.2337229440 to 0.1774665536 mm² Click. Ordinary logic
outside that owner also changes by −0.001163456 / +0.000197568 mm² through
synthesis variation. The approximately 24% block saving is therefore distinct
from the 1.92% / 1.52% whole-logic saving.

All 27 matched wake windows per variant retain their class, effects, clock-edge
counts and durations. The two firmware windows retire 43 instructions each,
using 3,255 / 3,160 work edges and 271,607.839 / 263,691.109 ns. Maintenance and
sample windows are also unchanged. These results measure native digital-model
activity, not wake energy, reachable deep-sleep power, or placed/routed area.

## Physical path results and open gates

The five-corner pre-layout campaign covers 15 BD / 18 Click path groups and all
624 / 627 actual capture-clock sink pins in the mapped publication owner.
Analysis-only Q-source cuts preserve the original cells, input connections and
sink loads. Each cone is measured independently; no clock-to-Q subtraction from
an unrelated worst path is used. Source transition/load conditions and exact
netlists, libraries, scripts and OpenSTA binary are bound in the receipts.

The new byte-write transform exceeds its unchanged 10 ns allowance in three BD
and four Click corner/condition rows. Worst measurements are **15.040684 ns BD /
18.511408 ns Click** at SS 125 C. These remain failures. The measured local
trigger-to-CLK distribution fits its 2.5 ns bound in this isolated campaign.
There are no reported electrical violations in these selected conditions;
that does not bound the actual upstream transitions, external loads or routing.

A separate relative-path screen compares maximum data delay plus the complete
tabulated setup bound with minimum request-to-capture arrival. Its positive
margins are conditional on data already being stable at the publication input
when request arrives. They do not waive the 10 ns failures or qualify the
upstream source aperture. Self-feedback hold screening includes the signed
Click inverter delays (−0.007260 / −0.020219 ns at the two FF corners), verified
independently against the exact Liberty tables and 50% threshold convention.
The values are not clamped; their original parser rejection is retained.

Complete source hold through acknowledgment, Click capture pulse and phase
feedback, BD return, actual loaded transition bounds, reset assertion/release,
recovery/removal and routed RC remain open. The scratch-to-frame path crosses
two distinct native captures: a legal frame token cannot write the scratch bank
at that capture. This ownership fact must be preserved in later bank reductions.

The changed upstream `I2cUpdate` transform is measured separately using the
unmodified mapped stage. Every one of its 174 payload D pins and all 176 used
input bits has an actual path at both selected conditions in all five corners
(7,000 rows). All 180 input data bits are inventoried; only the four old
`headGray` bits have no structural path to payload D because the transform
recomputes that value. Analysis cuts only the identified controller keeper
feedback arcs; it creates no periodic clock and removes no data-path cells.

| Upstream whole-transform maximum (ns) | BD | Click |
| --- | ---: | ---: |
| TT 25 C, 3.3 V | 11.332152 | 11.312802 |
| SS 125 C, 3.0 V | 22.064154 | 22.061193 |
| SS −40 C, 3.0 V | 15.244105 | 15.241936 |
| FF 125 C, 3.6 V | 9.867076 | 9.866777 |
| FF −40 C, 3.6 V | 6.782236 | 6.782004 |

The unchanged 10 ns allowance fails at TT and both SS corners. All ten runs
complete with exact endpoints and unchanged input hashes; their combined
receipt correctly reports `MEASURED_BUDGET_FAILURES`, not a physical pass.
Selected electrical reports show no violations. Source/capture relative timing,
actual transition/load envelopes, inter-owner wiring and the full reset path
still need qualification; publication-only setup margins cannot establish them.
