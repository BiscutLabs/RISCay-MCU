# Retained frame at Control ingress (11b1)

The command sender duplicated all 271 frame bits even though the selected native
frame bank already retained them. Each variant now sends a 108-bit metadata
header and borrows the frame through native Control acceptance and return.
The full native command remains 379 bits. Three POR-owned bits retain
the physical bank identity and pending retirement. The
[frame contract](../frame-admission-contract.md#11b1-borrow-the-retained-frame-through-native-control-acceptance)
defines logical dispatch D, clocked tag retirement R and physical bank return separately.

Digital verification and fresh independent review pass. Physical qualification of the new
bank-Q/selector/Host-mask/Join path remains open. This item does not migrate the
remaining Services scheduler, descriptor queue or frame head receipts.

## Corrected BD return topology

The first candidate failed the unchanged `READY_BY_THIRD_NEXT_A` check at a
1 ms service period (`capture-r5-bd`). Serializing Control's full command return
and the head receipt's return delayed bank availability. The correction accepts
BD's head at D and joins its ACK with selected native Control ACK using four
native C-elements and twenty public control gates. Both falling returns overlap;
there is no additional periodic clock, synchronizer or payload bank. Click keeps
its existing phase protocol and accepts its head at R. Both opposing slow-clock
profiles pass in `completion-slow-r2`; the final complete capture campaign also passes.

Independent review requested per-generation actual command/receipt return checks,
all four ordering combinations at every bank, overlapping old/new bank generations,
and integrated minimum/maximum completion-gate skew. Structural controls also
reject aliased gate outputs, output/input shorts, non-scalar or missing internal
output declarations, extra ports and primitives hidden in disabled generate scopes.
These changes strengthen the checks without changing the bank-reuse deadline.

## Matched cost of corrected topology

Both mappings use the same pinned mapper, libraries, guard recipes, capture trees
and graph-preserving repair. The baseline is `capture-drive-{bd,click}-r1` from
PR #10; the final candidates are `control-frame-borrow/completion-final-map-bd`
and `completion-map-click`. The scalar-metadata re-emission is byte-identical for
Click, recorded in `completion-click-reemit-equivalence.json`. These are cell
footprints before placement, not die or routed area.

| Metric, before → after | BD | Click |
| --- | ---: | ---: |
| Mapped logic, mm² | 2.848522 → 2.825888 | 3.614665 → 3.585890 |
| Repaired logic, mm² | 3.039160 → 3.014986 | 3.824640 → 3.795762 |
| Repair increase, mm² | 0.190638 → 0.189099 | 0.209975 → 0.209872 |
| Work-clocked storage cells, including macro clock sinks | 4,009 → 3,741 | 4,060 → 3,792 |
| Service-clocked storage cells | 1,253 → 1,253 | 1,257 → 1,257 |
| LF-clocked storage cells | 78 → 78 | 78 → 78 |
| Work storage clock-pin load, pF | 14.183811 → 13.287083 | 14.355237 → 13.458509 |
| TT listed-state leakage envelope, µW | 8.0241–10.3025 → 7.9615–10.2012 | 9.5562–12.6313 → 9.4853–12.5217 |

The net reduction is **268 periodic flip-flops per variant**, with no new native
payload storage. Repaired logic falls 0.024174 / 0.028878 mm² (0.795% / 0.755%).
The three SRAM LEF footprints remain 0.466240659 mm² in total. Their separate
Liberty area fields sum to 0.6282008304 mm² and must not be substituted silently.
One SDA event clock sink remains separate from periodic clocks.

The leakage envelope sums independent listed cell states at TT, including SRAM's
aggregate datum. It is not a reachable standby-state measurement or whole-chip
deep-sleep power. It excludes analog sources, pads, CTS and routed-wire effects.
Clock-pin load is not clock energy. Fresh corrected native-model activity is unchanged:
3,257 BD / 3,212 Click work edges for each 43-instruction firmware wake, lasting
271,774.507 / 268,024.477 ns. Maintenance uses 24 / 19 work edges and ADC wakes
217 / 214. These model results do not measure mapped energy or host-upload energy.
`completion-activity.json` binds the corrected fixtures, binaries and logs; the existing 32 ns BD
Control ACK guard still contributes 22 transitions and 704 ns accumulated delay
per firmware wake, with no incomplete return at sleep entry.

Evidence: `build/control-frame-borrow/{completion-final-area-bd.json,completion-area-click-r1.json,completion-final-cost.json}`;
`completion_final_cost.py` records the measurement procedure and input hashes. Fresh independent
review recomputed both LEF area differences from flat cell inventories.
Historical repair receipts name pre-repair netlists in `inputs_sha256`; validation
must resolve these through their retained `electrical-repair/reference` snapshots.
Final netlists match the receipt's repaired hashes. The only historical helper
hash mismatch is the independently checked LF/CRLF representation of
`repair_gf180_design.py`; its normalized LF bytes match the historical hash.
Historical receipts and netlists were not rewritten to make this comparison.

## Verification

The corrected implementation's evidence is under `build/control-frame-borrow/`:

- `completion-export-regression-r2.log`: 149/149 tests across 14 suites,
  including Control, I2C, sleep/deep sleep, firmware, telemetry, both independent
  Fabric/Scaling implementations, frame stores/receipts and core reference checks.
- `completion-regression-r2.log`: 65/65 FrameAdmission, FrameWake, ControlReset
  and ProgramSource cases. The final focused run repeats all 32 FrameAdmission
  cases with per-bank actual command/receipt return evidence, adds two clockless
  completion tests, and passes five physical-policy tests (`completion-final-sbt.log`).
  These cohorts cover 216 distinct verification tests plus five physical-policy
  tests; repeated FrameAdmission runs are not additional distinct coverage.
- Final Python unit runs pass 75 frame, 60 export and 11 reset tests. The 11
  ControlGate role tests pass separately; no existing guard was shortened.
- `completion-ownership-r8`: all 15 compiled cases pass their exact verdicts.
  Both original variants witness same-edge R/new D. The 13 faults cover ownership
  priority, application-reset clearing, wrong retained selectors, early retirement,
  and BD receipt-only, native-only and combinational-AND returns.
- `completion-integration-{bd,click}-r5.json`: 2,299 BD and 1,969 Click structural
  fault cases pass, covering inline and extracted assertion forms. These run on
  isolated immutable export copies.
- All four strict exports pass with sleep-clock background activity and three
  actual SRAM instances. Physical: 646,129,440 BD / 555,485,628 Click mapping
  checks. Portable: 645,918,240 BD / 555,296,508 Click. The portable runs use
  source-identical isolated copies, bound by
  `completion-portable-parallel-equivalence.json`. `completion-strict-complete.json`
  verifies the executed probes, binaries, logs and complete source/auxiliary
  inventories against their attestations.
- `completion-capture-{bd,click}-r4`: all 346 cases pass (292 positive and 54
  exact-fatal controls). Both complete 173-case shards were freshly compiled
  and executed. `completion-capture-complete.json` binds their disjoint union,
  identical current source/helper/compiler inventories and preserved original
  fixtures. This includes all original slow-period reuse deadlines, full-width
  payload/epoch activity and integrated completion-gate skew.

The original bank-reuse deadline is unchanged. The capture oracle compares the
actual 379-bit native Join input/storage against independent frame and dispatch
metadata, tracks each bank's generation through both actual returns, and requires
D/capture/R counts to agree after drainage. The clockless completion tests cover
all four acceptance/return order combinations on every bank, POR and overlapping
old/new bank generations, with 28 min/max/random-delay runs.

BD's late-ACK test prolongs only a sender synchronizer's already observed high
ACK, allowing the actual native return and reply to finish before tag retirement.
It then releases that observation to exercise R/new D on one clock edge. It does
not force native payload, derived valid or native ACK. The fatal-site harness
expands four identical genvar monitors into constant-index instances without
changing their conditions/actions, avoiding compiler-generated scope names.

Fresh independent reviews found no remaining RTL blocker. They requested actual
per-generation return evidence, integrated completion-gate skew, exact compiled
faults and source custody. A subsequent review found primitive output/input shorts
missing from the structural proof. The corrected proof requires internal scalar
gate outputs disjoint from all module ports; only a final C-element may directly
drive its own declared bank output. Corresponding alias/scope/declaration faults
are included. The final ownership reviewer independently verified all 1,766
referenced hashes, both same-edge witnesses and all 13 exact fatal source lines.
The final documentation review rechecked ownership r8's 1,766 hashes and clarified
that README's PR9/PR10 local timing results are historical snapshots, not timing
reruns on the new 11b1 graph. The final capture reviewer independently checked
37,189 current hashes, fresh ordered compiler inputs and all 346 verdicts against
their actual assertion sites and positive/copy-order oracles. Both complete
shards, their disjoint union and retained failed r2/r3 evidence pass that audit.

## Retained failures and superseded evidence

The first candidate passed ordinary regressions but failed the unchanged 1 ms
`READY_BY_THIRD_NEXT_A` case in `capture-r5-bd`. That is implementation failure
evidence, not a waived test: the native BD join corrects the serialized-return
cause. `completion-regression-r1` retained three obsolete monitor failures where
clocked tag retirement was incorrectly treated as physical bank return. The
replacement monitors check actual per-bank command and receipt return edges.

Earlier `capture-r1` through `capture-r4`, strict-export attempts and policy logs
remain. They include stale emitted-net bindings, process-resource timeouts,
interrupted helper revisions and a policy/source-custody failure caused by a
concurrent checker writing into the same export. Current policy campaigns use
isolated export copies. Wall-clock compiler/simulator allowances were increased
without changing simulated deadlines, timing models, stimuli or coverage.

`completion-ownership-r1` through `r5` retain injector/diagnostic failures: a named
byte alias, a missing same-edge witness, the stronger earlier RTZ assertion,
compiler-generated scope names, and an invalid declaration order in the AND
mutant. Compiler errors never count as detected faults. Scalar leaf metadata also
replaces unresolved Vec endpoint references; it changes no functional logic.
Cancelled campaigns are labeled and do not count as accepted evidence.

`completion-capture-bd-r2` retains an exact-diagnostic mismatch: the command-D
corruption is caught by `FRAME_CAPTURE_COMMAND_FULL_RTZ_HOLD` before the delayed
capture assertion. The corrected injector expects that one exact BD site;
Click retains its capture-time identity site. Neither the corruption nor any
assertion changed. All four frame/header corruption smoke cases pass their
expected fatal sites, followed by a complete rerun of both capture shards.
The ownership campaign is also rerun as r8 because it imports the changed
capture helper; r6/r7 remain independently audited historical receipts.

`completion-capture-bd-r3` retains a second injector failure: forcing the
clocked head receipt ACK no longer forces bank unavailability after the new
native completion join. It instead caused an unrelated admission/overflow
failure, correctly rejected by the exact-site verdict. The corrected BD
unavailable-at-O fault forces the actual bank-zero completion C-element Q at
the original fourth-admission frontier. The distinct return-stuck fault still
forces the receipt ACK. `forced_return_source` records the actual primitive;
all four BD/Click return-fault smoke cases hit their unchanged expected sites.
Independent review verified those force statements and exact fatal locations.
Both complete capture shards are freshly compiled and executed; no execution
cache or reused verdict is used.

## Remaining physical obligation

The prior Control setup/hold results start at a different upstream storage
boundary. Requalify the borrowed bank, selector and valid mask through the latest
native Join capture, including source reuse, reset containment, all corners and
extracted min/max RC. No guard was shortened and no clock or synchronizer was
added to the native path. The synchronous header sender and three ownership bits
remain explicit candidates for later scheduler migration.
