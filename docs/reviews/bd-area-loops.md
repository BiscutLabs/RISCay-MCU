# Independent review: three adaptive BD area loops

## Loop 1: exact ADC scaler

Fresh review by `bd_control_bank_review`, with an independent arithmetic review
by `area_action_plan_review`. No required functional fix remains. Review traced
the real assemble latch through the unbuffered Fork, new scaler and consumer
Join; deleted prepare-stage launch lead is not credited. Exhaustive finite-domain
selection is exact before low-32 truncation, including zero and overflowing
coefficient cases. Production admission permits only one conversion at a time.

Final repaired production evidence: `build/area-loops/loop1/timing-r4`, all five
corner receipts / ten corner-slew cases pass. Same-corner composed bounds use
20% two-sided engineering variation, a 2 ns reserve and Liberty apertures:

| Bound | Minimum margin, ns |
| --- | ---: |
| Actual source to scaler setup | 98.739287 |
| Scaler to consumer Join setup | 48.451071 |
| Complete source-return hold | 129.829306 |
| Complete output-return hold | 62.981251 |
| Input ACK high | 124.367590 |
| Scaler closed pulse | 117.838172 |
| Integrated production open pulse | 2186.132232 |

All 15,720 data-cone arc checks pass (1,557 arithmetic plus 15 output arcs,
ten contexts), including actual loaded slew/Liberty range checks. The 17 padded
consumer data lanes are proven constant; capture/ACK coverage still includes
all 32 consumer lanes. Failed r1-r3 binding attempts remain: conditioned launch,
OpenSTA feedback reachability, and missing constant-lane classification. None
was resolved by a circuit waiver or by dropping a live data lane.

Maximum conditional propagation is 504.030 ns request-to-capture, 509.006 ns to
input ACK, 687.216 ns to publication, 308.637 ns output-ACK-to-complete-release,
and 630.751 ns input-ACK-to-source-release. Arbitrary backpressure is excluded;
these are not transaction deadlines. The production open-pulse proof uses actual
admission plus the next conversion's 32 wire slots, at least two 50 ns work edges
per slot (3,200 ns). It adds no clock or wait. Generic standalone pending-input
rearm remains unqualified; the failed query is retained. Other coefficients have
functional evidence, not this production 25300/4095 physical map.

Local canonical checks also pass: scaler setup/hold +91.991/+0.783 ns, consumer
+15.657/+0.764 ns. Those apply 20% without the composed 2 ns reserve; do not
substitute them for the full-return proof above. Global electrical closure,
extracted min/max RC, reset distribution, noise and statistical mismatch remain
open. This is local conditional graph timing, not tape-out qualification.

