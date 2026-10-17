# Area ledger

This is the running item/batch ledger from the 11b1 baseline. Use the same
Groundlark low-power profile, three GF180 SRAM macros, pinned standard-cell
libraries, mapper and accepted repair flow for matched production comparisons.
Full routed physical requalification remains migration item 17.

The next milestone is **BD mapped logic below 2.3 mm² excluding SRAM**. Starting
from 2.825888 mm², that required **0.525888 mm² (18.61%)** reduction. The measured
11b2/11b3 batch is 2.792933 mm², leaving **0.492933 mm² (17.65%)** of its area
to remove. The batch is digitally verified; the milestone is unmet.
A7b/A8b are isolated experiments; their local deltas
do not count toward it until adopted and measured on the production design.

## Accepted production batches

Every area entry is mm² and every pair is **BD / Click**. Mapped means before
electrical repair; repaired means accepted pre-placement repair, not P&R.

| Item / source | Mapped logic | Repaired logic | Guards | Allowances | DLYD | Periodic clock sinks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 11b1 (`c195deb`, merged `29e0ea7`) | 2.825888 / 3.585890 | 3.014986 / 3.795762 | 0.542153 / 1.061831 | 0.413624 / 0.366484 | 0.536041 / 1.052901 | 5,072 / 5,127 |
| 11b2 + 11b3 | 2.792933 / 3.554119 | 2.978974 / 3.757950 | 0.542153 / 1.061831 | 0.413624 / 0.366484 | 0.536041 / 1.052901 | 4,810 / 4,865 |

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
| A8b | One 101-bit RAM prepare allowance per variant, BD and Click | 0 / −0.003384998 each / 0 | 0 | [Passive model and physical comparison](reviews/a8b-passive-stage.md) |

A7b's minimum setup margin under 15% two-sided sensitivity is +4.579 ns;
that sensitivity is not a qualified mismatch bound. Hold and ACK timing are
unchanged. Complete source launch, return/reset/pulse envelopes, electrical
closure and extracted RC remain open. No production guard is shortened.

A8b also removes one 0.000013171 mm² reset-repair buffer per variant, for a total
local repaired-graph delta of **−0.003398170 mm² each**. It needs no local hold
repair under the tested zero-wire conditions. This is a proposed new passive
model's behavior; the existing library primitive and production mapper retain
their reset semantics. Full launch/reset/electrical/routed qualification and
production adoption remain open.

## In progress

| Item | Scope | Acceptance still required |
| --- | --- | --- |
| A7b | Independently reviewed isolated BD elapsed request guard candidate above | Complete launch/return/reset and routed qualification before production shortening |
| A8b | Independently reviewed RAM prepare passive-allowance candidates above | Supported library API, fanout isolation audit and physical qualification before adoption |

## Accepted ownership batch: 11b2 + 11b3

The combined batch passes 319 Scala cases, all four strict SoC exports, exact
fault controls and fresh independent review. Accepted electrical repair and
matched area/activity comparisons pass. It removes 262 work-clock flip-flops per variant without changing native
storage or other clock domains. Mapped logic falls 1.166% / 0.886%; repaired
logic falls 1.194% / 0.996%. Guards and allowances remain 34.22% / 40.19% of
mapped logic. All 27 native-model wakes per variant are unchanged. Independent
review reproduced the area, activity and clock counts; see the
[batch evidence](reviews/service-command-borrow.md). Its final reports are
`build/command-borrow/area-bd-r3.json`, `area-click-r3.json`, `cost-r3.json` and
`activity-r3.json`. Full physical qualification remains at item 17.
Keep isolated pilot deltas separate.
