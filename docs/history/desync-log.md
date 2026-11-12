# Desynchronization ledger

Logic excludes the same three fixed SRAM macros. Ratios, not absolute area
targets, govern adoption. Old BD/Click physical results do not qualify desync.

| Batch | Flat mapped logic / clocked | Storage bits | Delay/controller/mutex | Repaired + CTS | RTL diff vs clocked | Status |
|---|---|---|---|---|---|---|
| Phase 0 tools/reference | 0.5318332992 mmÂ² / 1.000Ã— â†’ 1.000Ã— | 2,977 â†’ 2,977 | 0 mmÂ² / 0% | 0.5915383488 mmÂ² / 1.000Ã— | 0; no desync RTL | Verified and independently reviewed; stop after Phase 0 |
| Connected controller preparation | Storage-only 0.5849922624 â†’ connected 0.5958650880 mmÂ²; 1.099954Ã— â†’ 1.120398Ã— pinned reference; **whole-chip ratio unavailable** | 2,977 architectural; 5,283 FF/latch bits + 198 control keepers | Controllers/joins/mutex 0.0109606336 mmÂ², 1.83945%; delays unmeasured | Not measured | 0 | Ten banks connected; external delay apertures; no chip acceptance |
| Loaded control/distribution and area trial | 0.5958650880 â†’ 0.5998603520 mmÂ² before lines; cell-exact ten-line trial **0.6186512640 mmÂ² / 1.163243x (FAIL)** | Unchanged: 2,977 architectural; 5,283 FF/latch + 198 keeper bits | Trial 0.0337468096 mmÂ² / **5.4549% (FAIL)** | Zero-wire preparation 0.6562813824 mmÂ², excluding lines; not the matched physical result | 0 | Electrical preparation and ideal-cycle proof; production sizing remains unavailable; budget decision required |
| Approved mapped ceiling and pure data-path measurements | Unchanged **0.6186512640 mmÂ² / 1.163243x**; mapped ceiling now **1.20x** | Unchanged: 2,977 architectural; 5,283 FF/latch + 198 keeper bits | Unchanged 0.0337468096 mmÂ² / **5.4549%**; separate 5% ceiling unchanged | Unchanged preparation; complete physical ratio unavailable | 0 | Mapped area fits; data segments measured; control share and composed timing remain open |
| Direct I2C latch handoff | **1.163243x â†’ 1.163243x**, 0.6186512640 mmÂ² unchanged provisional trial | 2,977 architectural; 5,283 FF/latch + 198 keepers, unchanged | 0.0337468096 mmÂ² / **5.4549%**, unchanged | Preparation remains 0.6562813824 mmÂ² without lines/wires | 0 | Sampled M-to-S steady-cycle hold measured; no added hold cells or adopted delay counts |
| Full-feedback I2C retention | **1.163243x â†’ 1.163243x**, 0.6186512640 mmÂ² unchanged provisional trial | 2,977 architectural; 5,283 FF/latch + 198 keepers, unchanged | 0.0337468096 mmÂ² / **5.4549%**, unchanged | Unchanged preparation; complete physical ratio unavailable | 0 | All paired latches retain data in the sampled full-feedback circuit; no production timing adoption |
| Work-gate return ordering | **1.163243x â†’ 1.163243x**, 0.6186512640 mmÂ² unchanged provisional trial | 2,977 architectural; 5,283 FF/latch + 198 keepers, unchanged | 0.0337468096 mmÂ² / **5.4549%**, unchanged | Unchanged preparation; complete physical ratio unavailable | 0 | Actual retained qualifiers and return paths checked; opening/setup and production timing adoption remain open |
| Conditional work-gate opening | **1.163243x â†’ 1.163243x**, 0.6186512640 mmÂ² unchanged provisional trial | 2,977 architectural; 5,283 FF/latch + 198 keepers, unchanged | 0.0337468096 mmÂ² / **5.4549%**, unchanged | Unchanged preparation; complete physical ratio unavailable | 0 | Actual gate paths measured at the qualifier setup aperture; upstream arrival/retention and production timing adoption remain open |
| Explicit prototype budget approval | **1.163243x â†’ 1.163243x**, unchanged; ceiling **1.17x** | 2,977 architectural; 5,283 FF/latch + 198 keepers, unchanged | 0.0337468096 mmÂ² / **5.4549%**; ceiling **5.5%** | Unchanged preparation; 1.20x repaired/tree limit retained | 0 | User-approved prototype budgets now fit; timing and production adoption remain open |

The mapped reference is the original clocked export, remapped with the pinned
Yosys 0.62/ABC and GF180 7-track libraries. Pre-placement repair is
0.5326608896 mmÂ²; placement repair is 0.5683921600 mmÂ²; CTS adds
0.0231461888 mmÂ² to reach the table's total. No ordinary data/storage is
protected. Periodic sink inventory is service 539 + work 2,362 + LF 78 = 2,979,
including three SRAM clocks. The separate SDA event adds one nonperiodic pin.
All 2,980 pins are reached; graph preservation passes at preparation, repair,
placement and CTS. Five final PVT reports have zero slew/capacitance violations.

Physical settings are 1.94 Ã— 2.53 mm, density 0.60, three north-edge SRAMs,
per-corner electrical limits and corrected nominal wire resistance. This is
placement-estimated RC, **not routed signoff**. The progress-fixed OpenROAD
binary has SHA-256
`20abaf17173bc8be06b658179920f739103279e54105b3c165dceab4c8ba00a1`;
the run receipt pins all other tool/library inputs. Reuse the same flow for the
eventual desync denominator comparison.
The current prototype budgets permit at most 0.6222449601 mmÂ² mapped
(user-approved 1.17x after `b2cac0f`),
0.7098460186 mmÂ² repaired plus trees. Revised storage limits are exactly
2,977 architectural bits and 0.2552221840 mmÂ² storage cell area. These are limits,
not achieved desync measurements.

| PVT | Fast-region period requirement, ns, before 1.2 factor |
|---|---:|
| TT 25 Â°C, 3.3 V | 55.093433 |
| SS 125 Â°C, 3.0 V | 112.803410 |
| SS âˆ’40 Â°C, 3.0 V | 76.374889 |
| FF 125 Â°C, 3.6 V | 45.689070 |
| FF âˆ’40 Â°C, 3.6 V | 30.994888 |

These are STA requirements on the CTS netlist at zero wire RC, including
full- and half-cycle groups. The reference's 50 ns analysis period does not
close setup at every corner; electrical acceptance does not imply 20 MHz
timing closure. These are **not generator periods**. No actual
loaded chain exists yet; `desync-delays.json` remains empty, and missing entries
fail. No slow-corner IÂ²C/ADC throughput margin is claimed. IÂ²C remains 400 kHz
SCL, as confirmed by the user.

The fresh export maps to 0.5312120576 mmÂ². Its 0.12% difference comes from unordered Scala `Set[Bool]`
iteration changing two commutative OR-expression orders in the emitted clocked
fabric. Their equivalence passes all 6,732 points in `equiv-reference-final`.
It is not a desynchronization saving. Keep the reference export pinned
for each comparison; resolve deterministic elaboration before cross-commit
comparisons depend on newly emitted graphs.

Evidence: `build/desync-phase0/map-pinned-clocked`, `clocked-physical-final`,
`region-final`, `equiv-ci-tool-r6` and `ci-final`. Yosys 0.33 proves 6,976/6,976
reference equivalence points. Next-state, reset-value and fixed-macro-input
mutations fail as required. The complete gate passes **427 Python tests and
267 Scala tests across 28 suites**, both measured area comparisons, and the
6,976-point chip equivalence check. The reference harness passes on Yosys 0.33
(CI version) and 0.62 (physical toolchain). Independent review's chain-identity
and solver-coverage findings are fixed and approved. No production RTL,
functional oracle or deadline has changed. The existing earliest-status test
body now also runs against the clocked reference.

