# Matched service-architecture comparison

Further service-island migration is frozen. Matching the mapper, SRAMs, native
core timing and workload confirms that the migrated services cost substantially
more area and active-clock work. Keep both native CPUs and all later correctness
requirements while evaluating a smaller service architecture. Restoring the old
raw-reset implementation is not an acceptable rollback.
A reconstructed clocked island must retain the newer correctness requirements
and be measured again; the historical baseline does not guarantee its final cost.

The compared RTL revisions are `8637099bb603543b4d8e1d76de2bf165bbaa171a`
and `2e4169c2f1befd1e8c5dfc704d9e936fe70e1a90`. No production RTL changes
are part of this measurement. The flip-flop-memory `4b5d105` experiment is not
the baseline here.

## Matched mapping and activity

| Metric | Baseline BD | Current BD | Baseline Click | Current Click |
|---|---:|---:|---:|---:|
| Mapped logic area, excluding SRAM (mm²) | 0.576457 | 3.492221 | 0.594447 | 4.345699 |
| Control guards (mm², included above) | 0.018892 | 0.594065 | 0.027954 | 1.146281 |
| TT listed-state leakage, including SRAM (µW) | 2.217–2.890 | 9.129–11.987 | 2.253–2.982 | 10.817–14.705 |
| Firmware work-clock edges per wake | 866 | 3,256 | 866 | 3,161 |
| Maintenance work-clock edges | 10 | 22 | 10 | 19 |
| Sampling work-clock edges | 183 | 216 | 183 | 214 |
| Work storage clock-input capacitance (pF) | 6.358257 | 20.774969 | 6.358257 | 20.946395 |

All candidates have three identical SRAM macros: 2 KiB program and 1 KiB working
memory. Their combined LEF footprint is 0.466241 mm². The report keeps SRAM
Liberty area and LEF footprint distinct. The real 100,000-edge POR hold is included
in mapping. Five pinned Liberty corners are reported in the evidence.

Each activity run contains 22 maintenance windows, three sampling windows and
two firmware windows. Every firmware window retires exactly 43 instructions.
Real I²C upload, commit, lock, deadline sleep and ADC pin stimulus are unchanged.
Both revisions use identical supported default core policies; the old physical
emitter's different timing experiment is not used. The baseline harness-only
patch inlines its original assertions so Icarus executes them. Baseline metadata
explicitly retains its historical reset limitations and cannot pass the
production v3 policy gate.

The workload uses the same 12 MHz service oscillator and approximately 7.7307 Hz
LF model. It exercises Groundlark OFF/restart qualification, not RUN/SHUTDOWN.
The implementation clock target remains 20 MHz.

These are library estimates and native-model activity, not silicon energy.
Leakage sums independent listed cell states, which need not form one reachable
standby state. Storage clock-pin capacitance excludes buffers, CTS and wires.
Native activity counts width-weighted capture opportunities, not changed bits,
glitches or internal switching energy. Analog and pads are excluded. The
6.06×/7.31× logic-area increase, larger leakage, loads and wake counts justify
freezing further state removal without claiming a complete energy measurement.

Large native owner groups include I²C (0.522/0.608 mm² BD/Click), elapsed scaling
(0.339/0.377), Control (0.331/0.397), and program/RAM access (each 0.221/0.299).
These disjoint hierarchy groups include nested bridges and guards. Guard area
crosses those owners; do not add the two decompositions. Rework must preserve
reset containment, accepted effects, ABI, lock, retention and permanent power
supervision.

## Physical experiment

The common outline is fixed before placement at 3,250 µm square, with the same
30 µm core inset, macro coordinates, PDN, placement settings, routing seed, eight
threads and pinned tools. It derives from the largest mapped logic candidate at
45% target occupancy plus SRAM footprints and core inset. Placement uses density
0.50 for every candidate. This does not establish minimum die size.

Nominal, minimum and maximum RC are extracted independently from the same routed
checkpoint, each with its own bound ODB/SPEF. The flow analyzes five cell corners
against each RC view. Reset-tree repair and the full reset envelope remain R2b
obligations; other timing-closure work remains under item 17. Routing success is
not qualification.

| Routed metric | Baseline BD | Current BD | Baseline Click | Current Click |
|---|---:|---:|---:|---:|
| Placed cells plus SRAM (mm²) | 1.058367 | 4.024985 | 1.079839 | 4.880987 |
| Routed wire length (m) | 1.316968 | 5.864487 | 1.325040 | 6.401379 |
| Detailed-router violations | 0 | 0 | 0 | 0 |
| TT/nom local probe groups | 85 | 1,228 | 83 | 1,495 |
| Local timing violations | 0 | 395 | 0 | 47 |
| Uncovered local probe groups | 0 | 0 | 0 | 0 |

