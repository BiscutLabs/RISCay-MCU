# Desynchronization ledger

Logic excludes the same three fixed SRAM macros. Ratios, not absolute area
targets, govern adoption. Old BD/Click physical results do not qualify desync.

| Batch | Flat mapped logic / clocked | Storage bits | Delay/controller/mutex | Repaired + CTS | RTL diff vs clocked | Status |
|---|---|---|---|---|---|---|
| Phase 0 tools/reference | 0.5318332992 mm² / 1.000× → 1.000× | 2,977 → 2,977 | 0 mm² / 0% | 0.5915383488 mm² / 1.000× | 0; no desync RTL | Verified and independently reviewed; stop after Phase 0 |
| Connected controller preparation | Storage-only 0.5849922624 → connected 0.5958650880 mm²; 1.099954× → 1.120398× pinned reference; **whole-chip ratio unavailable** | 2,977 architectural; 5,283 FF/latch bits + 198 control keepers | Controllers/joins/mutex 0.0109606336 mm², 1.83945%; delays unmeasured | Not measured | 0 | Ten banks connected; external delay apertures; no chip acceptance |
| Loaded control/distribution and area trial | 0.5958650880 → 0.5998603520 mm² before lines; cell-exact ten-line trial **0.6186512640 mm² / 1.163243x (FAIL)** | Unchanged: 2,977 architectural; 5,283 FF/latch + 198 keeper bits | Trial 0.0337468096 mm² / **5.4549% (FAIL)** | Zero-wire preparation 0.6562813824 mm², excluding lines; not the matched physical result | 0 | Electrical preparation and ideal-cycle proof; production sizing remains unavailable; budget decision required |

The mapped reference is the original clocked export, remapped with the pinned
Yosys 0.62/ABC and GF180 7-track libraries. Pre-placement repair is
0.5326608896 mm²; placement repair is 0.5683921600 mm²; CTS adds
0.0231461888 mm² to reach the table's total. No ordinary data/storage is
protected. Periodic sink inventory is service 539 + work 2,362 + LF 78 = 2,979,
including three SRAM clocks. The separate SDA event adds one nonperiodic pin.
All 2,980 pins are reached; graph preservation passes at preparation, repair,
placement and CTS. Five final PVT reports have zero slew/capacitance violations.

Physical settings are 1.94 × 2.53 mm, density 0.60, three north-edge SRAMs,
per-corner electrical limits and corrected nominal wire resistance. This is
placement-estimated RC, **not routed signoff**. The progress-fixed OpenROAD
binary has SHA-256
`20abaf17173bc8be06b658179920f739103279e54105b3c165dceab4c8ba00a1`;
the run receipt pins all other tool/library inputs. Reuse the same flow for the
eventual desync denominator comparison.
The current budgets therefore permit at most 0.6116082941 mm² mapped,
0.7098460186 mm² repaired plus trees. Revised storage limits are exactly
2,977 architectural bits and 0.2552221840 mm² storage cell area. These are limits,
not achieved desync measurements.

| PVT | Fast-region period requirement, ns, before 1.2 factor |
|---|---:|
| TT 25 °C, 3.3 V | 55.093433 |
| SS 125 °C, 3.0 V | 112.803410 |
| SS −40 °C, 3.0 V | 76.374889 |
| FF 125 °C, 3.6 V | 45.689070 |
| FF −40 °C, 3.6 V | 30.994888 |

These are STA requirements on the CTS netlist at zero wire RC, including
full- and half-cycle groups. The reference's 50 ns analysis period does not
close setup at every corner; electrical acceptance does not imply 20 MHz
timing closure. These are **not generator periods**. No actual
loaded chain exists yet; `desync-delays.json` remains empty, and missing entries
fail. No slow-corner I²C/ADC throughput margin is claimed. I²C remains 400 kHz
SCL, as confirmed by the user.

The fresh export maps to 0.5312120576 mm². Its 0.12% difference comes from unordered Scala `Set[Bool]`
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

Failed experiments retained: unsupported asynchronous FF SAT models → use
`clk2fflogic`; missing blackbox declarations/internal structural matching →
strict hierarchy plus ordinary `opt_merge`, with all equivalence points proved;
old OpenROAD repair-progress hang → pinned fixed build; blanket 2 ns data slew
and incorrect work-clock traversal (0.878861 mm²) → per-corner ordinary limits
and an explicit combinational generated-clock path. None qualifies the reference.

Phase 0 ended at the requested boundary. The GF180 mutex still lacks layout,
LEF and Liberty; its registry recipe is unavailable.

## Retired single-oscillator prototype (historical)

| Batch | Mapped logic | Ratio to clocked | Storage bits | Controller/delay/mutex area | Status |
|---|---:|---:|---:|---:|---|
| Copied ideal-clock region | 0.5318332992 mm² | 1.000× (region only) | 2,977 → 2,977 | Excluded; not measured | Digital tests pass; no physical Phase 1 acceptance |