Failed experiments retained: unsupported asynchronous FF SAT models â†’ use
`clk2fflogic`; missing blackbox declarations/internal structural matching â†’
strict hierarchy plus ordinary `opt_merge`, with all equivalence points proved;
old OpenROAD repair-progress hang â†’ pinned fixed build; blanket 2 ns data slew
and incorrect work-clock traversal (0.878861 mmÂ²) â†’ per-corner ordinary limits
and an explicit combinational generated-clock path. None qualifies the reference.

Phase 0 ended at the requested boundary. The GF180 mutex still lacks layout,
LEF and Liberty; its registry recipe is unavailable.

## Retired single-oscillator prototype (historical)

| Batch | Mapped logic | Ratio to clocked | Storage bits | Controller/delay/mutex area | Status |
|---|---:|---:|---:|---:|---|
| Copied ideal-clock region | 0.5318332992 mmÂ² | 1.000Ã— (region only) | 2,977 â†’ 2,977 | Excluded; not measured | Digital tests pass; no physical Phase 1 acceptance |

The region map has 21,696 cells, three fixed SRAM macros and zero protected
ordinary cells. Its clock inventory remains 539 service + 2,362 work + 78 LF
sinks, plus one SDA-event sink. Service/work are external ideal clocks in this
measurement; no reduction in periodic sinks is claimed. Mapped whole-chip
headroom is 0.079775 mmÂ², before the unmeasured generator. Repaired desync area
and timing remain unmeasured. Evidence: `build/desync-prototype/map-region-r1`
and its `region-comparison.json`; the whole-chip gate correctly rejects it with
`DESYNC_INCOMPLETE_GENERATOR`.

The user limited this batch to a digital prototype. Nine functional files are
still identical to clocked after package normalization. The shell retains the
work gate, LF clock, wake logic and POR hold state. Separate simulation-only
controller/delay/mutex bodies now execute the pausible clock; no physical cell
recipe or measured chain has been added. Physical area acceptance stays open.

Scala diff against `designs/clocked`: **159 added / 27 removed lines**, including
package/export names and shell/interface files; the separate digital models are
79 lines. No clocked architectural storage is added or removed. The model's
event-cancellation counters are simulator bookkeeping, excluded from synthesis.

Final CI (`build/desync-prototype/ci-final-r2`) passes **428 Python tests and
306 Scala tests across 37 suites**, with no skips or changed inputs. It proves
all **6,976 equivalence points** against a freshly exported clocked chip
(Yosys 0.33). Shared test bodies select desync without changing their oracles
or deadlines: core, SoC, fabric, reset, sleep/deep-sleep, four-variant event
history and both 400 kHz earliest I2C status test points. The extended A/B
boot/update and firmware rerun against the final model passes **37 tests across
two suites** (`digital-r6.log`, separate `extended-target/test-reports`).

The 2 KiB primary boot takes **94.287 ms / 897,968 work edges**; full-capacity
golden fallback takes **267.655 ms / 2,549,072 work edges** (`digital-r6` artifacts).
Both pass the original deadlines with randomized 50â€“55 ns loop delays. These
are digital workload measurements, not corner-qualified timing bounds.

Independent review requested actual exported-shell coverage and explicit POR
behavior. Both are covered; re-review has no remaining functional findings.
The final gate compares a real desync candidate against the clocked reference.
Digital event cancellation preserves the reset ABI; physical delay discharge,
reset qualification, generator area, timing and routed checks remain open.

Failed experiments retained:

- Fixed `clocked.json` descriptor name rejected desync; the shared writer now accepts an optional filename without changing its default or macro models.
- Pre-time-zero testbench power-good initialization left the existing reset-hold model unknown; matching the supply monitor's time-zero assertion fixes the fixture (`digital-r3`, `shell-debug-r1`).
- Minimum-reset assumption rejected the existing 1 ns brownout test; cancel pending simulator events on POR instead (`ci-final`, stopped after the failure).

## Deterministic region exports (clocked fix retained; copied region retired)

| Batch | Flat mapped logic / clocked | Storage bits | Delay/controller/mutex | Repaired + CTS | RTL diff vs clocked |
|---|---|---|---|---|---|
| Sort application-address decode before constructing hardware | Both 0.5318332992 â†’ 0.5315501184 mmÂ²; 1.000Ã— â†’ 1.000Ã— (region only) | 2,977 â†’ 2,977 | Generator excluded, not measured | Not rerun; Phase 0 remains a pinned pre-change baseline | Unchanged: +159 / âˆ’27 Scala lines |

Mapping a key set to Chisel `Bool` let identity hashes choose the OR-tree order.
Both implementations now sort integer addresses first. No state, ABI, reset or
clock changes; all nine functional files still match after package normalization.
The small common mapping change (âˆ’0.053%) is not a desync area saving.
Periodic sinks remain 539 service + 2,362 work + 78 LF, with one separate SDA
event pin and zero protected ordinary cells.

Evidence is in `build/desync-reproducibility`: `before.log` fails the new
repeat-export property in both variants, `after.log` passes it, and both paired
production exports are byte-identical. `map-clocked`, `map-desync` and
`region-comparison.json` retain the matched maps; whole-chip acceptance still
rejects the excluded generator. Parent-to-current proofs pass all 6,976 points
per variant after bijectively matching five renamed equality wires by their
complete expression; no point or logic was removed. The failed name-based runs
are retained. Independent review accepted the implementation and correspondence.

Final CI passes **428 Python tests and 308 Scala tests across 38 suites**, with
no skips, changed inputs or missing outputs. Its fresh clocked/desync exports
prove all 6,976 equivalence points and exactly match the measured exports across
a separate sbt JVM (31 clocked files, 33 desync files). The repeat-export test is
now in the fast gate; existing functional assertions and deadlines are unchanged.

## Multi-bank rebuild: storage-cap investigation

The user rejected raising the storage-area cap and selected the flop-plus-bubble
investigation. No whole-chip desync map exists in this batch.

| Batch | Whole-chip mapped/repaired ratio | Architectural bits / storage area ratio | Control share | Banks / cycle time | Result |
|---|---|---|---|---|---|
| Retire oscillator copy; partition and CPU-FF preflight | Unavailable â†’ unavailable | Reference 2,977; candidate unchanged by substitution / calculated 1.300158x â†’ 1.230263x | Unmeasured; mutex allowance 0.001 mmÂ² | 9 candidate / unmeasured | CPU-only candidate retained for qualification; no RTL conversion adopted |

Literal master/slave replacement costs 0.2654633408 mmÂ² of storage against
0.2041777472 mmÂ² clocked, exceeding the cap by 0.0102411568 mmÂ². The CPU's 591
mapped plain FFs would save 0.0142709952 mmÂ², giving 0.2511923456 mmÂ² storage and
a 0.5788478976 mmÂ² logic **substitution floor** (1.088401x). After the estimated
mutex allowance, 0.0317603965 mmÂ² remains below the mapped cap for all other
controllers, joins and delay/hold cells. These are library-area calculations,
not synthesis of a controller-connected chip; reset-master changes are excluded.

Independent review caught missing opposite-edge and gate dependencies. The
partition now emits their exact receiving-register witnesses and phase types;
it adds the previously missing power-to-ADC gate edge. The positive-edge graph
projection remains live with CPU FFs but is explicitly incomplete for the MCU.
Negative-edge reset release, both transparent-phase timing cones, FF apertures,
per-register enable gating and arbitrary-stop handshake rest remain open.
The gate-transition counterexample also rejects using the new enable for a
falling capture: start would insert one and stop would lose one. The existing
previous-enable state may supply the qualifier; its phase stability is unproved.

