# BD compact Housekeeping effects review

Fresh independent source review found no blocking RTL or test issue. The
transition body is unchanged from `c8bcb74`. One parent transform supplies the
259-bit closed state bank and 41-bit effect stage; there is no state payload copy
in the stage. The accepted command remains held in the Join through actual bank
capture and full reply return. Services captures the held new consumed value on
the original receiving edge, while the live bank still contains the old value.
No periodic clock, synchronizer, payload mirror or Click change is introduced.

The independent state/effect oracles remain. Tests additionally exercise old-bank
visibility before ACK, new consumed-time receipt versus old same-edge bank,
invalid time targets, and a queued next command while the first reply is held.
The fast gate passes 397 Python and 227 Scala tests; all 82 focused cases pass.
Generation audits and both RDC proofs pass. All 15 extended activity, deep-sleep
and compiled-firmware tests pass in BD and Click. Both final full-capacity BD
boot cases pass: 333.860569 ms primary and 953.315969 ms golden recovery at
10 MHz, with 3,338,586 / 9,533,140 work edges. These exactly match the Control
batch's integrated measurement. Original boot deadlines and assertions remain.

The repaired graph and native/direct-control branch proofs pass. The new timing
binding follows the actual parent arithmetic through the passive alias into
all 41 effect capture pins; checking the child's identity transform alone would
omit that arithmetic. It also covers the 259-bit direct state capture and reuse.
Five corners and two input slews give these zero-wire-RC bounds:

| Bound | Minimum | Margin policy |
| --- | ---: | --- |
| Full arithmetic to effects setup, no receipt-cycle credit | +6.950 ns | 20% early/late derate, Liberty aperture and 2 ns reserve |
| State-bank setup, no receipt-cycle credit | +18.915 ns | Same |
| State-bank setup, one existing work edge | +68.915 ns | Same; at least 50 ns on the unchanged receiver |
| Held command reuse | +50.718 ns | Same |
| Effect hold before old bank changes | +30.461 ns | Same |
| Bank capture high/low | +41.379 ns | Same |
| Same-event state feedback hold | +0.880 ns | Nominal same-corner, actual slew and Liberty hold; mismatch/routed qualification remains open |

The local stage hold/publication bounds are +0.745 / +4.420 ns with the existing
20% two-sided policy, without the additional 2 ns reserve. The capture tree has
2.378 ns maximum latency and 0.308 ns spread. All 1,030,830 sampled operand and
feedback arc evaluations are within Liberty tables. Five run receipts pass.
Unchanged source admission into the retained Join is not newly requalified.

The selected ordinary data-driver trees also pass all five corners: 15 roots
and 161 buffers, worst slew 1.864 ns, fanout at most 16, characterized loads.
These trees cost 0.004948 mm² and were already introduced in the Control batch.
This does not establish whole-chip electrical closure.

All ten native bank-reader cases are positive: 905 targets have minimum
+183.241 ns later-read setup and +1.420 ns same-edge hold; bank-to-feedback
ordering is +11.045 ns. These retain the existing conditional reader contract.

The combined reader campaign receipt remains **failed** because its separate
ordinary 50 ns qualifier screen fails SS/hot: −7.683 ns at 0.02 ns input slew
and −8.170 ns at 2 ns, versus −7.680 / −8.167 ns in the retained historical
campaign (not a fresh rerun of the immediate parent). The path remains
housekeepingReturning Q to housekeepingOrdered period[11] D. Qualifier hold is
+0.432 ns. Seventeen qualifier launches reach 1,056 targets; none receives the
bank's conditional read or multicycle allowance. The selected data-tree table
audit above is not a complete electrical qualification of this qualifier cone.
Routed min/max RC, clock skew, reset distribution, noise, global electrical
closure, statistical mismatch and complete primitive waveform checks remain
item 17. This is local evidence, not tape-out qualification.

Evidence: `build/bd-housekeeping-effects/{map-r1,timing-r1,housekeeping-bank-r1,
ordinary-data-production-r1,summary-r1.json,activity-r1.json}`, the focused and
extended logs, `independent-reader-repair-review-r1.md` in that evidence folder,
`full-boot-r1.json`, `build/bd-housekeeping-effects-full-boot-r1.log`, and
`build/bd-housekeeping-effects-ci-r1/receipt.json`. Failed
ordinary-qualifier experiments remain under `build/hk-qualifier-tree-r1/r2` and
were not adopted. No behavioral expectation or deadline was relaxed.
