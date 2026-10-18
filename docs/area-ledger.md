# Area ledger

This is the running item/batch ledger from the 11b1 baseline. Use the same
reference capacities and low-power configuration, three GF180 SRAM macros, pinned standard-cell
libraries, mapper and accepted repair flow for matched production comparisons.
Full routed physical requalification remains migration item 17.

The **BD mapped-logic milestone below 2.3 mm² excluding SRAM is achieved**.
The latest generic-MCU batch maps to **2.100657 / 2.894444 mm²** and repairs to
**2.283901 / 3.099576 mm²**. Its immediate parent, the passive/guard/fusion batch,
maps to 2.229395 / 3.048424 mm². These are fresh whole-chip results, not summed
pilot savings. Mapped/repaired numbers exclude the P&R additions tabulated below.
Generic boot introduces new ROM/decode timing
obligations; the parent's local timing passes do not qualify those paths.

BD is now the tape-out target; Click is a frozen functional reference. Allocate
**0.05 mm² of additional standard-cell area for routed hold repair** in the BD
planning budget (about 2.4% of current mapped logic). This is an allowance, not
inserted area or a predicted requirement, and is separate from electrical/CTS
repair and placement whitespace. Record actual cell use after routing. If repair
exceeds it, revise the budget or architecture; do not waive a failing path. The
[repair contract](architecture-followups.md#routed-hold-repair) specifies the gates.

## Accepted production batches

### BD rectangular P&R

The current generic-MCU BD mapping has completed detailed routing on a
**1.94 × 2.53 mm** outline (4.9082 mm²), with **one unresolved Metal2 short**.
Nominal/minimum/maximum wire RC extraction is complete. **Physical timing remains
unqualified.** The larger comparison run completed with zero detailed-router DRC
violations.

| Source / physical run | Mapped logic | Pre-placement repaired logic | Routed logic | SRAM | Taps/endcaps | Total cell footprints | Periodic sinks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baec57b`, `pnr-bd-1940x2530-r1` (BD only, one router short) | 2.100657 | 2.283901 | 2.901978 | 0.466241 | 0.125372 | 3.493590 | 4,125 |
| `517c272`, `pnr-bd-3930x2530-r1` (BD only) | 2.100657 | 2.283901 | 2.895688 | 0.466241 | 0.266857 | 3.628786 | 4,125 |

All areas are mm². Routed logic includes the added ties, electrical repair and
CTS. On the smaller outline, placement repair adds 0.404505 mm², CTS 0.050450 mm²
and global-route repair 0.149238 mm². Total cell footprints fall 0.135196 mm²
relative to the larger outline because there are fewer taps/endcaps; logic grows
0.006289 mm². Guard, allowance and DLYD inventories are unchanged from the
generic-MCU row below. No RTL, physical timing recipe or wake workload changes.
The 0.05 mm² targeted hold-repair reserve remains separate and unspent. This is
a new physical implementation, not a matched architecture-area comparison with
the original baseline. [Smaller-outline run details](gf180-bd-1940x2530-pnr.md);
the [larger run](gf180-bd-rectangular-pnr.md) remains a historical comparison.

### Mapped batch history

Every area entry is mm² and every pair is **BD / Click**. Mapped means before
electrical repair; repaired means accepted pre-placement repair, not P&R.

| Item / source | Mapped logic | Repaired logic | Guards | Allowances | DLYD | Periodic clock sinks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 11b1 (`c195deb`, merged `29e0ea7`) | 2.825888 / 3.585890 | 3.014986 / 3.795762 | 0.542153 / 1.061831 | 0.413624 / 0.366484 | 0.536041 / 1.052901 | 5,072 / 5,127 |
| 11b2 + 11b3 | 2.792933 / 3.554119 | 2.978974 / 3.757950 | 0.542153 / 1.061831 | 0.413624 / 0.366484 | 0.536041 / 1.052901 | 4,810 / 4,865 |
| A7b + A8b + A10 SRAM fusion | 2.229395 / 3.048424 | 2.412382 / 3.252393 | 0.404567 / 0.942852 | 0 / 0 | 0.398561 / 0.934080 | 4,810 / 4,865 |

11b1 removes 268 periodic flip-flops per variant. Its complete contract, matched
parent comparison, wake activity and listed-state leakage bounds remain in the
[review evidence](reviews/control-frame-borrow.md). This ledger starts from that
accepted graph; it does not replace historical evidence with newly generated
receipts. The earlier PR10 maps fail current receipt validation with
`REPAIR_INPUT_CHANGED`; those failures are retained under `build/area-ledger/`.

## Counting rules and evidence

### Generic MCU correction (digital and structural verification complete)

The generic SPI ROM and removal of fixed application supervision have completed
matched mapping and graph-preserving electrical repair on the final arbitration
graph. Affected RTL regressions, four generation audits, both production RDC
proofs and independent review pass. Physical timing qualification remains open.

| Batch | Mapped logic | Repaired logic | Guards | Allowances | DLYD | Periodic clock sinks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Generic SPI boot / supervisor removal | 2.100657 / 2.894444 | 2.283901 / 3.099576 | 0.398209 / 0.927310 | 0 / 0 | 0.392440 / 0.918854 | 4,125 / 4,179 |

Against `90ce9f7`, mapped logic falls by 0.128738 / 0.153980 mm²
(5.77% / 5.05%); repaired logic falls by 0.128481 / 0.152817 mm².
Periodic sinks fall by 685 / 686. These are net changes: removed supervisor
owners/transport and redundant housekeeping state, plus the 2,096-byte ROM,
loader ingress/status and generic SPI claim/arbitration. They are not an
isolated ROM or supervisor area estimate. SRAM footprints are unchanged.

Reports: `build/generic-mcu-r10/area-bd.json` and `area-click.json`;
accepted graph proofs are under the matching `map-*/electrical-repair/`.
Earlier R2 reports predate the final arbitration and are superseded here.
The initial repair failed on an added orphan tie. Applying the existing strict
orphan-tie cleanup before the initial graph comparison removes only the unused
tie on padded GPIO input lanes; all original/protected cells remain intact.
Raw, pruned and failed inputs are retained. Full physical qualification is open.

| DLYD purpose | BD cells / mm² | Click cells / mm² |
| --- | ---: | ---: |
| Custom ordering and reset | 3,533 / 0.263692 | 8,956 / 0.668447 |
| Bundling / request and pulse | 937 / 0.069935 | 835 / 0.062322 |
| Seed reset admission | 100 / 0.007464 | 0 / 0 |
| Publication / output and pulse | 688 / 0.051350 | 1,960 / 0.146288 |
| ACK and pulse | 0 / 0 | 560 / 0.041797 |

The exact purpose names and input hashes are in the reports. These DLYD costs
overlap guards; they are not additional area. No guard was shortened in this batch.

### Counting conventions

- Logic excludes all three SRAM macro footprints (0.466240659 mm² LEF total).
  Do not mix LEF footprints with the macros' different Liberty area values.
- Guards are the exact native matched-control adapters with model delay above
  1 ns. This accounting convention does not classify shortening eligibility.
  The current separate 1 ns functional-adapter costs are 0.041094 / 0.053308 mm².
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
closure and extracted RC remain open. This historical pilot did not shorten a
production guard.

A8b also removes one 0.000013171 mm² reset-repair buffer per variant, for a total
local repaired-graph delta of **−0.003398170 mm² each**. It needs no local hold
repair under the tested zero-wire conditions. This is a proposed new passive
model's behavior at the pilot revision. The supported opt-in library primitive
and production adoption are now tracked in the combined batch below; this
historical delta is not a whole-chip measurement.

## Adopted local scopes

| Item | Scope | Local evidence |
| --- | --- | --- |
| A7b | 199 baseline BD ordering guards reconciled: 4 fused away, 90 publication + 1 elapsed request changed, 89 request + 15 custom retained; 73 live Click ACK guards changed | 1,630 corner/slew cases, physical/digital controls and independent review; full source/routed qualification remains item 17 |
| A8b | Supported source-pinned passive primitive; complete parent 110 BD /124 Click and final 108 BD /122 Click instance audits | Four strict exports, exact capture/constant bindings, local setup/hold screens and matched mapping/repair |
| A10 first fusion | Remove both 101-bit SRAM prepare stages per variant | Full-capacity word/byte/reset regressions; 80 composed timing cases, 10 physical controls and exact Click hold/rearm binding |

The selected guard policy is a 20% two-sided engineering derate plus 2 ns
residual margin, not foundry-qualified mismatch data. The former 25-cell elapsed
pilot does not meet that floor; the adopted elapsed request uses 28 cells.
Local acceptance permits reversible parameter adoption now. Item 17 is not a
blanket adoption gate, and later extracted evidence can require lengthening.
See [the sizing contract](gf180-guard-sizing.md).

The final passive inventory is 108 BD /122 Click instances: A10 separately
removes two 101-bit stages per variant. Do not count those two removed allowances
again as passive-adoption savings. DLYD-by-purpose counts accompany the
fresh whole-chip ledger row below; DLYD area remains a subset of guard area.

### Combined batch measurements

These are fresh whole-chip mappings and accepted structural electrical repairs,
not estimates obtained by adding isolated pilot savings. Relative to 11b2/11b3,
mapped logic falls 20.177% / 14.228% and repaired logic 19.020% / 13.453%.
The exact reports are `build/area-adoption/area-{bd,click}-r3.json` and
`cost-r3.json`. The source is pinned in those receipts; no new P&R area is claimed.
Repair adds 0.182987 / 0.203969 mm². The retained native payload/capture inventory
falls by 202 / 204 cells; periodic storage and clock-input capacitance are unchanged.

| DLYD purpose | Parent BD / Click cells | Current BD / Click cells | Current BD / Click area, mm² |
| --- | ---: | ---: | ---: |
| Request bundling | 1,055 / 885 | 977 / 865 | 0.072920 / 0.064561 |
| Publication | 2,484 / 2,100 | 720 / 2,044 | 0.053738 / 0.152558 |
| Click ACK | 0 / 2,100 | 0 / 584 | 0 / 0.043588 |
| Custom ordering/reset | 3,533 / 9,022 | 3,533 / 9,022 | 0.263692 / 0.673373 |
| Seed reset/admission | 110 / 0 | 110 / 0 | 0.008210 / 0 |
| **Total** | **7,182 / 14,107** | **5,340 / 12,515** | **0.398561 / 0.934080** |

Normal native-model activity reproduces all 27 parent wake windows per variant.
The 43-instruction firmware wake remains 3,257 BD / 3,212 Click work-clock edges.
Physical chain counts and digital model delays are distinct: unchanged modeled
edges do not measure physical guard energy or silicon wake time. TT independent
listed-state leakage bounds are recorded with the cost report; they are not a
measurement of reachable deep-sleep power.
The current TT bounds are 6.43–8.39 µW BD / 8.10–10.87 µW Click, versus
7.87–10.07 / 9.39–12.38 µW for the matched parent. These include the same three
SRAM macros and omit analog-block power, LF switching and a reachable sleep-state
analysis; they are not a replacement for that eventual measurement.
The complete batch passes 808 distinct Scala cases, 1,198 Python controls and
four strict exports, with fresh independent review. The one original host
timeout, its unchanged executable replay and exact affected-test rerun remain
in [the batch evidence](reviews/native-area-adoption.md). No simulated deadline
or functional assertion was relaxed.

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
