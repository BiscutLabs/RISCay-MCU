# Area ledger

This is the running item/batch ledger from the 11b1 baseline. Use the same
Groundlark low-power profile, three GF180 SRAM macros, pinned standard-cell
libraries, mapper and accepted repair flow for matched production comparisons.
Full routed physical requalification remains migration item 17.

The next milestone is **BD mapped logic below 2.3 mm² excluding SRAM**. Starting
from 2.825888 mm², that requires another **0.525888 mm² (18.61%)** reduction.
The milestone is unmet. A7b/A8b start as isolated experiments; their local deltas
do not count toward it until adopted and measured on the production design.

## Accepted production batches

Every area entry is mm² and every pair is **BD / Click**. Mapped means before
electrical repair; repaired means accepted pre-placement repair, not P&R.

| Item / source | Mapped logic | Repaired logic | Guards | Allowances | DLYD | Periodic clock sinks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 11b1 (`c195deb`, merged `29e0ea7`) | 2.825888 / 3.585890 | 3.014986 / 3.795762 | 0.542153 / 1.061831 | 0.413624 / 0.366484 | 0.536041 / 1.052901 | 5,072 / 5,127 |

11b1 removes 268 periodic flip-flops per variant. Its complete contract, matched
parent comparison, wake activity and listed-state leakage bounds remain in the
[review evidence](reviews/control-frame-borrow.md). This ledger starts from that
accepted graph; it does not replace historical evidence with newly generated
receipts. The earlier PR10 maps fail current receipt validation with
`REPAIR_INPUT_CHANGED`; those failures are retained under `build/area-ledger/`.

## Counting rules and evidence

- Logic excludes all three SRAM macro footprints (0.466240659 mm² LEF total).
  Do not mix LEF footprints with the macros' different Liberty area values.
- Guards are the exact native matched-control adapters with model delay above
  1 ns. This accounting convention does not classify shortening eligibility.
  The separate 1 ns functional-adapter costs are 0.042521 / 0.053598 mm².
- Allowances include every whole-transform-allowance adapter. Named
  `data_delay` instances are a subset, never an additional cost.
- DLYD counts every such mapped leaf, regardless of role. It overlaps guards
  and is reported for attribution; **do not add DLYD to guards**.
- Periodic sinks are actual service, work and LF clock-input sinks, including
  the three SRAM CLK pins. Exclude native event-triggered storage and the
  separate SDA event sink. These are not energy estimates.
- Wake edges, listed-state leakage bounds and reachable sleep power are
  different measurements. Keep their evidence and qualification limits with
  each item's review; never infer energy from a smaller clock-sink count.

`tools/report_repair_area.py` now emits all ledger columns together, validates
the exact accepted repair receipt, reconciles every native adapter leaf and
freezes its inputs. Category/overlap and wrong/missing-leaf controls live in
`tools/test_report_repair_area.py`. The 11b1 reports are
`build/area-ledger/11b1-bd.json` and `11b1-click.json`, from
`build/control-frame-borrow/completion-final-map-bd` and
`build/control-frame-borrow/completion-map-click` respectively.

The reports use `RISCAY_PHYSICAL_TOOLS=build/control-join-tools.json`, matching
the original mapping receipts. An initial BD attempt with the wrong runtime
configuration failed `REPAIR_INPUT_INVENTORY`; its log remains beside the
successful retry. No validation was relaxed.

## Isolated pilots

These rows are measured changes to one component of the 11b1 repaired graph.
They are not production adoption or fresh global repair results, and are not
subtracted from the accepted totals above.

| Item | Component change | Guard / allowance / DLYD area delta, mm² | Clock sink delta | Evidence |
| --- | --- | ---: | ---: | --- |
| A7b | BD elapsed request chain: 86 → 25 DLYD cells | −0.004552845 / 0 / −0.004552845 | 0 | [Ten corner/slew cases and four exact controls](reviews/a7b-elapsed-guard.md) |

A7b's minimum setup margin under 15% two-sided sensitivity is +4.579 ns;
that sensitivity is not a qualified mismatch bound. Hold and ACK timing are
unchanged. Complete source launch, return/reset/pulse envelopes, electrical
closure and extracted RC remain open. No production guard is shortened.

## In progress

| Item | Scope | Acceptance still required |
| --- | --- | --- |
| A7b | Independently reviewed isolated BD elapsed request guard candidate above | Complete launch/return/reset and routed qualification before production shortening |
| A8b | RAM prepare standard-stage passive allowance, BD and Click | Matching model semantics, reset/reuse controls, max/min capture and ACK checks, exact graph delta and review |
| 11b2 + 11b3 | Borrow Housekeeping ordered payload and Telemetry commit fields | Focused ownership/reset/stall faults, shared regressions, strict exports, matched map/activity and review |

Replace these rows with measured pilot/batch evidence when complete. Keep
experimental component deltas separate from the accepted production totals.