The region map has 21,696 cells, three fixed SRAM macros and zero protected
ordinary cells. Its clock inventory remains 539 service + 2,362 work + 78 LF
sinks, plus one SDA-event sink. Service/work are external ideal clocks in this
measurement; no reduction in periodic sinks is claimed. Mapped whole-chip
headroom is 0.079775 mm², before the unmeasured generator. Repaired desync area
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
Both pass the original deadlines with randomized 50–55 ns loop delays. These
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
| Sort application-address decode before constructing hardware | Both 0.5318332992 → 0.5315501184 mm²; 1.000× → 1.000× (region only) | 2,977 → 2,977 | Generator excluded, not measured | Not rerun; Phase 0 remains a pinned pre-change baseline | Unchanged: +159 / −27 Scala lines |

Mapping a key set to Chisel `Bool` let identity hashes choose the OR-tree order.
Both implementations now sort integer addresses first. No state, ABI, reset or
clock changes; all nine functional files still match after package normalization.
The small common mapping change (−0.053%) is not a desync area saving.
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
| Retire oscillator copy; partition and CPU-FF preflight | Unavailable → unavailable | Reference 2,977; candidate unchanged by substitution / calculated 1.300158x → 1.230263x | Unmeasured; mutex allowance 0.001 mm² | 9 candidate / unmeasured | CPU-only candidate retained for qualification; no RTL conversion adopted |

Literal master/slave replacement costs 0.2654633408 mm² of storage against
0.2041777472 mm² clocked, exceeding the cap by 0.0102411568 mm². The CPU's 591
mapped plain FFs would save 0.0142709952 mm², giving 0.2511923456 mm² storage and
a 0.5788478976 mm² logic **substitution floor** (1.088401x). After the estimated
mutex allowance, 0.0317603965 mm² remains below the mapped cap for all other
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
area comparisons (mapped 0.5318332992 mm²; repaired/CTS 0.5915383488 mm²).
Both receipts have no changed inputs or skips. Independent review's phase/gate
inventory, protection-permission, unsupported-state and descriptor-bypass
findings are addressed. The checker still cannot qualify the unfinished MCU.
No clocked/BD/Click production RTL changed in this batch.

## Phase-aware graph and causal controller candidates

| Batch | Whole-chip mapped/repaired ratio | Architectural bits / storage area ratio | Control share | Banks / cycle time | Result |
|---|---|---|---|---|---|
| Opposite-edge bank; causal controller and CPU pair candidates | Unavailable → unavailable | No payload change; reference 2,977 / calculated floor stays 1.230263x | Whole-chip share unmeasured; ordinary pair 0.0002261056 mm², CPU pair including its two joins and output driver 0.0003314752 mm² | 9 → 10 / unmeasured | Abstract graph and schematic samples pass; physical bindings remain unavailable |

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
mutex still need area/timing accounting. The 0.5788478976 mm² substitution floor
and 0.001 mm² mutex estimate remain estimates, not a desync map.

Evidence: `build/desync-multibank/{partition-ten,graph-ten-r2}.json`,
`primitives-final-r1` (120 five-corner loaded schematic cases),
`primitives-final-negative` (expected `DESYNC_PRIMITIVE_STATE`), `ci-phase-r1`
(450 Python, 268 Scala across 29 suites, 6,976 reference equivalence points)
and `ci-phase-reviewed` (451 Python plus both pinned reference area comparisons
after the Python-only recipe update). Receipts have no changed inputs or missing
outputs. Independent review's phase, qualifier, constant-emission and reset-wording
findings are fixed. No production RTL, assertion, deadline or ABI changed.

Failed experiments retained:

- Nine mixed-phase banks: sampled S aperture 1.64–5.97 ns at SS/hot versus the reference's 12.63 ns half-cycle requirement; isolate opposite-edge state in bank ten.
- Simplified CPU controller: 50 fF publication loading stalls; output isolation restores sampled behavior but leaves about 15 ps at 50% crossings and −159 ps at conservative thresholds; restore the causal condition.
- Stronger keeper alone: `_2` remains marginal and `_4` worsens it; rejected. A buffered-delay experiment also remains unadopted.


## Experimental mutex layout

| Batch | Whole-chip mapped/repaired ratio | Architectural bits / storage area ratio | Cell area | Result |
|---|---|---|---|---|
| GF180D mutex layout and distributed extraction | Unavailable → unavailable | Reference 2,977 unchanged / calculated floor stays 1.230263x | 0.00098784 mm² outline, below the 0.001 allowance | Experimental; no mapper binding or chip RTL change |

The unchanged 46-transistor schematic now has a generated 28 × 35.28 µm layout.
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
0.334–1.325 ns, quiet handover is at least 0.891 ns and active-reset clearance
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
| Top-metal port access and scenario timing tables | Unavailable → unavailable | Reference 2,977 unchanged / calculated floor 1.230263x unchanged | 0.00098784 → 0.00098784 mm² | Experimental views; mapper binding remains unavailable |

