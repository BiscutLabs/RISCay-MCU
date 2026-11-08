# BD memory Source/Return guard review

Scope: the nine 200 ns model guards in BD ProgramSource/RamSource and
ProgramReturn/RamReturn, compared with `fcb0387`. Click, the synchronous
comparison chip, the ABI, memory ownership and reset domains are unchanged.
The retained `a5a68cd` loop-3 maps are the matched before measurement: the
intervening commit changed tools/docs, not RTL or physical recipes.

## Causal changes

| Old wait | Replacement and obligation |
| --- | --- |
| Two Source grant guards | Publish the existing LongHold output directly. Its own capture/publication path must cover both the role latch and native eligibility register. No clocked-receiver latency is credited. |
| Two Source reservation-ACK guards | Use the retained return C-element directly. It includes the reservation, decision/publication receipts and, for Program, the complete selected Stored branch. |
| Two Return cleanup guards | `released` clears `pending` directly, but remains set until `pending OR armed` falls. Capacity waits for the full branch/history return. |
| Program decision guard | Retain and size against the real decision sender, decode and Stored selection. Charge sender CLK-to-Q without crediting its preceding work-clock cycle. |
| Two Return arm/history guards | Retain and size for payload/permission capture on rise and request inhibition, completion-proof withdrawal and keeper closure on fall. |

Source retirement now waits for the delayed decision request to fall as well as
the raw request. The first direct-ACK candidate omitted this dependency and
failed the existing Program capture/reset test with `HANDSHAKE_ORDER decision`.
A new reservation could see the old delayed decision. The fix makes that return
part of the decision ACK handshake; it does not add a timer or weaken the test.
The original failure is retained in `export-sources-r1.log`.

Return completion follows `released rise -> pending fall -> armed fall ->
history fall -> released fall`. All four branch completion proofs must exist
before release rises. This is stronger than the historical proposal that tied
release to pending and relied on a narrow feedback pulse. Loaded measurements
must still prove that the set term persists until keeper regeneration, and
that the history tail outlasts both offer inhibition and proof withdrawal.

POR still resets transport/storage. Qualified application reset revokes only
presentation eligibility/permission and application response history. It does
not cancel accepted memory effects, erase a retained word or reset POR phases.
The close/reset/rebase coordinator and its receiving-clock proofs are intact.

## Verification and evidence

The unchanged Source/Return suites plus two new causal-history tests pass
113 cases, with randomized primitive delays and existing payload, reset,
backpressure and full-return oracles. The new monitor fails deliberately when
`released.common` is changed back to `pending`: `RETURN_RELEASE_BEFORE_HISTORY`.
The fault run uses the same generated testbench and keeps its original payload
and delivery checks. No functional assertion or deadline is weakened.

The compact `check_memory_owner_timing.py` adapter reuses the existing repaired
leaf graph, reviewed keeper cuts, path tables and per-pin electrical audits.
It does not introduce a new physical solver or evidence-custody framework.
Counts use the same-corner 20% two-sided engineering allowance and 2 ns residual.
These are local zero-wire checks, not statistical mismatch or tape-out signoff.
Complete routed min/max RC, coupling, reset distribution and global electrical
qualification remain open. The separate 0.05 mm² routed hold-repair reserve stays.

Evidence root: `build/bd-source-return-guards/`. The final area, activity and
verification totals are recorded in the [area ledger](../area-ledger.md).

## Final local results and independent review

Three independent agents reviewed the Source paths, Return paths and the final
combined batch. The final graph removes six guards and uses **10/12/12 DLYD**
for Program decision / Program Return arm / RAM Return arm. All **80 Source +
260 Return + 20 source-hold contexts** pass across five corners and both source
slews. The closed forcing envelopes check **9,940 owner/parent outputs**, including
actual per-pin limits and every gate feeding keeper common/set inputs. No path,
table-range or electrical failure is waived. A partial Return run was restarted
when its checker changed; its partial logs remain, and the complete frozen run
has an unchanged-input receipt.

| Bound | Worst residual, ns, after 20% two-sided derate and the 2 ns floor |
| --- | ---: |
| Program decision setup | +3.358 |
| Source eligibility before grant | +3.114 |
| Source role before grant | +4.904 |
| Canceled Stored-path return | +2.128 |
| Return data before offer | +20.978 |
| Return history after request inhibition | +5.796 |
| Released keeper retained before set withdrawal | +2.060 |
| Weakest completion keeper retention | +1.606 |
| Publication-ACK inhibition before decision reuse | +29.206 |

The last row uses the existing retained decision bridge, not an arbitrary native
producer. Its earliest new payload is E3 after ACK falls; the check credits only
one 50 ns work period under the existing 20 MHz maximum. A bridge-removal change
must re-prove this hold. See both memory return contracts for that internal-port
requirement. The keeper envelope is normal operation after settled reset; POR
assertion/release distribution remains a separate qualification gate.

Actual mapped logic is **1.455121 -> 1.345309 mm² flat**; hierarchical mapped logic
is **1.532146 -> 1.419686 mm²**, and repaired logic **1.690651 -> 1.578033 mm²**.
Two Return pending parent buffers initially exceeded the native 2 ns slew limit
at SS/hot (2.124 ns). Changing only those parent drivers from `buf_2` to `buf_4`
closes their forcing bounds and adds 0.0000263424 mm², included in the final area.
Protected native storage/keeper recipes remain intact. Native storage and all
periodic clock-sink inventories are unchanged.

Reproduce the local physical checks with configured physical tools:

```text
python tools/check_memory_owner_timing.py --mapping <map> --output <source-output> --group source
python tools/check_memory_owner_timing.py --mapping <map> --output <return-output> --group return
python tools/check_memory_source_hold.py --mapping <map> --export <bd-export> --output <hold-output>
```

The passing receipts are `final-source-timing/receipt.json`,
`final-return-timing-r3-frozen/receipt.json` and
`final-source-publication-hold/receipt.json` under the evidence root. Production
adoption changes only the policy status/provenance from the measured candidate;
the per-instance counts and parameter records are identical. Whole-chip model
activity improves the 43-instruction firmware wake from 4,139 to 3,967 work edges.
The unchanged-oracle accelerated guard replay passes separately; neither activity
run predicts mapped silicon power or duration.

## Final regression acceptance

The final fast gate passes **406 Python properties and 235 Scala cases across
26 suites**, with no skips, changed inputs or missing outputs
(`ci-r3/receipt.json`). The affected extended run passes **207 cases across
12 suites**, including all **69 generic-boot cases**. Its full-capacity primary
and golden-fallback boots pass for both variants; `extended-reports/` preserves
the full JUnit results before CI runs its smaller boot selection. The focused
Source/Return run passes **113 cases** (`focused-export-r2.log`).

All four debug/physical generation audits, both production RDC proofs and the
complete mapped/repair graph proofs pass. Evidence includes `check-debug-*-r2/`,
`check-physical-*-r2/`, `rdc-*-r2.log`, `map-r3/electrical-repair/receipt.json`
and `fast-model-final/results.json`. The failed first Source candidate and the
failed R2 electrical results remain retained. Independent review findings are
resolved; no functional expectation or simulation deadline was relaxed.
