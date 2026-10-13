# Current-controller physical export

Substep 17a2a restores physical-flow inputs for the current separate BD and
Click SoCs. It changes the physical emitter and its policy binding, not controller
RTL, digital guard budgets, the public ABI or clocked-state ownership.
17a2b owns clock/reset/crossing constraints; 17a3 owns complete timing obligations.
No current output is physically qualified.

## Supported controller policy

`PhysicalSocExport` emits the current default digital controller policies for
both variants. `PhysicalTiming` remains a separate standalone-core experiment,
with its original independent dependent-write tests. The old physical emitter
passed that core policy into the composed Click fabric; the fabric correctly
rejected it. Its `CLICK_FABRIC_REQUIRES_SIMULATION_POLICY` guard remains intact
and has a direct negative test. No native controller receives an unsupported
policy merely to make export succeed.

The physical emitter retains the enabled Groundlark evaluation policy, ADC,
source-stopping low-power configuration, independent LF time/watchdog and chip
reset qualifier. Its threshold defaults are not battery/tapeout settings.
Ordinary reference emitters keep their existing disabled board policy.

Every controller's exact timing intent resides in `contract.json`. The current v3
`physical-policy.json` binds that file and `ports.json` by SHA-256, identifies
the supported digital policy and explicitly labels qualification as absent.
The obsolete global timing numbers from the standalone core experiment are
removed: they did not describe the migrated service controllers. Service/LF
limits remain identified. R2's `application_reset` record separates the eight-edge
pulse qualifier, 64-edge assertion/release intervals, their conservative 3.15 us
minimums, the rounded measured local 1.55 us guard bound and the unchanged 250 ns
digital timing-policy cap. The old `native_reset_settlement_fs` field is rejected.
Reset qualification remains `unqualified` with scope `local-guard-margin-only`;
complete reset-tree, upstream logic and core startup are not characterized here.
R2a passes digital regression, fresh independent review, actual-RTL structural
controls and strict validation of both portable and physical export forms. This
verification does not close R2b/item 17a3 physical reset qualification.

The mapper rejects stale contract/port hashes, wrong variant/top bindings,
disabled evaluation policy, unsupported policy names, false qualification labels
and old v1/v2 policy records. Regenerate old exports with the current emitter;
do not edit their policy JSON to claim current support. Existing old P&R artifacts
remain historical and do not qualify the migrated RTL.

## Verification-source boundary

Chisel verification bodies stay inline in their owning modules using
`chisel3.layer.elideBlocks`. Original assertions, including
`CONTROL_HOST_MAILBOX_OVERFLOW`, remain present in simulation RTL. The existing
physical synthesis command defines `SYNTHESIS`, excluding those bodies from
hardware. This does not disable assertions in functional simulation.

Strict frame/return validation accepts the two reviewed compiler forms explicitly:
the ordinary exports' extracted assertions and the physical exports' inline
assertions. Only expected identifier spellings change; observed RTL is never
rewritten to make a check pass. Both forms retain exact driver/writer, capture,
overflow and literal-mask checks. Assertion validation also closes lexical
ownership: a correct-looking assertion inside a disabled generate, uninstantiated
module or uninvoked task is not executable evidence. Mutation controls exercise
both actual forms, including the disabled-generate case found by fresh review.

The mapper still requires every listed source to resolve directly inside the
export directory and belong to an inventoried module, registered primitive or
pinned SRAM. It does not admit arbitrary files or extracted verification modules.
Normal `./` or `.\` spellings of registered local files satisfy this same-directory
rule; subdirectories and parent traversal do not. Never remove a failing source
from `filelist.f` to make the inventory pass.

The export command refuses to overwrite an existing output directory. Retain
failed exports and use a fresh directory for each repair attempt.

## Verification and open physical work

Evidence is under `build/async-physical-export-migration/`. Required checks include
both physical-policy core tests, both new export tests, all Python controls,
strict validation of both actual exports, actual mapping and cell functional
oracles. Compare every public port field to the prior qualified digital exports;
preserve source/policy hashes, compiled probe attestations and all failure logs.
The initial new test incorrectly rejected registered `.\` source spellings;
the corrected test resolves paths and still requires the exact export parent.
The original test and failed log remain evidence.
The first strict attempts also exposed extracted-only frame aliases and return
clock names. Their logs and generated artifacts remain alongside the corrected
checks; the actual exported controller RTL is unchanged by those repairs.

The final run passes four physical tests, 378 Python tests, 3,620 actual frame
source mutations and 124 return integration tests. Both strict exports pass
(815,242,320 BD and 706,764,240 Click mapping checks). All 34 public ports match
the prior digital exports exactly. Actual mapped-cell checks cover 26,567 BD
and 15,108 Click vectors; synthesis audits retain three SRAMs per design and
the exact async cells and connections.

The final scalar-clock validator repair happened while strict simulation was
running. A separate final-helper preflight reran every static check and compiled
the probe in a fresh export copy, stopping before simulation. The collector
requires identical probe/source/tool hashes and the identical ordered compiler
command (only the copied export directory prefix is normalized), then binds
that result to the original simulation's actual PASS and executed binary. The
preflight itself supplies no simulation PASS. Both forms retain original
functional oracles; earlier failures and interrupted campaigns remain recorded.

The 17a1 measurements already show guards exceeding fixed digital maxima and
the old 250 ns reset-settlement assumption. R2's separate reset intervals exceed
the measured local propagation but cannot establish a full reset-tree bound.
Successful export, synthesis or cell
truth-table checks cannot close those mismatches. Current hierarchy and
related-clock constraint repair, complete transforms, pulse/hold/reset envelopes,
electrical limits and extracted timing remain mandatory. Further service-island
migration is frozen by the R4 cost gate, independently of these qualification
obligations.
The independent review of `c4b7f44` additionally reopens reset-domain crossing
and frame-copy completion assumptions. The corrective gates in the migration
checklist must close before further state removal; export validation does not
resolve those design issues.

The R4 historical comparison has a separate, explicit baseline-policy option.
It admits only the pinned `8637099` revision with the comparison schema and
historical reset declaration, while checking the supported core timing, enabled
board policy, inline assertions and source/contract hashes. Default production
validation still requires v3 and rejects this historical policy. Its two-file
harness patch is recorded in the comparison evidence; it neither upgrades the
old reset architecture nor qualifies that RTL for production.