Failed experiment: contracting both CPU and Fabric creates a tokenless cycle;
rejected with `DESYNC_TOKENLESS_CYCLE`. No reset, oracle or deadline was relaxed.
Evidence: `build/desync-multibank-preflight/storage-floor.json` and
`build/desync-multibank/{partition,cpu-screen,cpu-storage-candidate}.json`.

Validation: `ci-r1` passes 439 Python tests, 268 Scala tests across 29 suites,
and all 6,976 Phase 0 reference-equivalence points. This includes unchanged
400 kHz earliest I2C status at both service rates, full-capacity SRAM, sleep,
reset, generic SPI boot and repeat-export coverage. After Python-only review
fixes, `ci-reviewed` passes all 441 Python tests and both pinned reference
area comparisons (mapped 0.5318332992 mmÂ²; repaired/CTS 0.5915383488 mmÂ²).
Both receipts have no changed inputs or skips. Independent review's phase/gate
inventory, protection-permission, unsupported-state and descriptor-bypass
findings are addressed. The checker still cannot qualify the unfinished MCU.
No clocked/BD/Click production RTL changed in this batch.

## Phase-aware graph and causal controller candidates

| Batch | Whole-chip mapped/repaired ratio | Architectural bits / storage area ratio | Control share | Banks / cycle time | Result |
|---|---|---|---|---|---|
| Opposite-edge bank; causal controller and CPU pair candidates | Unavailable â†’ unavailable | No payload change; reference 2,977 / calculated floor stays 1.230263x | Whole-chip share unmeasured; ordinary pair 0.0002261056 mmÂ², CPU pair including its two joins and output driver 0.0003314752 mmÂ² | 9 â†’ 10 / unmeasured | Abstract graph and schematic samples pass; physical bindings remain unavailable |

The 42 falling-edge bits now have their own S-master bank. The ten-bank graph
has 25,293 reachable markings and one-safe/live topology. With `power.m-` held,
every abstract marking drains to one terminal within 51 firings. Physical
handshake-wire rest, gate-leaf ordering and controller correspondence are open.
The partition checks the existing previous-enable register's actual connection,
clock, reset and phase; no new qualifier copy or payload storage was added.

The causal controller restores `Ri & !Ro` on acknowledgement rise. No extra
keeper or guessed wait repairs the original recipe's request-return race.
The CPU pair's sampled **slave** return-to-capture propagation is at least
0.383594 ns and its sampled slave-enable high pulse is at least 0.601142 ns.
These are not the CPU FF capture/hold margin or a minimum-pulse guarantee.
All whole-chip joins, matched delays, trees, any required master resets and the
mutex still need area/timing accounting. The 0.5788478976 mmÂ² substitution floor
and 0.001 mmÂ² mutex estimate remain estimates, not a desync map.

Evidence: `build/desync-multibank/{partition-ten,graph-ten-r2}.json`,
`primitives-final-r1` (120 five-corner loaded schematic cases),
`primitives-final-negative` (expected `DESYNC_PRIMITIVE_STATE`), `ci-phase-r1`
(450 Python, 268 Scala across 29 suites, 6,976 reference equivalence points)
and `ci-phase-reviewed` (451 Python plus both pinned reference area comparisons
after the Python-only recipe update). Receipts have no changed inputs or missing
outputs. Independent review's phase, qualifier, constant-emission and reset-wording
findings are fixed. No production RTL, assertion, deadline or ABI changed.

Failed experiments retained:

- Nine mixed-phase banks: sampled S aperture 1.64â€“5.97 ns at SS/hot versus the reference's 12.63 ns half-cycle requirement; isolate opposite-edge state in bank ten.
- Simplified CPU controller: 50 fF publication loading stalls; output isolation restores sampled behavior but leaves about 15 ps at 50% crossings and âˆ’159 ps at conservative thresholds; restore the causal condition.
- Stronger keeper alone: `_2` remains marginal and `_4` worsens it; rejected. A buffered-delay experiment also remains unadopted.


## Experimental mutex layout

| Batch | Whole-chip mapped/repaired ratio | Architectural bits / storage area ratio | Cell area | Result |
|---|---|---|---|---|
| GF180D mutex layout and distributed extraction | Unavailable â†’ unavailable | Reference 2,977 unchanged / calculated floor stays 1.230263x | 0.00098784 mmÂ² outline, below the 0.001 allowance | Experimental; no mapper binding or chip RTL change |

The unchanged 46-transistor schematic now has a generated 28 Ã— 35.28 Âµm layout.
Magic and Netgen agree; independent foundry KLayout checks report zero violations
across 649 categories and matching LVS. A thin Metal1 wire and a wrong transistor
gate fail the corresponding checks. The geometry is within the declared outline.
Extraction keeps all 46 MOS, 303 resistors and 451 capacitors, including the
1.93 Mohm substrate branch. Collapsing resistance recovers the schematic nets;
the audit includes device terminals, W/L and diffusion area/perimeter.

Mirrored devices do not imply matched routes. N0/N1 external extracted capacitance
is 20.59/21.95 fF before MOS capacitance. Simulations therefore load and observe
the actual G pins through distributed RC; no capacitance-only replacement is
used. Nominal parasitics are not min/max RC. Density/fill, antenna, latch-up,
variation, coupled noise, LEF and conditional Liberty remain open. Contention
still has no maximum resolution-time promise, and the reliability target is unset.

Failed experiments retained: initial tap edges passed Magic but produced 20
foundry implant-width errors; expanding the well within the same outline fixes
them. A routing-priority name mismatch is fixed. Review also added diffusion
geometry checks, reverse handover and active-reset samples. Operational stopping
must still drain grants; these samples characterize destructive POR behavior
and do not authorize operational reset.