Functional evidence: 32 focused cases; final CI 397 Python +227 Scala pass;
generation/RDC pass. Extended checks are 15/17. The two accelerated-maintenance
sleep failures reproduce exactly on detached parent `a978eae`, including Click;
the original assertions and failed logs remain. Normal/deep sleep and measured
activity pass. The [ledger](../area-ledger.md#adaptive-area-loop-1-exact-adc-arithmetic)
records matched area, storage, clocks and wake duration.

## Deferred I2C candidate

Fresh `bd_publication_slot_review` rejected byte transport at preflight. A late
readStart can follow capture of the first read word when the consumer clock is
stopped; independent byte fetching could mix snapshots. The review also found
obsolete/X-prone occupied-ring probes and a first-byte snapshot test whose old
and new expected bytes are both zero. These are code-review findings; no I2C
RTL or oracle changed. See the [experiment record](../area-optimization-loops.md).

## Loop 2 — bounded elapsed arithmetic (accepted after a timing fix)

Fresh reviewer `bd_effect_banks_review` checked the arithmetic, original oracles,
repaired parent/candidate graphs and every selected corner/slew case. Quotient
history is added once; a bounded increment carries the four radix remainder
steps. BigInt bounds include the final fractional carry. State widths, fraction,
turn count, ownership, reset and handshake remain unchanged.

The first candidate saved area but failed local setup in all ten cases, reaching
−7.809 ns with 28 request-delay cells. The parent also missed the 2 ns reserve
(+1.078 ns minimum). Actual path inspection locates the critical cone from old
target[1] through admission/nibble selection to remainder[2][7]; attributing it
to the final quotient adder from source alone would be wrong. Both graphs pass
actual loaded Liberty/table limits, so the failure is not extrapolation.

The fix lengthens only the elapsed request recipe from 28 to 34 DLYD cells.
Measured same-corner increments indicated 33; one additional cell supplies a
conservative reserve. The final fresh synthesis/repair and ten-case campaign
passes: setup **+3.789599 ns**, publication rise/fall **+4.288913/+4.274889 ns**.
These use the existing two-sided 20% engineering policy and 2 ns floor. The
zero-source-credit local hold is **+0.621384 ns**, unchanged in every case; it
is not a claim of a composed 2 ns hold reserve. Latest conditional capture is
**257.434728 ns**, within the unchanged 645 ns slow-step throughput test.
No digital deadline or oracle changed, and no guard was shortened.

All ten final data audits cover 7,465 pins and 2,487 output loads per case, with
no actual transition/capacitance, ordinary-policy or table-range failure.
Selected request/capture/return paths also pass their electrical checks in all
40 contexts. Blanket 2 ns whole-chip report rows are not substituted for the
actual ordinary-cell limits or hidden as a chip-wide pass.

Focused elapsed/scaling tests pass 19/19; CI passes 397 Python and 227 Scala
cases before the physical-only count correction. Final integrated loop-3 CI
also passes with that correction. Generation/RDC pass both variants. Activity
and sleep checks are 6/8: the same two accelerated-maintenance failures reproduce
on the starting revision and remain open. Activity windows are unchanged.

Evidence: `build/area-loops/loop2/{map-r2,final-local-r2,final-ranges-r2,
final-electrical-r2.json,independent-review-final.json}`. Parent and 28-cell
failures, including all logs, remain beside them. Conditional input launch is
explicit: full FIFO seed/admission composition, reset distribution, extracted
RC, noise and statistical mismatch are not closed by this local campaign.

## Loop 3 — last-consumer CPU projection (accepted)

Fresh source/test reviewer `area_action_plan_review` and independent timing
reviewer `bd_control_bank_review` found no unresolved blocker for this scoped
change. Two test-review findings were fixed before acceptance: use the typed
Join channel id `left_input`, and observe reset register signatures before the
program reseeds them. Existing retirement assertions and all deadlines remain.

Named continuation fields equal live CoreState fields minus writeback, including
widths. Execute never reads the old writeback; RF still consumes it directly
before the same 31 ns guard. Shared ISA, state/RF storage and all handshakes are
unchanged. Physical-only trace removal has both debug/physical independent
memory-history comparisons and a GPIO/host/lock/POR integration test; default
debug exports retain full retirement. SocSpec is included in the fast CI gate.

The mapped graph confirms exactly 144 fewer native bits and unchanged 85 core
primitive identities/guard recipes. CI passes 397 Python/235 Scala; focused
25+4 and extended 15/15 pass, as do both generation/RDC audits. Review inspected
the receipts and matched area/sink reports, not only test exit codes.

| Conditional nominal bound, ns | Parent | Loop 3 |
| --- | ---: | ---: |
| Execute allowed input lag | 112.046778 | 112.249256 |
| Immediate-source-reuse hold | 1.187441 | 1.339435 |
| ACK after latest capture | 1.381441 | 1.533435 |
| Join-left to execute setup | 134.385037 | 133.993412 |
| Join-right to execute setup | 126.592961 | 126.804689 |
| Left ACK return after source close | 146.218791 | 146.236421 |
| Right ACK return after source close | 146.297499 | 146.297499 |

All ten stage and ten Join contexts pass. The candidate has the same 647 live
sources; 37 dead Join inputs disappear and dynamic capture destinations fall
278→171. There are no constant-lane exclusions. All 55,720 data-arc/table checks
pass. The actual per-pin electrical audit covers 45 contexts, 78,225 data pin
samples and 18,990 request/capture/ACK pin samples, with no missing limits or
waivers. It uses the actual Liberty/ordinary 0.8× limit and native 2 ns policy;
blanket 2 ns global-report failures remain in the logs and are not a chip pass.

These margins are **nominal, conditional, zero-wire RC**. RF launch-event
alignment, full source return/rearm, mismatch, routed RC/noise/reset and global
electrical closure remain open. No guard was shortened on this evidence.
Evidence: `build/area-loops/loop3-preflight/{parent-summary.json,
candidate-summary.json,candidate-electrical-r1/results.json}` and the loop-3
functional/area receipts listed in the [ledger](../area-ledger.md).
