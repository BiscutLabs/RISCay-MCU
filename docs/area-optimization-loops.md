# Three adaptive BD area loops

User-authorized on 2026-11-07. Starting commit `a978eae`: 1.506013 mm² flat
mapped logic versus the unchanged 0.531833 mm² clocked reference; hierarchical
mapped/repaired logic 1.587209 / 1.749243 mm². Three SRAM macros are excluded
from every logic comparison. Native storage is 5,780 bits; flat periodic sinks
are 2,822 (1,188 service / 1,556 work / 78 LF).

This is a BD-first continuation. Click remains independently implemented and
functionally regression-tested. Keep the wire/MMIO ABI, reset/lock/retention,
watchdog and original deadlines. No application policy or new periodic clock,
and no library change, is part of these loops. The replacement register-pointer
host ABI remains a separate decision; existing framed traffic must keep working.

## Decision rule

Each loop has one primary technique, a baseline, an implementation attempt,
independent review, affected functional/structural/timing checks, and a matched
whole-chip map. Record failed alternatives too. Adopt only behaviorally correct
changes with an area benefit and acceptable measured latency/timing tradeoffs;
otherwise retain the parent and carry the failed hypothesis into the next loop.
Use the same pinned mapper/PDK/profile. Keep repaired and flat metrics separate.
Local zero-wire-RC checks cannot close item 17; preserve the known Housekeeping
ordinary qualifier failure and every new failure explicitly.

Quality means preserved semantics first, then mapped/repaired area, storage,
guard cost, periodic sinks, wake duration/edges, margins and proof complexity.
Do not optimize bit counts alone. Reuse existing tests and timing templates.
Run one sbt process at a time. Commit/push each accepted loop to main.

## Loop 1 — exact finite-domain arithmetic and stage fusion (accepted)

The ADC scaler holds four 56-bit partial-result tokens at production coefficients
and implements twelve radix steps. Candidate: replace it with a single standard
native stage using an exact constant reciprocal; store only the live quotient.
For reduced positive N/D and raw x in 0..4095, M=ceil(N*2^K/D) with
2^K>4095*D guarantees floor(x*M/2^K)=floor(x*N/D). Search smaller shifts but accept
only exhaustive BigInt equality for all 4,096 inputs. Keep the full product until
the shift, then preserve the existing low-32-bit result. Production uses
N/D=5060/819, K=22, M=25913527 and 15 live result bits. Zero quotient, denominator
one and overflowing generic coefficients remain valid configurations.

This is a candidate, not a promise that constant multiplication maps best. A
projected three-nibble pipeline (25+25+15 bits) is the fallback if the single-stage
cone or required guard loses on area/timing. Initial request timing is a
conservative 80 ns model target; its own repaired cone must be measured.
Source admission, sample-bank capture, timestamp/priming, SPI pins and actual
clocked receipts remain unchanged. Capacity falls from four tokens to one; both
production callers admit only one conversion at a time, so no independent
requester loses buffering. The standard four-phase stage retains its 15-bit
production quotient through full return; the public result remains 32 bits.
The full product is shifted before low-32 truncation, and signed ADC offset
remains in the existing finish transform. All coefficients use one stage,
preserving the simultaneous-completion contract across scaling configurations. Complete source launch/hold, new capture,
ACK and pulse obligations apply after deleting the old prepare stage.

Verification: exhaustive ADC integer oracle, large-coefficient/modulo and
zero-quotient cases, held replies, reset, actual SPI/ADC, maximum-delay drainage,
sleep/activity, CI and generation/RDC. Preserve coincident completion across
coefficient configurations. Record measured results before choosing loop 2.

## Loop 2 — factor arithmetic without changing ownership (accepted after correction)

I2C byte transport was rejected at preflight, before RTL changes. Its steady
byte selection has a useful ring bound (18 edge events between byte ACK falls,
only eight queued slots), but first-byte snapshot acceptance has no bound with
the consumer clock deliberately stopped. The first word can be captured before
readStart; fetching later bytes independently could mix old and new snapshots.
This is a code-review finding, not a simulated failure. Fix the snapshot lifetime
before using byte projection as an area technique; retain the current transport.

Review also found two existing oracle gaps to address in that future I2C batch:
the occupied-ring test uses obsolete observedBits[339:336] instead of named
headGray (which needs Gray decoding and X rejection), and the stopped-consumer
snapshot test checks one byte whose old/new values are both zero. Selecting
loader word 1 and checking all four bytes distinguishes old profile ID 1 from
new PROGRAMMED 0. Do not change expected data to accommodate a stale snapshot.