OpenROAD could not access the original 0.4 µm Metal4 ports behind conservative
internal obstructions. Seven Via4 connections and 0.8 µm Metal5 landing pads fix
access within the same outline. The transistor circuit and Metal2–4 routes stay
unchanged. New foundry checks report zero violations across 649 categories; both
LVS engines match. The new nominal extraction contains 46 MOS, 304 resistors and
452 capacitors. Earlier RC results describe the earlier geometry, not these pins.

The macro LEF blocks Metal1–4 and exposes only verified Metal5 ports. The access
fixture connects five signals and explicit VDD/VSS straps with zero final router
violations. Its coarse global-route congestion is retained, not reported as a
full-chip routing pass. All 462 loaded-RC samples pass. The separate timing grid
passes 180 cases plus four half-step repeats; OpenSTA reproduces all 180 lookups.
Isolated 50%-threshold request propagation is 0.299–1.194 ns; input capacitance is
10.16–13.86 fF. Refinement changes are below 0.04 ps. These are scenario samples,
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
| Generated storage with CPU FF exception | Unavailable → unavailable; storage scaffold 0.5849922624 mm², 1.099954x pinned mapped reference | 2,977 → 2,977 / 1.230263x | Not measured as a chip | 10 / unmeasured | Storage-only map passes; complete controller adoption and POR initialization remain open |

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
| Mapped logic, mm² | 0.5864630464 | 0.5849922624 | 0.5369678720 |
| Storage area, mm² | 0.2543007488 | 0.2511923456 | 0.2041777472 |
| Architectural bits | 3,012 | 2,977 | 2,977 |
| Physical storage bits | 5,353 | 5,283 | 2,977 |

The matched normalized ratio is 1.089436x. The pinned 0.5318332992 mm² reference
still sets the unchanged ceiling; its ratio is 1.099954x. Under the normalized
input/naming path the paired reference is 0.0051345728 mm² higher than that pin;
the individual causes have not been isolated. Neither reference is replaced
silently. The scaffold has 0.0266160317 mm²
logic and 0.0040298384 mm² storage headroom, before omitted control, timing and
qualified-POR work. No repaired ratio is available for this candidate.

| Bank | Architectural bits, unchanged | Clocked storage, mm² | Candidate storage, mm² |
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
inventory estimates 0.0108311168 mm² for controllers, joins, stop and the
experimental mutex, excluding delays/drivers/trees. The initial 15-gate estimate
covered only gate closure; including same-phase and macro/CPU relations gives
34 added AND2 gates (0.0005970944 mm²) and 154 external binary joins. Sampled
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
all ten generated banks. Controllers/joins/stop occupy 0.0099727936 mm²; the
experimental mutex contributes its measured 0.0009878400 mm² footprint. All 546
registered leaves survive the exact connectivity/protection audit; ordinary
storage and data remain unprotected. Nine first-sample masters gain the original
POR value, adding 0.0000395136 mm² and no bits. Storage cell area is
0.2512318592 mm², or 1.230457×. The retired service-clock input has no leaf
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
Q-to-D maxima span 5.676–117.861 ns at SS/hot, before launch, setup, controller,
join and tree costs. They are **not bank delay bounds or cycle times**. No physical
delay count is published from them. Loaded delay sizing, actual enable/ACK and
POR release, slow-corner throughput, flow equivalence, full-chip area, repaired
ratio and routed qualification remain open. The mapped headroom is 0.0157432061
mm²; it is a limit, not a forecast of the finished result.

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
exact `_2` to `_4` native-driver resize gives 0.5998603520 mm². The preserved
native graph has 858 protected cells. Datapath/storage protection is forbidden.

Parent/reset drivers and balanced enable trees give 0.6562813824 mm² before
matched lines and wire RC. All five global electrical reports have zero rows;
the separate conservative envelope covers all 857 combinational native leaves
at actual complete loads and every library slew knot in the admitted 0.02–2 ns
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

| Cell class, mm² | Pinned clocked | Ten-line trial |
|---|---:|---:|
| Storage | 0.2041777472 | 0.2512318592 |
| Ordinary buffers/inverters | 0.0078675968 | 0.0094481408 |
| Other ordinary logic | 0.3197879552 | 0.3242244544 |
| Controllers and joins | 0 | 0.0139680576 |
| Experimental mutex | 0 | 0.0009878400 |
| Matched-line trial | 0 | 0.0187909120 |
| Total | 0.5318332992 | **0.6186512640** |

The trial exceeds the 0.6116082941 mm² mapped limit by **0.0070429699 mm²**.
Its control share is **5.4549%**, above 5%. This deliberately failed area run is
retained. No accepted repaired-plus-tree or slow-corner throughput ratio exists.
Per the user's stop rule, further architecture/size changes wait for a decision:
keep the limits and test consolidating Fabric/time/power (estimated saving
0.007–0.010 mm², unmeasured), or explicitly allow prototype ceilings of 1.17x and
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
