# Desynchronization ledger

Compare logic excluding the same three SRAM macros with the pinned clocked
reference: **0.5318332992 mm² mapped**, **0.5915383488 mm² repaired + CTS**,
2,977 architectural bits, 0.2041777472 mm² storage. Accepted prototype ceilings:
1.17× mapped, 1.20× repaired + trees, 1.00× architectural bits, 1.25× storage
area and 5.5% control/delay/mutex share. Complete physical acceptance remains open.

One short row per commit. Earlier detailed evidence and failed experiments are
archived in [the migration log](history/desync-log.md); they are not current qualification.

| Commit | Change | Mapped ratio | Storage / control | Evidence and limits |
|---|---|---|---|---|
| `2c72874` | Reference and Phase 0 tools | Reference 1.000× | 2,977 bits | Repaired + CTS denominator established |
| `d553528` | Digital oscillator prototype | Historical | Historical | Superseded and removed |
| `6061fa2` | Deterministic export | Reference retained | Unchanged | Repeated RTL/port exports agree |
| `b82aa11` | Multi-bank/CPU exception exploration | Incomplete | CPU remains FFs | No complete chip result |
| `2fbc971` | Mixed-phase graph and causal controllers | Incomplete | No payload copies | Abstract graph only |
| `c267af5` | Experimental mutex layout | Incomplete | 0.00098784 mm² mutex | DRC/LVS; no 1 FIT claim |
| `a983b56` | Mutex views and reliability target | Incomplete | Unchanged | Qualification remains disabled |
| `e869a43` | Generated storage | 1.099954× without controls/delays | 2,977 architectural; 5,283 FF/latch bits | Storage-only map |
| `6092427` | Connected controls | 1.120398× without delays | +198 keepers | Ideal-cycle fold, not chip simulation |
| `291d731` | Loaded controls and provisional lines | 1.163243× | 5.4549% control/lines/mutex | Failed then-current budget; timing incomplete |
| `b26bfd7` | Approved area ceiling; data segments | 1.163243× unchanged | Unchanged | Conditional STA, not whole-chip timing |
| `9c8e195` | I2C direct handoff | Unchanged | Unchanged | Conditional local timing only |
| `fef29f5` | I2C feedback retention | Unchanged | Unchanged | Local SPICE only |
| `47c05d3` | Work-gate return | Unchanged | Unchanged | Local SPICE only |
| `b2cac0f` | Work-gate opening | Unchanged | Unchanged | Local SPICE only |
| `7b55fd6` | User-approved prototype ceilings | 1.163243× under 1.17× | 5.4549% under 5.5% | Approval does not qualify timing |
| `b31ffa6` | Generated boot/transfer/stop tests; Fabric/time/power area trial | Main 1.163243× unchanged; trial **1.143261×** | Main 5,283 FF/latch +198 keepers unchanged; trial +124 keepers, 3.8548% control share | 4 boot cases +5 randomized replays pass; selected slow suites 7/9 pass, two unchanged failures; graph 358.9 ns misses I2C sampling budget; reviewed; merge not adopted |
| Throughput diagnosis | Explicit-policy replays, cumulative repairs, direct tick-comparison trial | Main **1.163243× unchanged**; combined eight-bank trial **1.152111×**, not adopted | Main unchanged; trial 5,283 FF/latch +124 keepers, 3.8252% control share; RTL diff **0** | Both slow failures retained; trial data path **119.897 → 79.632 ns**, 1,531-point two-state proof; 513 Python/268 reference Scala pass; eight-bank SoC/stop replays pass; evidence `build/desync-followup/` |

The eight-bank experiment maps ordinary logic/storage/controllers to
0.5944404032 mm². Inserting the existing provisional chain recipes (merged
bank uses the largest of the three prior counts) adds 0.0135838976 mm², giving
**0.6080243008 mm²**, down 0.0106269632 mm² from the ten-bank trial.
Storage area stays 0.2512318592 mm² (1.230457×). No repaired or routed ratio
exists for this experiment. Evidence: `build/desync-integration/merged-map` and
`build/desync-integration/merge-area.json`.

The direct tick-comparison experiment adds 0.0047065088 mm² to that merge
(total **0.6127308096 mm²**). Repaired logic with delay apertures still open is
**0.6435470272 → 0.648308416 mm²**; these are not completed repaired-chip ratios.
All five corners × two sampled Q slews improve after zero-wire electrical
preparation. Neither bank policy nor delay counts are adopted. Detailed numbers:
`build/desync-followup/direct-tick-compare/comparison.json`.

Work order: generated-chip behavior and register flow; trial-cycle/deadline
checks; bank-merge evaluation; then per-bank STA sizing. Local SPICE is paused.
Reference Scala passes must never be reported as generated-chip passes.

Checkpoint evidence: `build/desync-integration/{generated-slow-final.log,
final-replays,timed-graph-final-serial,ci-reference-final}`. Failures are
`BOOT_NOT_SLEEPING` (sleep residency) and `LOADER_COMPLETION_DEADLINE`.
Reference CI passed 268 Scala tests and reference equivalence; the final Python
properties passed 512 tests (`ci-python-reviewed`), with the strengthened timeout
control rerun separately (`timeout-reviewed.log`).
The [contract](desync-contract.md) lists unrun coverage and physical limitations.