The local probe inventory additionally contains ten constant groups and four
reset-only groups across the four designs. These are not dynamic timing passes.
The targeted FF/min and SS/max checks cover the former missing dynamic probes:
BD's address C-element measures 8.091–11.020 ns at SS/max, exceeding its 10 ns
maximum. Click's corresponding acknowledge guard measures 200.045–211.952 ns;
its local contract has a 32 ns minimum and no upper bound. That PASS does not
establish a controller deadline or reset envelope. Full local probes here use
TT/nom only, supplemented by those selected corners; they are not a complete
fifteen-corner local timing campaign.

Signed STA diagnostics are retained: 202 negative reset-only measurements in BD
and 40 negatives in Click (24 dynamic). Every dynamic negative belongs to a
VIOLATION group. Independent old/per-group and optimized/global contexts agree
point by point. The inspected negatives arise from Liberty extrapolation beyond
an 8.6 ns slew-table ceiling: BD's reset input is modeled at 537.8 ns; Click's
generated `~porReleased` net drives 3,300 instance terminals and reaches about
641/548 ns rise/fall slew. Its downstream buffer then receives 55.3 ns slew.
These out-of-range results are not credible physical delay bounds. The collector
rejects a dynamic-negative PASS, and R2b must repair this internal POR tree as
well as other reset distribution before qualifying reset or local timing.

The old probe logs contain two BD omissions and one Click omission. BD's initial
data path is proven constant zero. The dynamic omissions are automatic STA loop
cuts inside preserved primitives. Separate local measurements retain source
slew, cut outgoing timing edges at selected output/capture boundaries without
changing physical connections, and
require each meaningful source/sink polarity pair. Constant and reset-only
cases are distinct from timing passes. Keeper feedback, complete controller
loops, pulse/aperture and reset envelopes remain separate obligations.

The four corrected routes, all 60 clocked corner reports and full TT/nom probes
are complete. Independent review found that an early constraint fallback to
module inputs omitted locally retained state. Those first attempts remain
diagnostic evidence. The corrected fallback bounds all register launches to the
exact destination, with explicit endpoint-qualification limits. The final
independent receipt confirms complete evidence for the R4 cost decision while
retaining open timing violations. R2b reset distribution comes next.

## Reproduction

Evidence is under `build/matched-service-comparison/`. The baseline is a detached
worktree; `tools/gf180_matched.py setup-baseline` records its two-file patch.
Run sbt serially in each checkout to emit `riscay.physical.EmitPhysical` and run
`riscay.PhysicalEstimateSpec`. Use `gf180_matched.py map-inputs`,
`gf180_implement.py` and `report_gf180_matched.py --output <new-report.json>`
with the same locked assets. Baseline policy requires the explicit comparison
option. Keep original logs and use fresh output paths for reruns.

The independent numerical review uses its own Decimal/Liberty parser and graph
traversal. It reproduced areas, five leakage corners, clock loads, storage
observer coverage, all wake windows, and identical core/workload contracts.
The final mapping/activity report is `mapped-cost-r4.json`; it validates eight
measurement/preparation helpers and the independent audit's 432 artifact files
and 190 source files, including the four executed testbenches, binaries and logs.
Reproduction requires that independent audit receipt (`--audit-receipt`), not
just copying the displayed totals. Ten provenance controls reject stale or
missing bindings. Four physical-policy cases and all 428 Python controls pass.
The new executable Tcl controls reproduce the endpoint-cap failure across both
polarities and reject a mutation restoring the old accounting.
Preparing the local timing graph once preserves all pair/polarity checks while
avoiding repeated whole-design rebuilds. Independent differential checks match
17,980 measurements across all 295 completed original groups, retain existing
violations and detect the
same actual interior-arc mutations. `--run-tag context-r3` keeps the new complete
sweeps separate from the original reports and interrupted current-BD attempt.

The final independent physical receipt is
`physical-review/r4-physical-provenance-r1.json`, SHA256
`18e890ad30954d6d4ed6fed4a56bb1b394c81007e80009e0c4ba014dfe03609a`.
It binds 1,119 inputs and 12 helper files, all four corrected routes, 60 clocked
views, 257,148 complete local polarity/mode measurements, original/new
differential checks and actual-path negative-delay diagnosis. Seventeen
collector controls pass. The mapping/activity provenance receipt is
`cost-review/r4-provenance-receipt.json`, SHA256
`c7bfd7b02421cc6c4627ea663205b5b417cb2f69de8a193fcfae88f14e7f5757`.
All paths in this paragraph are relative to the evidence directory above.