The implementation is committed in chisel-async
[`24c1216`](https://github.com/BiscutLabs/chisel-async/commit/24c1216), with portable
Magic startup fixed in [`3a712ec`](https://github.com/BiscutLabs/chisel-async/commit/3a712ec).
Both reviewed extracted-RC runs pass: 361 base cases and 101 reverse/reset cases,
including two half-timestep repeats. Sampled uncontended propagation is
0.334â€“1.325 ns, quiet handover is at least 0.891 ns and active-reset clearance
is at most 2.094 ns. Half-step changes are below 0.041 ps. None of the 20
simultaneous-request reset cases remained unresolved before reset; that coverage
is still open. These are observations at five transistor corners with nominal RC.

Evidence is under `build/desync-mutex-layout/`: `layout-verified-final`,
`rc-samples-r8`, `rc-supplement-r1`, the two `rc-*-reviewed-final` replays,
`replay-controls-r1` and `ci-r1`. The final checker independently verifies saved
stimuli, PVT, output files and recomputed convergence. Library validation passes
27 Python tests, 11 digital contract cases, 44 diagnostic controls and docs.
Independent review's routing, geometry, reset-window and replay findings are fixed.
The MCU fast gate passes 451 Python tests and 268 Scala tests across 29 suites,
plus the Phase 0 reference-equivalence harness. Its receipt has no changed inputs,
missing outputs or skips. This remains reference verification, not generated-chip
flow equivalence. The shared circuit/ABI, resets, deadlines,
clocked reference and old BD/Click oracles are unchanged; RTL diff is zero.

## Mutex integration views

| Batch | Whole-chip mapped/repaired ratio | Architectural bits / storage area ratio | Mutex outline | Result |
|---|---|---|---|---|
| Top-metal port access and scenario timing tables | Unavailable â†’ unavailable | Reference 2,977 unchanged / calculated floor 1.230263x unchanged | 0.00098784 â†’ 0.00098784 mmÂ² | Experimental views; mapper binding remains unavailable |

OpenROAD could not access the original 0.4 Âµm Metal4 ports behind conservative
internal obstructions. Seven Via4 connections and 0.8 Âµm Metal5 landing pads fix
access within the same outline. The transistor circuit and Metal2â€“4 routes stay
unchanged. New foundry checks report zero violations across 649 categories; both
LVS engines match. The new nominal extraction contains 46 MOS, 304 resistors and
452 capacitors. Earlier RC results describe the earlier geometry, not these pins.

The macro LEF blocks Metal1â€“4 and exposes only verified Metal5 ports. The access
fixture connects five signals and explicit VDD/VSS straps with zero final router
violations. Its coarse global-route congestion is retained, not reported as a
full-chip routing pass. All 462 loaded-RC samples pass. The separate timing grid
passes 180 cases plus four half-step repeats; OpenSTA reproduces all 180 lookups.
Isolated 50%-threshold request propagation is 0.299â€“1.194 ns; input capacitance is
10.16â€“13.86 fF. Refinement changes are below 0.04 ps. These are scenario samples,
not guaranteed bounds. Tables have no synthesis function or contention bound;
Boolean `when` conditions do not prove prior quiescence.

Independent review fixed waveform recrossing checks, slew/load restrictions,
layout/timing hash binding and missing-inventory rejection. A glitch and a
shortened table entry fail their checks. The first timing run was stopped after
the checker finding and replaced, not counted as a pass. Evidence is under
`build/desync-mutex-layout/`: `layout-m5-r1`, `views-m5-final-r1`,
`rc-m5-base-r1`, `rc-m5-supplement-r1`, `timing-m5-r2` and
`liberty-shortened-control`. The library Python properties and digital Mutex
contract remain green; source and commands are in its optional GF180 integration.
The implementation is chisel-async
[`aef1f09`](https://github.com/BiscutLabs/chisel-async/commit/aef1f09): 36 Python
properties, 11 digital contract cases and 44 diagnostic controls pass. The MCU
gate in `ci-m5-r1` passes 451 Python tests, 268 Scala tests across 29 suites and
all 6,976 reference-equivalence points, with no changed inputs or missing outputs.
This remains reference verification, not generated-desync flow equivalence.

The user set the stop/wake mutex target to **at most 1 FIT per MCU**. It remains
unmet: unresolved-reset recovery, min/max RC, variation/noise, a justified failure
model and the worst admitted arbitration rate are still needed. No chip-level
area, enable-tree, controller-share or slow-cycle result is claimed. Ten banks,
the CPU storage exception, architectural RTL and behavioral oracles are unchanged;
RTL diff remains zero.

## Generated storage and work-gate feasibility

| Batch | Whole-chip mapped/repaired ratio | Architectural bits / storage area ratio | Control share | Banks / cycle time | Result |
|---|---|---|---|---|---|
| Generated storage with CPU FF exception | Unavailable â†’ unavailable; storage scaffold 0.5849922624 mmÂ², 1.099954x pinned mapped reference | 2,977 â†’ 2,977 / 1.230263x | Not measured as a chip | 10 / unmeasured | Storage-only map passes; complete controller adoption and POR initialization remain open |

`desync_transform.py` now generates storage from the clocked generic netlist.
Only architectural slaves are work-gated; falling captures use the existing
previous-enable state. Synchronous-reset/enable priority is preserved, with
ordinary datapath logic free to optimize. Explicit aliases define masters for
independent application-release and wake-hold resets. Review caught the stale
master overwriting a wake flag at reset release; the fixed waveform passes and
the old plain-master version fails `WAKE_LOST_AT_RELEASE`.

The first conversion retained 35 redundant architectural bits. Running ordinary
constant, width and duplicate-register optimization before conversion removes
them without changing RTL. Non-protecting Q aliases retain bank ownership through
renaming; cross-bank merges fail. On the same Yosys 0.62/ABC and TT Liberty:

| Measurement | Before normalization (`storage-r5`) | After (`storage-r7`) | Paired clocked (`reference-r3`) |
|---|---:|---:|---:|
| Mapped logic, mmÂ² | 0.5864630464 | 0.5849922624 | 0.5369678720 |
| Storage area, mmÂ² | 0.2543007488 | 0.2511923456 | 0.2041777472 |
| Architectural bits | 3,012 | 2,977 | 2,977 |
| Physical storage bits | 5,353 | 5,283 | 2,977 |

The matched normalized ratio is 1.089436x. The pinned 0.5318332992 mmÂ² reference
still sets the unchanged ceiling; its ratio is 1.099954x. Under the normalized
input/naming path the paired reference is 0.0051345728 mmÂ² higher than that pin;
the individual causes have not been isolated. Neither reference is replaced
silently. The scaffold has 0.0266160317 mmÂ²
logic and 0.0040298384 mmÂ² storage headroom, before omitted control, timing and
qualified-POR work. No repaired ratio is available for this candidate.

| Bank | Architectural bits, unchanged | Clocked storage, mmÂ² | Candidate storage, mmÂ² |
|---|---:|---:|---:|
| CPU | 591 | 0.03762353 | 0.03762353 |
| Fabric | 707 | 0.04890686 | 0.06362787 |
| Control | 247 | 0.01857578 | 0.02270276 |
| Program | 78 | 0.00500945 | 0.00686659 |
| RAM | 81 | 0.00520043 | 0.00713001 |
| I2C | 347 | 0.02276861 | 0.03071304 |
| ADC | 83 | 0.00554727 | 0.00739343 |
| Time | 530 | 0.03735133 | 0.04788390 |
| Power | 192 | 0.01444442 | 0.01763185 |
| Falling edge | 42 | 0.00284498 | 0.00371428 |
| LF, retained | 78 | 0.00583045 | 0.00583045 |
| SDA event, retained | 1 | 0.00007464 | 0.00007464 |

The expanded controller exploration found that symmetric joins alone deadlock
the work-gate/same-phase relations. A one-sided closure qualifier and CPU rearm
condition are proposed, not adopted pending the user's decision. The full
inventory estimates 0.0108311168 mmÂ² for controllers, joins, stop and the
experimental mutex, excluding delays/drivers/trees. The initial 15-gate estimate
covered only gate closure; including same-phase and macro/CPU relations gives
34 added AND2 gates (0.0005970944 mmÂ²) and 154 external binary joins. Sampled
event equations survive 1,000,000 transitions and 100 stop/wake trials; this
is not a physical controller or flow-equivalence result.

Qualified POR still needs a release proof. Under asserted reset, conservative
constant folding gives the required master value for 1,160 of 1,169 unreset
positive-master bits; nine first-stage GPIO/SCL/SDA sample bits remain unknown.
This can avoid blanket master resets only after the implemented controller graph
proves initialization traversal and reset/data-settle timing. No such adoption
or acceptance is claimed here.

Evidence: `build/desync-transform/{storage-r5,storage-r7,reference-r3}`,
`storage-by-bank-r7.json` and `review/{review-results,control-area-inventory,por-fold-results}.json`.
Both final mapping receipts pass with unchanged inputs. Independent source review
found no further defect in this storage-only scope. `ci-r2` passes 459 Python
tests, 268 Scala tests across 29 suites and all 6,976 reference-equivalence points,
with no changed inputs, missing outputs or skips. This includes eight storage
transformation tests, not whole-chip desync flow equivalence. The earlier `ci-r1`
was deliberately interrupted after the reset finding.
Production clocked/BD/Click RTL, assertions, deadlines and ABI are unchanged;
RTL diff is zero. Whole-chip transformation, delay sizing, flow equivalence,
controller qualification and physical acceptance remain open.


## Connected controller preparation (2026-11-10)

The approved closure/same-phase qualification and CPU rearm condition now connect
all ten generated banks. Controllers/joins/stop occupy 0.0099727936 mmÂ²; the
experimental mutex contributes its measured 0.0009878400 mmÂ² footprint. All 546
registered leaves survive the exact connectivity/protection audit; ordinary
storage and data remain unprotected. Nine first-sample masters gain the original
POR value, adding 0.0000395136 mmÂ² and no bits. Storage cell area is
0.2512318592 mmÂ², or 1.230457Ã—. The retired service-clock input has no leaf
consumers: periodic inventory is LF 78, with one separate SDA event FF. The
5,207 native storage/macro enable pins still need physical tree qualification.

Independent replay of actual assembled ports and binary joins passed 20
running/stop/wake seeds; primitive characterization passed 180 loaded schematic
cases. Review fixes preserve the actual N-to-request dependency, report CPU
capture on A separately, and bind recipe constants as literal bits. These are
ordering/sample checks, not flow equivalence, minimum-pulse or metastability
qualification. Final `connected-map-r4` reproduces the stated area and passes
the protection/clock audit. `ci-r1` passes 466 Python tests, 268 Scala tests
across 29 suites, and all 6,976 reference-equivalence points. Both receipts
have no changed inputs or missing outputs. The reference self-comparison is
not generated-chip flow equivalence. The broken primitive control fails with
`DESYNC_PRIMITIVE_STATE` as required; its failure evidence is retained.

A data-only preparation preserves the graph (229 added buffers, two ties,
30 equivalent resizes), but its final SS/hot report contains **104 slew
violations**. The earlier zero-violation statement read the wrong preparation
result; r5 and its timing scans are diagnostic, not accepted timing evidence.
Preliminary
Q-to-D maxima span 5.676â€“117.861 ns at SS/hot, before launch, setup, controller,
join and tree costs. They are **not bank delay bounds or cycle times**. No physical
delay count is published from them. Loaded delay sizing, actual enable/ACK and
POR release, slow-corner throughput, flow equivalence, full-chip area, repaired
ratio and routed qualification remain open. The mapped headroom is 0.0157432061
mmÂ²; it is a limit, not a forecast of the finished result.

Failed experiments retained: `connected-map-r1` exposed a cell/net namespace
collision (fixed centrally); data-repair r1/r2 left the POR fanout unrepaired;
r3 used a mismatched escaped macro name; r4 cleared electrical checks but lost
constant-net assignments in the writer. The final data-only r5 uses the existing
tie-cell preparation and passes exact graph comparison, but does not clear
electrical checks. It does not establish controller-connected electrical closure. Evidence is under
`build/desync-network/` (maps, primitive samples, independent replay, and
`data-repair-r5`/`data-proof-r5`).

## Loaded preparation and budget stop (2026-11-10)

C-element Boolean factoring removes one heavily loaded feedback input; stronger
same-function S-controller request drivers clear the sampled electrical envelope.
The fresh ordinary Yosys/ABC map reproduces the factoring experiment; a subsequent
exact `_2` to `_4` native-driver resize gives 0.5998603520 mmÂ². The preserved
native graph has 858 protected cells. Datapath/storage protection is forbidden.

Parent/reset drivers and balanced enable trees give 0.6562813824 mmÂ² before
matched lines and wire RC. All five global electrical reports have zero rows;
the separate conservative envelope covers all 857 combinational native leaves
at actual complete loads and every library slew knot in the admitted 0.02â€“2 ns
range. The mutex is separate. This is preparation, not routed electrical closure
or transparent-storage slew qualification. Exact graph preservation passes.
Independent sink enumeration covers 5,207 native pins and 79 excluded pins
(LF 78, SDA 1), including exclusive SRAM final drivers. Removing an entire tree
is detected; the former report-only inventory incorrectly accepted that mutation.

The conditional native campaign resolves 21,820 local min/max samples. Real
feedback SPICE passes 180 ordinary primitive cases and 480 earliest-return cases
plus 240 crossing probes. The return tests reverse an input mid-ramp at first
30/70% acknowledgement recognition; direct waveforms verify the complete hold
window at <=20 ps steps. A broken keeper fails as required. These are finite,
zero-wire samples, not mismatch, noise, timestep-convergence or 1-FIT evidence.

The folded next-state proof covers all 2,994 actual generic Q bits and 87 SRAM
input observations, proving 3,013 simplified equivalence points. Five actual-chip
controls detect a changed data bit, reset, work gate, controller ACK/alias and SRAM
input. This is ideal-cycle equivalence, not asynchronous per-register flow
equivalence. No clocked/BD/Click RTL, oracle or deadline changed.

Bank analysis restores removed native input capacitance and reports actual
storage/tree arcs and worst-constraint-slack paths at both input-slew endpoints.
Independent review found a real distinction: a selected TT CPU-to-Fabric
0.909628 ns Q-D span misses a 0.866028 ns alternative. Those samples must never
be used as pure segment extrema. OpenSTA's latch max-delay exception references
opening, not closing/setup. Closing-edge corrections, transparent D-Q slew,
the falling enable qualifier, all hold/pulse paths and the absolute 5 ms POR
recurrence remain open. The ten-delay topology supplies the needed causal
frontiers; this is not a request for another controller.

### Area-only trial: not adopted

An exact hard-cell insertion into the matched mapped netlist adds ten loaded
NAND4/MUX lines: 370 units plus ten reset drivers, with every old data/storage
cell unchanged. Counts are ADC 25, Control 34, CPU 45, Fabric 67, falling 6,
I2C 22, power 37, program 37, RAM 30 and time 67. All five-corner loaded line
measurements meet the **provisional component-based envelope** used by this
experiment; they do not establish complete bank timing or necessary minimum
counts. Reset flush/release remains unqualified. Production `desync-delays.json`
is still empty and production recipe resolution still fails.

| Cell class, mmÂ² | Pinned clocked | Ten-line trial |
|---|---:|---:|
| Storage | 0.2041777472 | 0.2512318592 |
| Ordinary buffers/inverters | 0.0078675968 | 0.0094481408 |
| Other ordinary logic | 0.3197879552 | 0.3242244544 |
| Controllers and joins | 0 | 0.0139680576 |
| Experimental mutex | 0 | 0.0009878400 |
| Matched-line trial | 0 | 0.0187909120 |
| Total | 0.5318332992 | **0.6186512640** |

The trial exceeds the 0.6116082941 mmÂ² mapped limit by **0.0070429699 mmÂ²**.
Its control share is **5.4549%**, above 5%. This deliberately failed area run is
retained. No accepted repaired-plus-tree or slow-corner throughput ratio exists.
Per the user's stop rule, further architecture/size changes wait for a decision:
keep the limits and test consolidating Fabric/time/power (estimated saving
0.007â€“0.010 mmÂ², unmeasured), or explicitly allow prototype ceilings of 1.17x and
5.5%. The latter would not qualify the outstanding timing or reliability work.

Fresh independent review found no remaining blocking defect in this diagnostic
checkpoint after the sink and timing-scope fixes. Full CI passes 474 Python
properties and 268 Scala tests across 29 suites, including boot, earliest I2C
status, SRAM, sleep and reset. The reference self-comparison proves 6,976 points;
it is not generated-chip flow equivalence. A final Python-only gate passes all
474 properties after a whitespace-only Tcl cleanup. Both CI receipts have no
changed inputs or missing outputs. Evidence is under `build/desync-complete/`: `connected-map-r2`,
`connected-rebind-r4`, `electrical-r12`, `leaf-envelope-r3`, `transitions-r9`,
`primitives-r4`, `early-return-r7`, `early-return-validation-r1`,
`early-return-broken-r2`, `fold-r7`, `fold-controls-r1`, `tree-audit-r3`,
`bank-segments-r12/r13`, `line-area-trial-r3`, `review/`, `ci-r1`, and
`ci-python-final`.

Failed experiments retained: initial repair passes exposed missing reset drivers,
writer aliases and overloaded keeper outputs; folded-proof preparation exposed
helper-name and Q-alias coverage errors; early-return probes exposed a clamped
return and incomplete waveform-window checks; bank-load fixtures needed complete
Liberty syntax/thresholds. A fast-slew exploratory receipt rejects a concurrent
registry edit. The final diagnostic bank runs have unchanged inputs and complete
outputs. None of these failed runs supplies production sizing.

## Approved 1.20x mapped budget and data-path extrema

The user explicitly raised the mapped ceiling after `291d731`. The maximum is
now 0.6381999590 mmÂ², leaving 0.0195486950 mmÂ² above the unchanged ten-line trial.
The history guard permits only this mapped-budget transition from the approved
parent; later loosening or a change to another limit still fails. The separate
5% control-share ceiling remains unchanged and the trial still exceeds it.
`area-recheck/area.json` recomputes the same netlist and records that single
remaining area-gate failure. No circuit, stored bit, delay count or oracle changed.

The previous worst-slack query could miss the fastest Q-to-D path because clock
arrival and latch aperture affected ranking. The new optional data-only view
replaces actual Q pins with equal-arrival ports and actual D/control pins with
equal-required-time ports. Zero required time avoids float cancellation from a
large artificial budget. This is an analysis transform, not added hardware.

Independent inventory and graph checks cover 5,307 Q and 5,367 D/control pins,
including SRAM A/D/CEN/GWEN/WEN, with 20,237 surviving ordinary cells unchanged.
All 13,158 removed input loads are restored across 6,359 live nets. Registry and
Liberty inventories define permitted removals; caller-supplied lists cannot
authorize deleting ordinary logic. STA reachability is checked separately for
min and max, against the actual net graph. Missing endpoints, loads, paths or
storage counts fail.

Both 0.02 ns and 2 ns Q-slew samples pass at all five corners: 1,760 nonempty
min/max results and 7,060 explicitly empty pairs. The longest sampled data cones
are power.S to Fabric.M (116.167641 ns), power.S to time.M (115.186310 ns), and
Fabric.S to CPU.M (70.450470 ns), all at SS/hot. These are zero-wire combinational
segments, not cycle times, continuous slew envelopes or composed timing margins.
Transparent-latch slew, closing setup, source retention/hold, pulse widths and
reset distribution remain mandatory before sizing adoption.

The actual-chip delayed-arc control moves a TT CPU-to-Fabric path from 36.372131
to 56.054977 ns. Endpoint/load/ordinary-cell deletion controls reject their
mutations. Changing the analysis period from 1,000 to 333 ns leaves every result
and disconnected-pair inventory unchanged at all five corners. Full CI passes
479 Python properties and 268 Scala tests across 29 suites, including boot,
earliest I2C status, SRAM, sleep and reset. The reference self-comparison proves
6,976 points; this does not establish generated-chip flow equivalence. Final
measurement, control and CI receipts have no changed inputs or missing outputs.
Fresh independent review findings were fixed; source review has no blocking
findings for this diagnostic scope. Evidence: `build/desync-budget120/`, including
`data-segments-fast-final`, `data-segments-slow-final`, `controls-final-r3`,
`area-recheck` and `ci-final`.

Failed experiments retained: the initial uncached Liberty scan was stopped for
runtime; the first data run retained a large artificial timing budget, replaced
after review identified float quantization; the first delay-control attempts
used an unsupported annotation command and unescaped SDF names. Final controls
use OpenSTA's SDF input with escaped mapped instance names.

## Direct I2C handoff: compose before adding hold cells

`measure_desync_handoff.py` starts both hold arms at the receiver's actual A
output: its closing tree, and the sender's ACK/reopening tree. It preserves
the repaired graph and complete pin loads, independently enumerates actual
latch sinks, and compares physically paired Q/D bits. This avoids combining
unrelated extrema from isolated controller and tree measurements. The existing
B equation requires ACK low before publication; the measured ACK rise therefore
belongs to the current steady cycle, not retained initialization state.

All 347 direct I2C M-to-S pairs pass at five corners, six root slews and both
data polarities: **20,820 cases, minimum +0.793638 ns** with a 1.2 late derate.
Maximum scoped pin slew is 1.595057 ns. Changing the analysis period from 1,000
to 333 ns leaves every row identical. Annotating the actual closing inverter
with 10 ns makes every case fail: **âˆ’11.046344 to âˆ’7.279423 ns**. The expanded
report shows the intended 12 ns derated arc. The independent-extrema alarm does
not by itself justify an added hold cell or delay count. **The +0.794 ns margin
is conditional STA evidence; physical hold qualification requires a full-feedback
minimum-transition bound.** Keeper feedback can reinforce reopening faster than
the static-feedback model; retained finite SPICE samples do not close that bound.

Area, storage and RTL are unchanged. A fresh inventory of the provisional line
trial still gives **1.163243x mapped**, **1.230457x storage area** and **5.4549%**
control share; only the control-share budget fails. This is not an adopted map.
Production delay policy stays empty. Setup, reverse/same-phase handoffs, gated
qualifiers, CPU and SRAM edge classes, pulses, initialization/reset, continuous
slew bounds and routed RC remain open. Independent review found and fixed a
route-list omission that could hide paired sinks, and timing annotations now
fail closed on warnings. Final evidence is `build/desync-handoff/{final,
period-final,late-final,area-recheck,ci-final}`. Full CI passes **486 Python
properties and 268 Scala tests across 29 suites**, including boot, earliest I2C
status, SRAM, sleep and reset. The reference self-comparison proves 6,976 points;
it is not generated-chip flow equivalence. Final run receipts have unchanged
inputs and complete outputs; the deliberate late-capture run retains fail status.

Failed experiments retained: independent extrema produced a pessimistic I2C
hold alarm; the first mutation used an unsupported command, then unescaped
dots/slashes caused ignored SDF annotations. The corrected control fails for
the intended timing reason. No failed or ignored mutation qualifies the design.

## Full-feedback I2C retention

The keeper-cut STA result is now supplemented by transistor-level runs retaining
the actual controller, ACK/enable trees and all 347 latch pairs: 756 cells.
Source D is an explicit timing frontier; cuts restore the original pin load on
any live net. The independent graph review accounts for all 2,301 live input
loads, including 1,195 omitted/cut pins represented by Liberty capacitance.
Both keepers remain connected. A legal preceding handshake establishes the
retained state before every source D changes while its master is closed.

All **20 corner/slew/polarity cases pass**, or 6,940 paired retention checks.
Every master reuses its data and every slave retains the old value. The complete
return window also rejects early or repeated threshold crossings at every
enable leaf and controller A/B/N. The minimum raw Q50-to-closing-E50 separation
is **0.393105 ns**, at FF/cold with a 2 ns physical 30â€“70% input slew. This is
**not a qualified hold margin** and is not comparable to the prior conditional
STA slack: it contains neither Liberty aperture subtraction nor mismatch derating.
Actual receiver-A waveform admission, continuous envelopes, external dynamic
loads, pulses, reset and routed RC remain open. Production sizing stays empty.

Reducing the maximum timestep from 0.2 to 0.02 ns at FF/cold, fast input slew,
for both polarities changes all 141 controller/enable threshold crossings and
347 source-data crossings by at most **1 ps**, at reported measurement precision.
Delaying only the receiver inverter's analysis input by 10 ns corrupts all
347 receivers and fails `FEEDBACK_DATA_RETENTION`, while every source reuses.
Independent review fixed an incomplete observation window and an insufficient
ACK-frontier check; the final code, inventories and evidence have no blocking
review findings. No circuit, area, storage, delay count, oracle or deadline changed.

Evidence is `build/desync-feedback/{final,fine-final,convergence-final,late-final,
area-recheck,ci-final}`. Successful measurement receipts have unchanged inputs and
complete outputs; `late-final` deliberately retains fail status. Exploratory
full-bank prehistory initially left synchronizer-chain inputs connected; explicit
source-D frontiers corrected that fixture limitation. The first campaign was
stopped and its failed receipt retained while review findings were fixed.
Full CI passes **492 Python properties and 268 Scala tests across 29 suites**,
including unchanged boot, earliest I2C status, SRAM, sleep/wake and reset checks.
The 6,976-point reference self-comparison passes. These regression results do
not establish generated-chip flow equivalence; that acceptance remains open.

## Retained work-gate return ordering

The actual storage-clock inventory finds nine gates: seven ordinary S gates,
CPU capture on master.A, and falling.M. Eight use the retained `enabled` latch
in falling.M; falling.M uses the separate `previous` latch in power.S. Each
fixture preserves the actual qualifier controller and its complete ACK join and
closed-input routes, keeper feedback, qualifier latch, and clock/enable trees.
Normal gates use target.A rising; CPU uses master.A falling and the real A-to-N
closure path. Other native outputs are explicit timing frontiers with their
actual reset markings. External omitted loads remain inventoried pin capacitance.

This is a closing/order check only. Qualifier setup before opening, gate-output
minimum pulse widths, initialization/reset, continuous-slew and mismatch bounds,
dynamic external loads and routed RC remain open. No guard, storage, circuit,
oracle or deadline changed. The independent review exposed an inventory hole
that could hide an unexpected gate type; every actual storage clock must now
reach a native output or an explicitly traced LF/SDA root. Cyclic ACK joins also
fail instead of being mistaken for shared subtrees. Multiple gates from one
controller fail explicitly rather than overwriting a fixture.

All **180 cases pass**: the live nine-gate inventory, five corners, physical
30â€“70% input slews of 0.02 and 2 ns, and both qualifier polarities. The minimum
sampled qualifier/clock input-order separation is **1.943307 ns**, at CPU,
FF/cold, 2 ns slew, qualifier 0â†’1. Reducing the maximum timestep from 0.1 to
0.01 ns gives **1.943065 ns**. Across both slews and polarities at that corner,
every reported threshold crossing changes by less than **0.907 ps**, and the
separation by less than **0.243 ps**. This is not a Liberty hold margin or a
physical bound. Delaying only the CPU gate-clock branch by 10 ns produces a
**7.840 ns** unwanted pulse above half supply and correctly fails the checker.

Independent source and evidence review confirms the complete case inventory,
load/frontier scope, actual feedback, negative control and timestep comparison.
Successful campaign receipts have unchanged inputs and complete outputs; the
deliberate fault retains fail status. Evidence: `build/desync-gates/{final,
fine-final,late-final,area-recheck,ci-final}`. The fresh area inventory remains
**1.163243x mapped**, **1.230457x storage area**, and **5.4549% control share**;
the separate 5% control ceiling still fails. Production delay sizing remains
empty. Early fixtures retained the wrong reset marking at other native frontiers;
the corrected prelude uses each actual controller's marking. No failed fixture
is used as circuit evidence. The first CI run was intentionally stopped before
the final duplicate-target coverage fix; its failed receipt remains in `ci-r3`.

The final full CI gate passes **498 Python properties and 268 Scala tests across
29 suites**, including unchanged boot, earliest I2C status, SRAM, sleep/wake and
reset. Its inputs are unchanged and all outputs are present. The 6,976-point
reference self-comparison passes; generated-chip flow equivalence remains open.
Opening/setup must next compose the two actual qualifier paths (`enabled` and
`previous`) with their shared controller frontiers, rather than substituting an
unrelated whole-bank maximum.

## Conditional work-gate opening

The existing gate tool now checks opening from the qualifier owner's A
transition, preserving the target's feedback, ACK/closed-input or CPU
`riseAllowed` path, qualifier latch and actual trees. Its upstream inventory
finds two chains: demand logic â†’ falling.S â†’ falling.M `enabled`, and that
`enabled` value â†’ power.M â†’ power.S `previous`. The three intervening data
links are direct Q-to-D wires; ordinary demand logic is a separate frontier.

All **360 opening cases pass**: nine actual gates, five corners, two data
polarities and independently varied 0.02/2 ns physical data and frontier slews.
D is admitted near its Liberty setup aperture, then the final actual D/E
waveforms are checked. Minimum fixture setup headroom is **0.198727 ns**;
this is a chosen stimulus condition, not a measured upstream timing margin.
The smallest sampled settled-qualifier to opening-clock separation is
**0.626009 ns**, at CPU, FF/cold, 2 ns frontier slew, 0.02 ns D slew, rising D.
All other gates exceed **2.152316 ns**. The reported D arrival is a tested
condition, not a latest-safe-arrival limit or a continuous envelope.

At a 0.01 ns maximum timestep, the limiting case gives **0.626309 ns**.
Across all eight CPU FF/cold cases, every reported threshold crossing changes
by less than **1.726 ps**, and the separation by less than **1.493 ps**.
A 5 ns late-D control misses capture and fails; a separate checker mutation
keeps setup valid but delays the qualifier, independently failing ordering.
Review found a gap in observation of the preceding CPU pulse. The final
checker covers the entire prior return, requires qualifier reuse after clock
closure and rejects injected pulses in both data polarities. An early pilot
changed D before that prior return completed; its failed evidence is retained,
and its corrected prelude is not a circuit change.

Evidence is in `build/desync-opening/{final-<corner>,fine-final,late-data-final,
area-recheck}`. Fresh area accounting remains **1.163243x mapped**,
**1.230457x storage area** and **5.4549% control share**. The separate 5%
control ceiling still fails. No RTL, storage, guards or physical counts changed.
Production delay sizing remains empty. The next obligation is to compose
actual upstream arrival and retention with these measured apertures; minimum
pulses, reset, continuous slew, mismatch, routed RC and whole-chip flow remain
unqualified.

The **180 return-ordering cases** also pass with every result unchanged from
the previous batch (minimum **1.943307 ns**). Independent review reproduced
the opening coverage/minima and timestep comparison, checked the receipts and
confirmed the prior-pulse fault is rejected in both polarities. Return evidence
is retained in `build/desync-opening/return-final`.

The final full CI gate passes **504 Python properties and 268 Scala tests across
29 suites**, including unchanged boot, earliest I2C status, SRAM, reset and
sleep/wake. `build/desync-opening/ci-final` records unchanged inputs and complete
outputs. The reference self-equivalence harness passes; generated-chip flow
equivalence is still open.

## Explicit prototype budget approval

After `b2cac0f`, the user approved **1.17x mapped area** and **5.5% combined
control/join/delay/mutex share**, retaining every other limit. This latest
decision tightens the preceding 1.20x mapped ceiling and raises the preceding
5% control ceiling. Repaired plus trees remains 1.20x, architectural bits
exactly 1.00x and storage area 1.25x. The approval permits prototype continuation;
it does not establish timing, reliability or production qualification.

Reassessment of the unchanged ten-line trial now **passes the mapped,
architectural-bit, storage-area and control-share checks**:
**0.6186512640 mmÂ² / 1.163243x**, storage area **1.230457x**, and combined
control share **5.4549003%**. Mapped headroom is **0.0035936961 mmÂ²**. Evidence
is in `build/desync-prototype-budget/area-recheck`; earlier failed receipts
remain valid records of the former limits. No RTL, cell count, storage, delay
recipe or physical measurement changed. Production delay policy remains empty.
The complete repaired-plus-trees comparison remains unavailable.

The history check binds this approval to parent `b2cac0f` and the prior
1.20x/5% values, including before and after commit. A control-only increase
must resolve its approval even when mapped area decreases. The exception
cannot increase another limit or be replayed after a later tightening; the
earlier mapped-only approval is tested separately.

Full CI passes **505 Python properties and 268 Scala tests across 29 suites**,
including unchanged boot, earliest I2C status, SRAM, reset and sleep/wake;
the reference self-equivalence harness also passes. Evidence is retained in
`build/desync-prototype-budget/ci-final` with unchanged inputs and complete
outputs. Independent review checked the approval scope and area evidence.

## Contract before whole-chip integration

# Generated bundled-data MCU contract

The clocked RTL is the sole source. Generate ten four-phase banks from its
normalized netlist; no copied RTL, shared fast oscillator, payload copies,
transaction owners or ABI changes. Old BD and Click remain behavioral oracles.
The bank map and primitive registry are authoritative; history and measurements
are in [the ledger](desync-ledger.md).

## Storage and ownership

Banks are CPU, Fabric, Control, program, RAM, I2C, ADC, time, power and falling.
Ordinary rising-edge registers become M/S latch pairs. The 42 falling-edge bits
use S/M pairs. The approved CPU exception retains 591 FFs, captured on master.A;
latch enables use N. Work gating remains per register, including mixed-lifetime
power state. Falling captures use the existing `previous` qualifier.

Preserve every architectural bit, reset value and lifetime. Slaves retain the
original reset; masters remain plain except where reset analysis requires a
defined value. Both halves retain independent application/wake resets. Nine
first-sample GPIO/SCL/SDA masters keep POR values. No extra data state is allowed.
Actual generic Q pins and SRAM inputs define ideal-cycle equivalence coverage;
ownership aliases alone are insufficient.

## Controllers, boundaries and reset

Each bank has two semi-decoupled controllers, witnessed predecessor joins and
one matched delay. Existing A/B keepers implement request-return causality,
one-sided receiver closure and same-phase qualification. B responds to the
actual enable N. The approved CPU readiness/publication joins enforce rearm.
The C-element candidate is `Q_next = ab + Q(a+b)`, with one feedback input.
Protection covers native control cells, never ordinary data or storage.

The marked graph and assembled event replay screen ordering and stop drainage.
They do not prove physical leaf timing, pulse widths or whole-chip flow
equivalence. Mixed-edge transparent paths must include both falling latches,
their data/enable arrivals and the `previous` input of the enable AND.
For the affected M banks, the joined power/program/RAM S requests supply a
common launch frontier for the existing delay; no additional controller is
needed. This causal argument still needs numerical timing closure.

Deep sleep stops the graph at power.M through one persistent stop request and
one filtered mutex. Operational stop never resets a live grant. Controls reset
from raw `resetHold/unsafe_supply`; using qualified POR would deadlock the
power bank that advances the qualifier. Architectural POR remains qualified.
The 100,000-count qualifier must provide at least **5 ms** at the fastest
measured recurrence, including initialization and reset distribution.

The experimental mixed NAND4/MUX delay resets every unit in parallel. Prove
complete flushing before controller release, distributed reset skew, minimum
assertion, and the earliest subsequent request. Its counted recipe remains
unavailable as a production binding.

| Remaining clock/input | Obligation |
|---|---|
| LF watchdog/timebase | Independent time/recovery; preserve Gray crossing and skew limits |
| SDA event FF | Preserve START frontier and SCL aperture; synchronize through existing stages |
| SRAM CLK | Local port control; preserve launch/access order, setup/hold, access and pulse limits |
| GPIO/I2C synchronizers | Original stages as latch pairs; bound sampling interval and MTBF; active bus keeps sampling live |
| SPI MISO | Preserve source-synchronous sampling and the external ADC aperture |

## Timing and verification

Size relative bank delays from same-corner STA with actual loads/slews and
**1.2**, the user-specified engineering allowance, not measured mismatch.
No RTL delay constant or fallback formula supplies a count. Absolute obligations
are SRAM and controller/latch pulse/aperture limits, POR hold and mutex filtering.
Simulation bounds must come from measured bank envelopes. Production sizing
fails closed while those envelopes are incomplete.

Repair electrical violations before accepting timing. Native outputs have
parent drivers; enable trees have at most 16 loads per branch, equal depth and
exclusive final SRAM drivers. Independently enumerate every actual sink;
excluding only LF and SDA must leave exactly the reported native inventory.
Keeper feedback stays intact. Routed min/max RC, coupling and reset distribution
remain mandatory; zero-wire margins below 100 ps are untrusted.

Conditional primitive queries retain removed feedback capacitance. The data-only
bank view cuts every storage Q/D frontier and restores all removed input loads.
Equal zero arrival and required times give pure combinational extrema at each
sampled Q slew, independent of clock-tree skew and analysis period. The ordinary
graph and every frontier/load are audited. These finite samples are not a
continuous slew envelope. Compose closing-edge/setup corrections explicitly and
propagate transparent D-to-Q slew through downstream logic. The original
worst-slack bank samples remain diagnostic; neither view alone closes setup/hold.

Direct latch handoff hold starts at the receiver's actual A rise. Propagate that
same event through its closing tree and the sender's ACK/reopening tree, comparing
each physical Q-to-D pair with its loaded E-to-Q and hold arcs. Source B required
ACK low before publication, so this rising ACK belongs to the current cycle.
I2C M-to-S passes this sampled conditional STA check with a 1.2 late derate.
Fixed keeper-feedback inputs do not establish a minimum reopening bound:
real feedback can reinforce the transition. Physical hold qualification needs
a full-feedback minimum-transition envelope. The direct-handoff schematic check
retains the actual controller, enable/ACK trees and every paired latch; source D
is the timing frontier, with its removed load restored. Both data polarities must
reuse the source while every receiver retains the old value. All enable and
A/B/N return edges are checked across the complete retention window. External
omitted sinks remain lumped pin capacitances. Finite PVT/slew samples and injected
capture-skew failures do not establish continuous, mismatch or routed bounds.
Initialization, minimum pulses, reverse handoffs and routed RC remain separate.
Lengthening a primary request delay does not repair this immediate return path.

Work-gate return checks start at the actual target A transition, preserving the
qualifier owner's complete ACK join and closed-input paths, feedback, latch and
trees. Normal S gates and falling.M close from A rising; CPU capture closes from
master.A falling, including the real A-to-N inverter in its closure dependency.
Gate clock must fall before its retained qualifier changes, without a new output
pulse. Independently enumerate every storage clock; only traced LF/SDA roots are
excluded. This return check does not establish qualifier setup before opening,
clock pulse widths, reset behavior or a continuous/mismatch/routed timing bound.
Conditional opening checks retain the target's feedback and use the qualifier
owner's actual A transition as the common frontier. D arrives near the Liberty
setup aperture; final D/E waveforms must satisfy it before checking qualifier
settling against gate opening. Vary D and frontier slew independently. This
measures a tested arrival requirement, not the latest safe arrival. The upstream
`enabled`/`previous` latch links, demand logic and data retention still need
composition; an unrelated whole-bank maximum cannot replace those exact paths.

Required checks: generated-chip per-register flow equivalence; folded
next-state/SRAM-effect proof; unchanged boot, I2C earliest status, SRAM, ADC,
reset, firmware and sleep/wake suites; stop/wake races and POR in flight.
Throughput uses `events/window * worst firings/event * slowest cycle < window`.
I2C remains **400 kHz SCL**, tested against the existing 3.2/20 MHz reference
service points. No desync throughput margin is yet claimed.

## Acceptance boundary

The pinned reference is **0.5318332992 mm² mapped**, **0.5915383488 mm² after
repair/placement/CTS**, 2,977 architectural bits and 0.2041777472 mm² storage.
After `b2cac0f`, the user approved prototype ceilings of **1.17x mapped** and
**5.5% control/join/delay/mutex share**, superseding 1.20x and 5% respectively.
Unchanged limits are repaired plus trees **1.20x**, architectural bits **1.00x**
and storage area **1.25x**. This approval does not qualify production adoption.

Current inventories and area-only trials are in the ledger. The trial fits
the mapped/storage/control budgets; the repaired-plus-trees comparison remains
unavailable. Provisional counts are not
accepted timing; production delay policy remains empty. Neither budget approval
nor diagnostic measurements qualify adoption.

The experimental mutex footprint is 0.00098784 mm². Its **1 FIT per MCU** target
still needs a justified reliability model, arbitration rate, variation/noise and
extracted evidence; finite SPICE samples do not qualify it. No whole-chip timing,
flow, throughput or tape-out acceptance is claimed.
