# Area ledger

This is the running item/batch ledger from the 11b1 baseline. Use the same
reference capacities and low-power configuration, three GF180 SRAM macros, pinned standard-cell
libraries, mapper and accepted repair flow for matched production comparisons.
Full routed physical requalification remains migration item 17.

The **BD mapped-logic milestone below 2.3 mm² excluding SRAM is achieved**.
The Housekeeping batch maps to **1.987975 / 2.800265 mm²**
(BD / Click) and repairs to **2.209548 / 3.051047 mm²**, including the expanded
A/B boot ROM and current parent-driver recipe. The matched parent and
single-writer Telemetry results are recorded in their batch rows below.
The earlier passive/guard/fusion batch mapped to
2.229395 / 3.048424 mm² (BD / Click). These are fresh whole-chip results, not summed
pilot savings. Mapped/repaired numbers exclude the P&R additions tabulated below.
Generic boot introduces new ROM/decode timing
obligations; the parent's local timing passes do not qualify those paths.

BD is the tape-out target; Click physical timing/sizing work is frozen, while
architecture conversions now cover both native implementations. Allocate
**0.05 mm² of additional standard-cell area for routed hold repair** in the BD
planning budget (about 2.5% of current mapped logic). This is an allowance, not
inserted area or a predicted requirement, and is separate from electrical/CTS
repair and placement whitespace. Record actual cell use after routing. If repair
exceeds it, revise the budget or architecture; do not waive a failing path. The
[repair contract](architecture-followups.md#routed-hold-repair) specifies the gates.

## Accepted production batches

### Single-writer Housekeeping view

Services reads the qualified retained native Housekeeping bank. The state mirror
and unused elapsed-age command lanes are removed in both variants. BD replaces
its wide feedback FIFO/Join storage with one closed bank and a one-bit credit;
Click retains its native phase buffer. The 32-bit receiving-edge consumed-time
acknowledgement remains because it feeds asynchronous oscillator-wake logic.
Command arbitration, event cutoff, the host snapshot bank and the ABI are unchanged.

| Variant | Parent mapped / repaired logic | Current mapped / repaired logic | Delta mapped / repaired | Periodic sinks before → after |
| --- | ---: | ---: | ---: | ---: |
| BD | 2.048618 / 2.274043 | 1.987975 / 2.209548 | −0.060642 / −0.064495 | 3,515 → 3,223 |
| Click | 2.848272 / 3.098062 | 2.800265 / 3.051047 | −0.048007 / −0.047015 | 3,572 → 3,282 |

Areas are mm² excluding unchanged SRAM, with the same mapper, PDK and repair
recipe. Services loses **292 work sinks in each variant**, leaving **915 work +
14 service**. Click adds two work-clock qualification synchronizers outside
Services, so its total reduction is 290. Whole-chip service/work/LF totals are
**1,203/1,942/78 BD** and **1,207/1,997/78 Click**. The separate SDA event remains.
The reports retain the per-register Services inventory for item 16.

This matched comparison reruns both the immediate parent and candidate with the
new ordinary hierarchy parent-driver repair. Two high-fanout child outputs gain
exclusive repairable buffers; complete graph and driver proofs pass. The former
I²C readStart child's 251-load capacitance violation is removed. A broad 447-net
fanout experiment failed to fix that hierarchy boundary and is not adopted.

BD guards/DLYD change from 0.399605/0.393784 to **0.400304/0.394455 mm²**:
the new bank-feedback guard adds nine DLYD cells. Click remains
**0.937320/0.928706 mm²**. Allowances remain zero. These are subsets of mapped
logic, not additional area; the 0.05 mm² routed hold reserve remains separate.

| DLYD purpose | BD cells / mm² | Click cells / mm² |
| --- | ---: | ---: |
| Request bundling | 937 / 0.069935 | 855 / 0.063814 |
| Publication/output guard | 688 / 0.051350 | 2,016 / 0.150468 |
| ACK guard | 0 / 0 | 616 / 0.045976 |
| Custom ordering/reset | 3,560 / 0.265707 | 8,956 / 0.668447 |
| Seed reset/admission | 100 / 0.007464 | 0 / 0 |
| **Total** | **5,285 / 0.394455** | **12,443 / 0.928706** |

Safe full-return qualification has a measurable digital activity cost:

| Wake | BD work edges, parent → current | Click work edges, parent → current | Current duration BD / Click, µs |
| --- | ---: | ---: | ---: |
| Maintenance | 24 → 30 | 18 → 27 | 3.147 / 3.064 |
| Sample | 217 → 221 | 214 → 216 | 18.772 / 18.356 |
| 43-instruction firmware | 3,241 → 3,242 | 3,197 → 3,199 | 270.524 / 266.941 |

All 22 maintenance, three sample and two firmware observations per variant agree
within their respective categories. Maintenance oscillator-on duration is unchanged;
sample duration grows by 0.333/0.167 µs and firmware by 0.083/0.167 µs. Telemetry
commands remain zero. These are native digital-model windows, not measured power
or physical delay. Fewer sinks alone does not establish an energy win.

Evidence is under `build/housekeeping-view/`: `map-bd-r2`, `map-click-r1`,
`{baseline,candidate}-{bd,click}-repair-r4`, `*-area-r4.json`, `*-sinks-r4.json`,
`activity-r1.json`, `focused-complete-r3`, `extended-r1`, `atomic-r3`, `ci-r2`,
`python-final-r6`, `check-r1` and both RDC logs. The 59 focused cases, 33 extended
cases and four final atomic-snapshot controls pass. The fast Scala gate passes
197 cases; the final Python gate passes 381 tests without skips.
All four exports and both reset-crossing proofs pass. The first mapping's missing
new-guard classification, the original borrowed-command monitor declaration error
and the selector-correlation proof failure are retained, not counted as passes.
No functional deadline or oracle was weakened. Independent review found and
closed the reader-proof, timing-composition and shared-wrapper repair issues.

The final BD bank campaign (`timing-bank-r6`) passes all ten PVT/slew cases:
920 periodic bank-reader endpoints have minimum **+192.568 ns setup / +1.247 ns
hold**, with **+11.105 ns** bank-to-feedback ordering through the nine-cell
guard. The 17 qualification sources reach 1,074 periodic targets; all source/
launch-polarity combinations are checked with one-period setup and same-edge
hold, yielding **+0.834 / +0.482 ns** minima. The 263 native frontier endpoints
are explicitly inventoried, not counted as qualified periodic readers.
The ten canonical update-stage cases (`timing-update-r4`) also pass locally:
minimum data-lag budget **+9.929 ns**, zero-reuse hold **+1.187 ns**, and ACK
after capture **+1.381 ns**. These are repaired, zero-wire-RC bounds with no CTS
skew. Native bank-to-update launch composition, routed min/max RC, reset/noise,
mismatch justification and whole-chip electrical closure remain open.

The failed pre-parent-driver and global-CLK-to-Q envelopes remain in
`timing-bank-r2/r3`. `timing-bank-r4` caught sink-edge ranking by slack rather
than propagation; the final query neutralizes only that selection cost and
reapplies the unchanged Liberty apertures afterward. Every assigned zero cost
is read back, every source/polarity pair is required, and reversed bounds still
fail. Superseded `r5` retains a changed-tool receipt failure; only `r6` is accepted.

All four full-capacity primary/golden boot cases pass again in `full-boot-r1.log`;
`full-boot-r1.json` and `full-boot-r1-reports` retain their records. BD primary/
fallback take **353.740 / 1,010.872 ms**, Click **398.812 / 1,139.618 ms** at the
10 MHz digital-model service clock. Relative to the boot batch, the extra reader
qualification costs 0.1/3.9 µs BD and 6.4/10.0 µs Click. ROM remains 4,224 bytes;
the image, CRC, lock, golden fallback and factory provisioning protocols are
unchanged. See [boot activity](boot-slots.md#full-capacity-boot-activity).

### Bounded time coordinate

The conservative upper-time coordinate and sample timestamps are 43 bits,
with terminal saturation and saturated 32-bit age. This covers at least 116 wall
years under the GF180 5–12 Hz envelope; 41 bits would cover only 29. Nominal MMIO
time, deadlines, sequence and retention behavior are unchanged.

| Variant | Parent mapped / repaired logic | Narrowed mapped / repaired logic | Delta mapped / repaired | Periodic sinks before → after |
| --- | ---: | ---: | ---: | ---: |
| BD | 2.064823 / 2.291139 | 2.048618 / 2.273786 | −0.016205 / −0.017353 | 3,557 → 3,515 |
| Click | 2.869313 / 3.120468 | 2.848272 / 3.097721 | −0.021041 / −0.022747 | 3,614 → 3,572 |

Areas are mm², excluding unchanged SRAM. Both comparisons use the same mapper,
PDK and current parent-driver/receiver-isolator recipe. Services loses 21 work
sinks (1,228 → **1,207**); ADC admission loses another 21. Services service sinks
remain 14. Whole-chip service/work/LF totals are **1,203/2,234/78 BD** and
**1,207/2,287/78 Click**. BD guards/DLYD remain 0.399605/0.393784 mm² (5,276 cells);
Click remains 0.937320/0.928706 mm² (12,443). Allowances remain zero; DLYD purposes
and the separate 0.05 mm² routed hold reserve are unchanged.

Native-model activity is unchanged in the retained 43-instruction workload:
maintenance/sample/firmware work edges remain **24/217/3,241 BD**, **18/214/3,197
Click**, with windows **3.147/18.439/270.441 µs BD** and **3.064/18.189/266.774 µs
Click**. Telemetry commands remain zero in these windows. This fixture bypasses
normal boot; the separate full-capacity boot measurements below remain the boot
evidence, not these short wakes. These are digital activity measurements, not
power estimates or physical timing.

Evidence: `build/time-width/{baseline,candidate}-{bd,click}-{area,sinks}-r1.json`,
`summary-r1.json`, `activity-*-r1.log`, `ci-r1/receipt.json`, `python-r2/receipt.json`,
`focused-r1.log`, `extended-r1.log`, `check-r1/` and the two RDC logs. All 66 focused
and 35 extended tests, 372 Python/197 Scala fast tests, four exports and both RDC
checks pass. Independent source/evidence review is complete. The narrowed
production ADC/time local screen passes ten cases in `timing-adc-r2`: one-period
setup/hold minima **+6.312/+0.405 ns**, bank-reader **+210.489/+1.364 ns**, feedback
after bank **+11.311 ns**. Routed RC/skew and source-launch composition remain
open. The absent software-sample bank deliberately fails inventory in
`timing-software-r2`; no physical coverage is claimed for that optional profile.
The initial `LEAF_BUFFER_SHAPE` failure is retained: the checker now accepts
proof-approved combinational `clkbuf` as well as `buf`, with scalar I→Z pins;
their real delays remain in STA. Its existing positive/negative controls pass.

### A/B external boot slots

The ROM grows from 2,096 to **4,224 bytes**, with a statically bounded 188-byte
stack. Both fresh maps use the same mapper, PDK, capacities and parent-driver
recipe from `34d14e6`, before the five receiver isolators; the mapped/repaired
comparison below isolates the boot change.
The host synthesis timeout was increased from 600 to 3,600 seconds because the
old mapper's ROM technology mapping exceeded it. No circuit constraint changed;
the original timeout logs remain. Mapping and complete graph proofs pass.

| Variant | Parent mapped / repaired logic | A/B mapped / repaired logic | Delta mapped / repaired | Periodic sinks before → after |
| --- | ---: | ---: | ---: | ---: |
| BD | 2.010204 / 2.234365 | 2.064823 / 2.291051 | +0.054619 / +0.056687 | 3,557 → 3,557 |
| Click | 2.815021 / 3.064001 | 2.869313 / 3.120468 | +0.054292 / +0.056467 | 3,614 → 3,614 |

Areas are mm², excluding the unchanged 0.466241 mm² SRAM. The matched Click
parent reruns the current repair recipe on the previous RTL; it is not the older
3.032252 mm² repair in the Telemetry row. Evidence is under `build/generic-boot/`:
`slots-baseline-click-r1`, `slots-map-{bd,click}-r3`,
`slots-area-{bd,click}-r3.json` and `slots-sinks-{bd,click}-r3.json`.
BD's parent is `build/native-physical/map-bd-r4`.

Services remains 1,228 work + 14 service sinks in each variant. Whole-chip
service/work/LF totals remain 1,203/2,276/78 BD and 1,207/2,329/78 Click.
BD guards/DLYD remain 0.399605 / 0.393784 mm² (5,276 DLYD cells); Click remains
0.937320 / 0.928706 mm² (12,443 DLYD cells). Allowances remain zero and every
DLYD remains assigned to its existing purpose. The boot ROM is combinational;
no periodic or native storage, synchronizer or clock was added. Full-capacity
2 KiB primary boot takes 353.740 / 398.806 ms and 3,537,379 / 3,988,038 work
edges (BD / Click). With both field bodies corrupt, golden fallback takes
1,010.868 / 1,139.608 ms and 10,108,660 / 11,396,064 work edges. These are native
digital-model results at 10 MHz service clock; see the [boot table](boot-slots.md#full-capacity-boot-activity).
All 69 extended boot cases and the 372-Python/197-Scala fast gate pass; both RDC
proofs, all four export audits and independent final review pass. The older
README layout does not include the expanded ROM, whose paths need fresh timing.

### Compact native placement and parent drivers (electrical closure open)

The unchanged BD RTL maps to 2.010204 mm². The new parent-driver recipe passes
the complete graph/protected-cell proof and repairs to **2.234365 mm²**, versus
2.199751 mm² for the immediate parent: **+0.034614 mm² (+1.57%)** before placement.
The 9,916 exclusive native-output parents account for 0.174720 mm². Removing the
optional speculative early-sizing pass avoids enlarging every parent and removes
unnecessary ordinary buffers; actual electrical-violation repair remains enabled.
This is not an electrical or routed timing pass.

| Recipe / evidence | Mapped logic | Repaired logic | Native-output parent area | Periodic sinks |
| --- | ---: | ---: | ---: | ---: |
| Immediate parent, `single-writer-telemetry/map-bd-r7` | 2.010204 | 2.199751 | — | 3,557 |
| Trial with blanket early sizing, `native-physical/map-bd-r2` | 2.010204 | 2.743221 | 0.565958 | 3,557 |
| Violation-driven repair, `native-physical/map-bd-r4` | 2.010204 | 2.234365 | 0.174720 | 3,557 |
| Five measured receiver isolators, `native-physical/map-bd-input-r1` | 2.010204 | 2.234452 | 0.174720 | 3,557 |

The receiver-isolation trial adds five `buf_2` cells, **0.000088 mm²**, outside
unchanged native boundaries. Its complete graph and exclusive receiver audits
pass; the fresh reroute passes zero router violations and all compactness
checks. Extracted native-output capacitance passes; slew closure remains open. Evidence is
`build/native-physical/area-bd-input-r1.json` and `input-locks-r1.json`.

Areas are mm², excluding SRAM. The r4 report is
`build/native-physical/area-r4.json`. Guards remain 0.399605 mm², allowances zero,
and DLYD remains 5,276 cells / 0.393784 mm² with the same purpose inventory.
Service/work/LF sinks remain 1,203 / 2,276 / 78; Services retains 1,228 work and
14 service sinks. RTL/native-model wake activity is unchanged. Physical latency
and energy must be remeasured after routing. Click is unchanged. The 0.05 mm²
hold-repair reserve is separate and remains unspent. No smaller die or README
render is accepted until its new native geometry checks and zero-router-DRC gate pass.

The fixed-tool 2.25, 2.30 and 2.35 × 2.53 mm runs pass those routing gates and
complete nominal/minimum/maximum RC extraction. The smallest tested successful
candidate replaces the README render; smaller 1.94/2.05/2.20 mm runs remain
failed evidence. These are routing results, not physical qualification.

| Run under `build/native-physical/` | Routed logic | SRAM | Taps/endcaps | Total footprints | Core occupancy |
| --- | ---: | ---: | ---: | ---: | ---: |
| `pnr-2250x2530-d50-r1` | 2.858175 | 0.466241 | 0.145371 | **3.469786** | 64.27% |
| `pnr-2350x2530-d50-r3` | 2.875229 | 0.466241 | 0.152645 | **3.494115** | 61.90% |
| `pnr-input-2350x2530-d50-r2` | 2.874162 | 0.466241 | 0.152645 | **3.493048** | 61.88% |

The first two runs use the r4 map; the last uses `map-bd-input-r1` with five
receiver isolators. All predate A/B boot ROM expansion. The renders
and congestion inventories are in `render-2250-r1` / `routability-2250-r1` and
`render-2350-r3` / `routability-2350-r3`. The 2.35 mm min/max-RC audits resolve
all 10,609 adapter outputs with zero capacitance violations at all five PVT
corners. Whole-chip electrical closure remains open: slow/hot max-RC still has
10,649 slew violation rows, worst 28.087 ns, and several ordinary-driver
capacitance failures in the parent. The receiver-isolation reroute also passes
all 10,609 native output cap limits, but retains 10,832 slow/hot max-RC slew
rows with worst 12.626 ns. Worst slew improves while the row count increases.
Its footprint falls by 0.001067 mm²; this small difference includes placement
and electrical repair, not merely the five added cells. The new congestion
inventory is `routability-input-2350-r2`; full electrical tables and limitations
are in [the routing report](gf180-routability.md#extracted-electrical-results-and-remaining-receiver-locks).
These measurements must not be treated as timing closure.

### BD routing and signal-integrity investigation

The retained `ed38c62` BD map completed detailed routing on **2.53 × 2.53 mm**
with zero router violations, an empty retained DRC report and independent
nominal/minimum/maximum RC extraction. Cell occupancy is **55.80%** of the core.
Electrical limits and physical timing remain unqualified; routing acceptance
does not waive them. [Maps, limits and evidence](gf180-routability.md).

| Physical run | Mapped logic | Pre-placement repaired logic | Routed logic | SRAM | Taps/endcaps | Total cell footprints | Periodic sinks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `pnr-bd-routability-2530x2530-r7` | 2.010204 | 2.199751 | 2.767025 | 0.466241 | 0.164802 | 3.398069 | 3,557 |

Areas are mm². This batch changes floorplanning, routing and analysis, not RTL:
guards remain 0.399605 mm², allowances zero, DLYD 5,276 cells / 0.393784 mm²,
and periodic sinks remain service 1,203 / work 2,276 / LF 78. Native-model wake
activity is unchanged; no new silicon energy claim is made. The 0.05 mm² routed
hold-repair reserve remains unspent. The same current map on 1.94 × 2.53 mm
failed to converge to zero violations in late routing passes despite lower SRAM
band density; its evidence is retained. This is not an isolated comparison with
the older RTL in the rectangular-layout table below.

### BD rectangular P&R

The earlier generic-MCU BD snapshot (`baec57b`) completed detailed routing on a
**1.94 × 2.53 mm** outline (4.9082 mm²), with **one unresolved Metal2 short**.
Nominal/minimum/maximum wire RC extraction is complete. This snapshot predates the
ownership batches below. **Physical timing remains unqualified.** The larger comparison run completed with zero detailed-router DRC
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
| Clocked events + both retained register views | 2.053129 / 2.854875 | 2.237991 / 3.063397 | 0.398907 / 0.932315 | 0 / 0 | 0.393112 / 0.923780 | 3,896 / 3,952 |
| Single-writer Telemetry samples | 2.010204 / 2.815021 | 2.199751 / 3.032252 | 0.399605 / 0.937320 | 0 / 0 | 0.393784 / 0.928706 | 3,557 / 3,614 |

11b1 removes 268 periodic flip-flops per variant. Its complete contract, matched
parent comparison, wake activity and listed-state leakage bounds remain in the
[review evidence](reviews/control-frame-borrow.md). This ledger starts from that
accepted graph; it does not replace historical evidence with newly generated
receipts. The earlier PR10 maps fail current receipt validation with
`REPAIR_INPUT_CHANGED`; those failures are retained under `build/area-ledger/`.

### Single-writer Telemetry samples

The ADC owns its retained sample bank; CPU software samples have their own bank,
separate from application/GPIO state. A shared POR upper-time coordinate replaces
per-sample clocked age/capture/commit projections. Time and ADC publication no
longer produce Telemetry commands. CPU/recovery command ordering and the event
cutoff remain at their documented clocked boundaries. No periodic stage is added
inside a native owner. The [contract and ranked inventory](single-writer-telemetry.md)
record the independent implementations and remaining arbitration.

| Metric | BD parent → current | Click parent → current |
| --- | ---: | ---: |
| Mapped logic, mm² | 2.053129 → 2.010204 (−2.09%) | 2.854875 → 2.815021 (−1.40%) |
| Repaired logic, mm² | 2.237991 → 2.199751 | 3.063397 → 3.032252 |
| Guards, mm² | 0.398907 → 0.399605 | 0.932315 → 0.937320 |
| Allowances, mm² | 0 → 0 | 0 → 0 |
| DLYD, mm² | 0.393112 → 0.393784 | 0.923780 → 0.928706 |
| Periodic sinks | 3,896 → 3,557 (−339) | 3,952 → 3,614 (−338) |
| Whole-chip service / work / LF | 1,203 / 2,615 / 78 → 1,203 / 2,276 / 78 | 1,207 / 2,667 / 78 → 1,207 / 2,329 / 78 |
| Services service / work / LF | 14 / 1,468 / 0 → 14 / 1,228 / 0 | 14 / 1,468 / 0 → 14 / 1,228 / 0 |

The per-register report partitions every physical sink once, using complete Q
alias sets; unnamed registers remain visible. Removed Services families total
310 sinks; the 64-bit time coordinate and six retained application-index bits
make the net reduction 240. Full reports are `bd-baseline-registers.json`,
`click-baseline-registers.json`, `bd-registers-r7.json` and `click-registers-r7.json`
under `build/single-writer-telemetry/`. Work includes the three macro clock pins;
the unchanged asynchronous SDA event is excluded from periodic totals.

| Current DLYD purpose | BD cells / mm² | Click cells / mm² |
| --- | ---: | ---: |
| Custom ordering/reset | 3,551 / 0.265035 | 8,956 / 0.668447 |
| Bundling / Click request-pulse | 937 / 0.069935 | 855 / 0.063814 |
| Publication / Click output-pulse | 688 / 0.051350 | 2,016 / 0.150468 |
| Seed/reset admission | 100 / 0.007464 | — |
| Click ACK-pulse | — | 616 / 0.045976 |
| Total | 5,276 / 0.393784 | 12,443 / 0.928706 |

The timestamp nibble hierarchy costs about 0.0102 / 0.0112 mm² above the
rejected flattened arithmetic. Preserving its group-prefix levels adds another
0.002393 / 0.005293 mm², preventing serial carry reconstruction without adding
clock sinks. Guard area grows for the new retained ADC bank's completion/feedback contract.
Click uses its existing pulse/ACK policy; no Click sizing or timing campaign ran.
Matched logic is still about 3.49× / 4.74× the original 0.576 / 0.594 mm²
mostly-clocked baseline. This is an ownership improvement, not area convergence.

Activity uses the same 12 MHz native-model fixture, I²C-loaded 43-instruction
firmware, `spiBoot=false`, and 27 windows per variant. Production maps retain SPI
boot. Values below are window means; all measured time/sample-only Telemetry
traffic disappears. Actual CPU application/GPIO commits still use Telemetry.

| Wake / windows | Telemetry commands, BD / Click | Work edges, BD / Click | Duration ns, BD / Click |
| --- | ---: | ---: | ---: |
| Maintenance / 22 | 1 → 0 / 1 → 0 | 24 → 24 / 21 → 18 | 3,147.358 → 3,147.358 / 3,064.024 → 3,064.024 |
| ADC / 3 | 2 → 0 / 2 → 0 | 217 → 217 / 215 → 214 | 18,439.147 → 18,439.147 / 18,272.479 → 18,189.145 |
| Firmware / 2 | 1 → 0 / 1 → 0 | 3,243 → 3,241 / 3,200 → 3,197 | 270,607.831 → 270,441.163 / 267,024.469 → 266,774.467 |

Click's maintenance clock extension is removed by eliminating time-only bank
turns; the completion synchronizer remains for real CPU/reset commits. BD's
maintenance duration remains limited by the other owners' drainage. These are
model activity counts, not physical energy estimates.

Evidence: `build/single-writer-telemetry/{bd,click}-area-r7.json`,
`{bd,click}-registers-r7.json`, `map-bd-r7`, `map-click-r8`, `activity-r7.json`
and the [independent review](reviews/single-writer-telemetry.md). The software
sample fixture is a supported-configuration timing check, not the production
area configuration. Both production maps include the final prefix-tree arithmetic;
no earlier map substitutes for this RTL. No P&R run is replaced by these
pre-placement maps. The
0.05 mm² routed hold-repair reserve remains separate and unspent. Resilient A/B
external boot, golden recovery and factory programming precede further area work.

### Clocked event arbitration and both retained register views

The six-bit pending register, arrival-cutoff mask and WAIT remain at the work-clock
arbitration edge. Event fields and event-only transactions leave Telemetry. Click
now retains application/GPIO values natively like BD, using its own phase bank.
BD reuses its existing full-return state to qualify clocked bank readers; Click
adds a completion-phase synchronizer and receipt authorization bit. Neither owner
contains a periodic clock or a clocked payload mirror.

| Metric | BD before → after | Click before → after |
| --- | ---: | ---: |
| Mapped logic, mm² | 2.058088 → 2.053129 (−0.24%) | 2.894444 → 2.854875 (−1.37%) |
| Repaired logic, mm² | 2.242768 → 2.237991 | 3.099576 → 3.063397 |
| Guards, mm² | 0.398907 → 0.398907 | 0.927310 → 0.932315 |
| Passive allowances, mm² | 0 → 0 | 0 → 0 |
| DLYD, mm² | 0.393112 → 0.393112 | 0.918854 → 0.923780 |
| Periodic sinks | 3,915 → 3,896 (−19) | 4,179 → 3,952 (−227) |
| Whole-chip service / work / LF | 1,203 / 2,634 / 78 → 1,203 / 2,615 / 78 | 1,207 / 2,894 / 78 → 1,207 / 2,667 / 78 |
| Services service / work / LF | 14 / 1,481 / 0 → 14 / 1,468 / 0 | 14 / 1,692 / 0 → 14 / 1,468 / 0 |
| Services periodic total | 1,495 → 1,482 | 1,706 → 1,482 |

Work sinks include three SRAM clock pins; the separate SDA event sink is excluded.
The 32→6-bit clear mask does not imply 26 removed cells: unused upper bits were
already optimized away. Click's native bank adds guarded phase storage while
removing periodic mirrors; its guard area therefore grows slightly. No Click
counts were resized. Ten generated module suffixes in its guard identity bindings
were updated after elaboration; owner paths, primitive parameters and recipes are
unchanged. Relative to the original mostly-clocked mapped baseline (0.576 / 0.594
mm²), current logic remains about 3.56× / 4.81×; this batch does not close that gap.

| Current DLYD purpose | BD cells / mm² | Click cells / mm² |
| --- | ---: | ---: |
| Custom ordering/reset | 3,542 / 0.264364 | 8,956 / 0.668447 |
| Bundling / Click request-pulse | 937 / 0.069935 | 845 / 0.063068 |
| Publication / Click output-pulse | 688 / 0.051350 | 1,988 / 0.148378 |
| Seed/reset admission | 100 / 0.007464 | — |
| Click ACK-pulse | — | 588 / 0.043886 |
| Total | 5,267 / 0.393112 | 12,377 / 0.923780 |

Matched activity uses the existing 12 MHz native-model fixture, I²C-loaded
43-instruction firmware (`spiBoot=false`) and 27 wake windows per variant. The
production maps use SPI boot. These are digital activity measurements, not
physical energy or flash-boot measurements.

| Wake / windows | Telemetry commands before → after, BD / Click | Work edges before → after, BD / Click | Duration ns before → after, BD / Click |
| --- | ---: | ---: | ---: |
| Maintenance / 22 | 1 → 1 / 1 → 1 | 24 → 24 / 19 → 21 | 3,147.358 → 3,147.358 / 3,064.024 → 3,064.024 |
| ADC / 3 | 2 → 2 / 2 → 2 | 217 → 217 / 214 → 215 | 18,439.147 → 18,439.147 / 18,189.145 → 18,272.479 |
| Firmware / 2 | 4 → 1 / 4 → 1 | 3,258 → 3,243 / 3,212 → 3,200 | 271,857.841 → 270,607.831 / 268,024.477 → 267,024.469 |

Time and sample updates still need Telemetry. Event-only activity does not. Click's
completion synchronizer extends the work-clock enable window by two edges for
maintenance and one for ADC; firmware wake work falls in both implementations.

Evidence: `build/clocked-events/{bd,click}-area.json`,
`{bd,click}-clock-owners.json`, `map-bd`, `map-click-r2` and `activity-r3`.
The retained inventory generator remains `tools/report_clock_owners.py`.
These are accepted graph-preserving pre-placement repairs, not routed signoff.
See the [independent review and fixes](reviews/clocked-events.md).

BD repaired-map reader qualification now covers all **224 periodic D pins** reached
from the 206-bit native bank: 192 snapshot bits and 32 Control receipt bits. All
ten cases (five PVT corners × two input slews) pass with a same-corner 20% two-sided
derate. Minimum next-edge setup residual is **+27.147 ns**, same-edge old-bank hold
residual **+1.242 ns**, and feedback-after-bank separation **+12.638 ns** against the
2 ns floor. The former negative pending-to-dispatch path and self-holding view-valid
path disappear when native pending and view-valid state are removed. The tool
checks the remaining readers explicitly; it does not waive those old paths.
Evidence: `bank-timing-r3/{inventory,results,receipt}.json` beneath the batch root.

The standard Telemetry update-stage campaign also resolves all ten cases, including
the two former FF parser rejections. Minimum local data lag / zero-reuse hold /
ACK-after-capture are **+10.162 / +1.042 / +1.265 ns**. Signed NLDM data offsets are
retained and debit hold; they are not clamped to zero. These local stage results
are conditional, uncomposed and without the bank screen's mismatch derate.
Evidence: `telemetry-stage-r1/{results,receipt}.json`. Full electrical/table-range,
source composition, clock skew and routed RC qualification remain item 17.

All four functional/physical exports pass strict validation and the generation
audit; both reset-crossing proofs pass structural containment. The affected
extended campaign covers 206 tests across 13 suites. One shared-ADC test required
isolating idle-MISO stimulus from a legitimate periodic sample wake; both variants
pass its focused rerun without changing the original assertion or deadline.
The original failure, diagnosis and independently reviewed correction are retained
in the [batch review](reviews/clocked-events.md).
The final frozen-source gate passes **302 Python and 195 Scala/export tests**;
its accepted receipt is `build/clocked-events/ci-r2/receipt.json`.

## Counting rules and evidence

### Clocked-event conversion baseline

This is **step 0 only**, before the event/register-view conversion. Source is
`49ca683`. Reuse the accepted BD `build/native-app-registers/map-bd-r2` and
unchanged Click `build/generic-mcu-r10/map-click` maps; these are not new maps or
timing qualifications. New per-owner connectivity inventories are in
`build/native-events/baseline/{bd,click}-clock-owners.json`.

| Metric | BD | Click |
| --- | ---: | ---: |
| Mapped logic, mm² | 2.058088 | 2.894444 |
| Repaired logic, mm² | 2.242768 | 3.099576 |
| Periodic sinks, total | 3,915 | 4,179 |
| Whole-chip service / work / LF | 1,203 / 2,634 / 78 | 1,207 / 2,894 / 78 |
| Services service / work / LF | 14 / 1,481 / 0 | 14 / 1,692 / 0 |
| Services periodic total | 1,495 | 1,706 |

Work counts include the three macro clock pins in each variant. The independent
SDA event sink is excluded from periodic totals. The after-area comparison is recorded above.

`PhysicalEstimateSpec` now counts accepted Telemetry commands at the existing
command crossing. Fresh baseline runs pass on both variants with the same 12 MHz
native-model fixture and 43-instruction firmware workload. The new counter is
testbench-only; no RTL instrumentation or new clock sink is added. This retained
activity fixture loads firmware through I2C (`spiBoot=false`); the production
area maps above use external SPI boot. It is a matched wake workload, not a flash
boot-time measurement.

| Wake kind | Windows per variant | Telemetry commands, BD / Click | Work edges, BD / Click | Duration ns, BD / Click |
| --- | ---: | ---: | ---: | ---: |
| Maintenance | 22 | 1 / 1 | 24 / 19 | 3,147.358 / 3,064.024 |
| ADC sample | 3 | 2 / 2 | 217 / 214 | 18,439.147 / 18,189.145 |
| Firmware | 2 | 4 / 4 | 3,258 / 3,212 | 271,857.841 / 268,024.477 |

Raw activity logs, export pointers and `activity-summary.json` are retained under
`build/native-events/baseline/`. Counts include all Telemetry command kinds;
elapsed/sample maintenance will still need transactions after event-only work is
removed. These are digital-model wake windows, not silicon energy measurements.
The [event contract](native-events.md) records why the suggested saturated-counter
protocol has not been adopted and separates oracle checks from RTL verification.

### Historical BD Telemetry register-view slice (`49ca683`)

The following records the prior batch. The clocked-event conversion above
supersedes its pending ownership, Click divergence and local bank-timing status.

The existing native Telemetry owner now supplies application words, GPIO
output/OE and pending readback without Services payload mirrors. Click is
unchanged. This is a bounded item-A slice; the MMIO scheduler remains clocked.

| BD metric | Parent `4943239` | This batch | Change |
| --- | ---: | ---: | ---: |
| Mapped logic, mm² | 2.100657 | 2.058088 | -0.042569 (-2.03%) |
| Repaired logic, mm² | 2.283901 | 2.242768 | -0.041134 (-1.80%) |
| Guards, mm² | 0.398209 | 0.398907 | +0.000698 |
| Passive allowance cells, mm² | 0 | 0 | 0 |
| DLYD area, mm² | 0.392440 | 0.393112 | +0.000672 |
| DLYD cells | 5,258 | 5,267 | +9 |
| Periodic clock sinks | 4,125 | 3,915 | -210 |

The 212 removed clocked payload bits are 192 application + 14 GPIO + 6 pending.
One qualified receipt ACK and one application-view-valid flag add two control
bits. Native feedback also drops the duplicated architectural fields; the closed
bank lives inside Telemetry. The custom feedback-order guard accounts for the
nine additional DLYD cells. Its timing obligations are separate from area savings.
By purpose, DLYD remains 937 bundling, 688 publication and 100 seed/reset cells;
custom ordering/reset grows from 3,533 to 3,542 cells. No allowance cells return.

| Clock/owner inventory | Before | After |
| --- | ---: | ---: |
| Whole-chip service | 1,203 | 1,203 |
| Whole-chip work (including SRAM pins) | 2,844 | 2,634 |
| Whole-chip LF | 78 | 78 |
| Services service-clock storage | 14 | 14 |
| Services work-clock storage | 1,689 | 1,478 |
| Services SRAM clock pins | 3 | 3 |
| Services total periodic sinks | 1,706 | 1,495 |

The separate SDA event sink is unchanged and excluded from periodic totals.
The frozen Click map remains at 4,179 periodic sinks. SRAM area remains
0.466241 mm². The original matched clocked-island baseline was about 0.576 mm²
BD logic; this batch narrows, but does not eliminate, that architecture-area gap.

`tools/report_clock_owners.py` retains the per-owner inventory for item 16. It
attributes inlined storage using original local Q aliases, so repair buffers
cannot hide ownership, and lists native/unclassified clocks explicitly.
Evidence: `build/native-app-registers/baseline-clock-owners-reviewed.json`,
`area-bd-r2.json` and `clock-owners-r2.json` in that directory. The new map is
`map-bd-r2`; its complete graph/protected-cell repair proof passes. These are
pre-placement measurements, not a new P&R or physical qualification.
The [register-view contract](native-app-registers.md) records functional evidence,
activity and outstanding aperture/routed timing obligations.

Native-model activity uses the same 12 MHz oscillator fixture and 43-instruction
firmware wake as the parent. Maintenance and ADC windows are unchanged. The
firmware wake gains one fast/work edge (83.334 ns, 0.031%) with the added full-return
admission barrier; retired instructions and the Control ACK transitions are unchanged.

| BD wake | Observations | Work edges before / after | Duration before / after, ns |
| --- | ---: | ---: | ---: |
| Maintenance | 22 | 24 / 24 | 3,147.358 / 3,147.358 |
| ADC sample | 3 | 217 / 217 | 18,439.147 / 18,439.147 |
| Firmware | 2 | 3,257 / 3,258 | 271,774.507 / 271,857.841 |

Fast edges are 38, 221 and 3,261 before, and 38, 221 and 3,262 after. All 27 frozen
Click windows are identical, including its 3,212-work-edge firmware wake. These are
native digital-model windows, not mapped timing or power. Logs and comparison are
retained in `build/native-app-registers/activity-r2/`, against `baseline-activity/`.
The final fast gate passes 300 Python and 169 Scala tests; `extended-r2.log` and
`extended-r2-junit/` record 192 passing tests across 12 affected suites. Independent
review fixes, generation audits and both RDC proofs are complete. Physical timing
remains unqualified; the contract records failed/unresolved screens explicitly.

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
