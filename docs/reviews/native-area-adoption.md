# Passive data, ordering guards and SRAM prepare fusion

Status: **locally adopted; digital checks and independent review pass**.
This batch implements A8b, the standard-controller A7b cohort and the first A10
fusion together. Both independent native implementations retain their protocols,
ABI, reset isolation, programming lock, SRAM contents and permanent supervision.
Full routed qualification remains migration item 17.

## Scope

- chisel-async [`06b1216`](https://github.com/BiscutLabs/chisel-async/commit/06b1216493032c1fbb1a923aed82815b9cd7944e)
  adds an opt-in passive data allowance. The MCU pins a source-specific local
  artifact; [provenance](../../project/chisel-async-source.json) records its exact
  commit, coordinate and JAR digest. Default library behavior remains resettable.
- All final 108 BD /122 Click allowances use that primitive. Every output is
  audited to actual native payload D pins before physical aliases merge nets.
  Physical capture bindings retain exact lane identity, including independently
  proved constant polarity. No clock, storage, reset or per-lane buffer belongs
  inside an allowance. See [the contract](../passive-allowance-contract.md).
- The guard policy accounts for all 199 baseline BD ordering guards. Two fused
  stages remove four; 180 canonical guards and 15 custom ordering guards remain.
  Custom guards retain explicit obligations and their existing counts. Click's
  standard ACK cohort retains its full rearm and pulse-width requirements.
  The [sizing contract](../gf180-guard-sizing.md) defines the 20% two-sided
  engineering derate and 2 ns residual floor; this is not foundry-qualified OCV.
- Program and data SRAM each lose one 101-bit pure-copy prepare stage per
  variant. The preceding Join holds ownership through the first fork's return.
  [The fusion contract](../native-sram-prepare-fusion.md) names the actual source,
  capture and reuse paths. The clocked byte-macro boundaries remain unchanged.

The matched parent is `2f5aa54`; skill installation `c37bfed` changes no hardware.
Matched comparisons use the same profile, three SRAM macros, libraries,
mapping recipe and graph-preserving electrical repair. The area ledger is the
single source for final totals, including DLYD by purpose. Removed-stage
allowances are not counted twice.

## Evidence and retained failures

Library verification passed 16 Scala cases, 17 event-case groups, 70 Python
controls, 42 legacy export controls and documentation checks. Independent review
reran the Python controls and approved the supported primitive. The locally
published source-specific artifact differs from the initially tested snapshot
only in its manifest; all 315 archive entries were compared.

Initial MCU SRAM testing passed 28 cases in three suites. The first full Python
run exposed stale synthetic fixture bindings and the closed probe-source
fingerprint; their exact-source updates passed 1,146 controls on the second run.
These failures remain in `build/area-adoption/{sram-r1,python-r1}.log`.

The first physical preparation exposed unused native payload chains pruned by
the audit frontend. It now retains exactly the known native model types before
cleanup, matching the physical mapper. No missing-instance exemption was added.
Both complete emitted audits pass; six actual-graph negative controls reject
invalid fanout to capture control, reset and periodic storage. Independent review
confirmed the retention rule and reran 44 hold/handoff/graph controls.

Strict export then rejected the fused Join's missing declared credit-data port.
A narrow `dontTouch(owner.out.bits.left)` preserves that existing port; the ABI
checker is unchanged. The first broad regression was deliberately stopped before
editing the source. Its incomplete log and cancellation receipt are retained and
do not count as a completed pass. Fresh exports and the final regression use the
corrected source.

The first mapped native audits passed, but reset-buffer preparation assumed every
native adapter had a reset pin. Cell-free passive aliases correctly have none.
The repair path must identify and prove those exact alias bindings while retaining
all other native reset buffers; it must not silently skip missing reset ports.

Broad exploratory guard sweeps retain their completed rows, timeout/crash evidence
and incomplete status. Focused guard checks must keep every changed ordering,
capture, hold and Click rearm/pulse obligation. Separate setup/hold composition is
required where allowance removal and SRAM fusion change the data path. A partial
baseline or a process that crashes after printing results cannot qualify a case.

The full same-event feedback screen passes 55 corner/root cases across four BD
and 24 Click banks, covering 2,586 capture inputs and 465,970 sampled hold rows.
Minimum genuine Liberty hold is **+0.728611 ns BD / +0.728616 ns Click**. Every
eligible path remains within its Liberty load/slew tables at the sampled
conditions, with no unreachable
lane exemptions. Independent review re-parsed all rows and checked every frozen
input and artifact hash. These finite samples are a local zero-RC screen;
different-event release and correlated/routed variation remain separate.
The receipts are `build/area-adoption/feedback-{bd,click}-final-r2/results.json`.
Twenty-one unit controls reject wrong clocks, omitted endpoints, missing arcs,
table extrapolation and incorrect reset-cell polarity. A physical Click control
delays a real capture branch by 1,000 ns: all 32 victim checks fail hold while
the 32 unaffected route checks remain identical. These are two target D pins
with multiple sample/polarity checks. Changing the analysis period from 1,000 to
5,000 ns leaves every result in that control subset unchanged.

The fused SRAM path passes **80 corner/slew cases and 75,720 queries** across
eight source/receiver targets on the final repaired graphs. Each case includes
both operand-order contexts. Minimum conditional setup is +36.211737
ns BD / +77.739302 ns Click. BD fork-return hold, with zero source-contamination
credit, is +3.312031 ns. Ten mapped fault/period controls pass. Click's complete
local source-hold argument binds all four actual first-fork receivers across
program and data RAM to their exact guard-campaign receipts. Minimum hold is
+13.095116 ns, pulse-high +4.853257 ns and ACK-after-rearm +4.575096 ns.
See `build/area-adoption/fusion-summary-r1.json` and
`fusion-click-local-hold-r1.json`.

The final guard seal passes **1,630 corner/slew cases**, covering 90 BD and
73 Click owners. All 91 changed BD guards and 73 changed Click guards meet the
selected 20% two-sided derate and 2 ns residual floor. Worst changed margins are
+4.159930 ns BD publication, +5.337013 ns elapsed setup, +12.847456 ns Click hold,
+4.801602 ns Click pulse-high and +4.244298 ns Click ACK-after-rearm. The elapsed
request uses 28 DLYD cells, rather than the pilot's 25; standard BD publication
and Click ACK chains use eight. This does not qualify the 104 retained BD guards.

Five original BD OpenSTA crashes/timeouts remain in the primary report. Exact
retries disable only synchronous clock-reconvergence credit; all 25 successful
overlap cases retain identical raw timing results. The retry's physical controls
pass. Independent review reproduced the combined seal and accepted only the
policy's status/provenance change; every effective count remains byte-equivalent
to the measured map copies. Receipts are `build/guard-sizing/final-seal-r1.json`
and `policy-equivalence-r1.json`. The sizing contract records the complete retry
and campaign provenance, including bounded worker-capacity changes.

The strict probe's first complete run exposed 384 literal-zero lanes created by
the removed SRAM projection stages. A new exact graph proof discharges only
these 12 endpoints' low 32 bits, retains their zero observations, and inserts
four-state zero assertions. All 828 dynamic request lanes retain both-polarity
coverage. Eight negative/unit controls and independent reproduction on all four
exports passed before retry. All four strict-r4 exports then passed within the
2,400-second host cap, including reset, sleep-clock background activity and the
compiled/executed mapping attestations. The aggregate receipt is
`build/area-adoption/strict-r4/summary.json`:

| Export | Mapping comparisons |
| --- | ---: |
| Physical BD | 628,176,440 |
| Physical Click | 539,526,042 |
| Portable BD | 627,966,840 |
| Portable Click | 539,338,362 |

These are repeated mapping comparisons, not independent functional scenarios.
Original timeout and paired-budget failures remain in the strict-r2/r3 logs;
no dynamic lane or mandatory budget was waived.

One broad-regression failure was the Click slow-clock cold-boot fixture's
240-second host-process limit. An unchanged executable completed in 281.93 host
seconds, with `RISCAY_SOC_PASS` at 906.383 simulated milliseconds, before its
unchanged 1.2-second design deadline. The exact replay and input hashes are in
`build/area-adoption/deep-board-replay-r1/`. The completed broad run covers 803
cases in 67 suites: 802 pass and only this host timeout fails, with no aborted,
skipped, canceled or pending cases. All 211 frozen inputs are unchanged.
Original XML reports and the test source remain under `regression-r2-reports/`.
The reviewed change raises only Click's host allowance to 600 seconds, matching
BD. The exact named test then passes, followed by all five physical tests.

The final distinct cohort is **808 successful Scala cases**; the replacement
case is counted once. The complete final Python run passes **1,198 controls**.
Receipts are `build/area-adoption/regression-r2.json`, `regression-r3.json` and
`python-r3.json`. No functional expectation or simulated deadline changed.

## Matched cost and activity

Fresh whole-chip mapping is **2.229395 mm² BD / 3.048424 mm² Click**, excluding
SRAM. Accepted structural electrical repair raises these to **2.412382 /
3.252393 mm²**. Mapped logic falls 20.177% / 14.228% versus `2f5aa54`, reaching
the BD 2.3 mm² milestone with the accepted local batch.
The [area ledger](../area-ledger.md) records allowances, guards and DLYD purpose
without double-counting. No new P&R result is claimed.

All 27 native-model wake windows per variant match the parent. The 43-instruction
firmware wake retains 3,257 BD / 3,212 Click work-clock edges. Periodic clock
sinks remain 4,810 / 4,865; this batch removes native overhead rather than another
clocked service owner. The physical chain reductions do not change the model's
nominal delays, so digital activity is not a measurement of their silicon energy.
Listed-state TT leakage bounds, including the same SRAM macros, fall from
7.87–10.07 to 6.43–8.39 µW BD and 9.39–12.38 to 8.10–10.87 µW Click. These omit
analog power, LF switching and reachable-state sleep analysis.
Cost and activity receipts are `build/area-adoption/{cost-r3,activity-r2}.json`;
independent review checked their source, graph, library and workload identities.

Fresh independent review checked the implementation, all final receipts and
their source/graph/tool identities, retained failures and exact controls. It
reproduced the guard seal and confirmed that policy acceptance changes only
status/provenance, with no post-measurement recipe change. The final source and
evidence inventory is `build/area-adoption/final-adoption.json`.

## Qualification boundary

Positive local pre-placement results permit reversible parameter adoption under
the user's current workflow. They do not establish extracted min/max RC,
statistical mismatch yield, full reset-distribution closure or a tape-out-ready
chip. Electrical violation rows remain visible. Listed-state TT leakage bounds,
digital work-clock edges and measured deep-sleep power are distinct quantities.
Later item-17 evidence may require guard lengthening or local hold repair.