The next candidate transfers loop 1's finite-range arithmetic method to elapsed
scaling, while preserving every storage lifetime: four narrow remainder steps
compute inc=floor((16*r+nibble*us)/1000), then
qNext=(16*q+inc+lastCarry) mod 2^32. Elaboration bounds inc with BigInt;
fold fractional carry into the narrow term. Keep state, fractions, loop count,
handshake and reset ownership unchanged. Use the existing wide-integer elapsed
oracle and slow-corner throughput test. Loop 1's matched reduction and unchanged ownership select this as loop 2.

Loop 2's first map shrinks logic but worsens the actual remainder-selection
critical path: the 28-cell request recipe gives −7.809 ns derated local setup,
versus the parent's +1.078 ns (itself below the 2 ns reserve). All selected data
pins pass their actual Liberty limits and tables, so this is not an extrapolation
artifact. The accepted correction lengthens only that guard to 34 cells, using measured
same-corner increments and a fresh repaired-map check. Minimum setup is +3.790 ns;
latest conditional capture is 257.435 ns, within the unchanged 645 ns test envelope.
Do not attribute the measured path to the final quotient adder merely from RTL.

## Loop 3 — remove payload after its last consumer (accepted)

The third loop applies explicit last-consumer projection. RF consumes a writeback
before the unchanged 31 ns forwarding guard; execute unconditionally replaces it.
Drop those 37 bits from the Join continuation and reconstruct zero only inside the
shared ISA transform. A live field/width property prevents future schema fields
being silently omitted. Keep state-FIFO and new execute writeback storage intact.

The pad-level build also has no retirement-trace consumer, but native primitive
protection prevents ordinary synthesis from trimming its 107 stored trace bits.
Explicitly omit that field before the physical execute capture; preserve the full
default debug/verification core. The physical policy records the option. Test both
configurations against identical independent memory histories, including every
register's signature, faults, stalls and a reset with an accepted load outstanding.
The reset replay observes zero registers before reseeding. A trace-disabled SoC
test checks GPIO, host readback, lock and POR. No existing expectation is relaxed.

No forwarding/ACK guard is shortened. Recheck the smaller capture/Join trees on
repaired maps: fewer storage bits do not prove hold or capture ordering. RF event
launch/full return and routed closure remain explicit qualification boundaries.
A competing exact Mersenne ADC formula passed a finite-domain SAT miter and cut
its isolated mapped arithmetic by 0.003159 mm²; that small whole-chip opportunity
was deferred in favor of removing proven-dead protected storage. Its isolated
pilot is not counted as a whole-chip saving.

## Results and lessons

| Loop | Adopted change | Flat / repaired logic | Native / periodic storage | Wake / timing effects | Lesson used next |
| --- | --- | --- | --- | --- | --- |
| Baseline | a978eae | 1.506013 / 1.749243 mm² | 5,780 / 2,822 flat sinks | BD firmware 4,139 work edges, 345.275 µs | Remove architecture costs before shortening surviving guards |
| 1 | Exact ADC stage fusion | 1.477870 / 1.713602 mm² | 5,571 / 2,822 | ADC 220 edges; other wakes unchanged | Exact range arithmetic and fewer stores beat a slightly larger guard; reject ambiguous payload lifetimes |
| 2 | Bounded elapsed increment; measured guard correction | 1.466714 / 1.700345 mm² | 5,571 / 2,822 | Model wakes unchanged; local setup +3.790 ns | Smaller arithmetic can map slower; inspect the real critical path and include guard cost |
| 3 | Last-consumer CPU projection | 1.455121 / 1.690651 mm² | 5,427 / 2,822 | Debug-model wakes unchanged; local hold/ACK improve | Project before protected storage, preserve architectural/retirement oracles, and remeasure changed loads |

The [independent reviews](reviews/bd-area-loops.md) record findings, fixes and
qualification scope. The [area ledger](area-ledger.md) remains the canonical measurement ledger.
This page records experiment choices and transferable lessons, not a second
custody/attestation framework. The three loops are complete: −3.38% flat logic,
353 fewer native bits and no added periodic sinks. Whole-stage fusion saved the
most; arithmetic factoring required a measured guard correction; last-consumer
projection removed storage that mapping protection could not trim. Lifetime
review rejected the I2C candidate before it could introduce mixed snapshots.
BD remains 2.736× the clocked logic area, a 0.923288 mm² gap. No new P&R or power
claim is made. Stop here; the remaining gap needs larger ownership changes and
surviving-guard qualification, not an assumption that these three loops finish
optimization.
