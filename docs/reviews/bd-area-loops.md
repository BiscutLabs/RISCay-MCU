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
