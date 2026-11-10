# Desynchronization ledger

Logic excludes the same three fixed SRAM macros. Ratios, not absolute area
targets, govern adoption. Old BD/Click physical results do not qualify desync.

| Batch | Flat mapped logic / clocked | Storage bits | Delay/controller/mutex | Repaired + CTS | RTL diff vs clocked | Status |
|---|---|---|---|---|---|---|
| Phase 0 tools/reference | 0.5318332992 mm² / 1.000× → 1.000× | 2,977 → 2,977 | 0 mm² / 0% | 0.5915383488 mm² / 1.000× | 0; no desync RTL | Verified and independently reviewed; stop after Phase 0 |

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
0.7098460186 mm² repaired plus trees, and 3,125 storage bits. These are limits,
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

## Digital prototype verified — physical Phase 1 acceptance remains open

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
