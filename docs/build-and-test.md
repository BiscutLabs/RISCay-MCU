# Build and test

## Fresh recovery ownership — digitally verified, 2026-10-10

Substep 10b2c2a adds immutable CPU/recovery roles and native sticky debt to the
independent BD and Click publication owners, removing four clocked recovery
flags per variant. No additional crossing is introduced. The original five
crossings and clocked full-return fence remain until later substeps. Prolonged
application reset still permits independent Housekeeping maintenance. This
checkpoint does not establish minimum synchronous state or physical timing.

Evidence: `build/async-recovery-ownership-migration/qualification-evidence.json`.
The full run passes **352 tests across 41 verification suites**, including
independent core references, real serial firmware uploads, sleep, watchdog,
full-capacity SRAM and permanent supervision, plus **two core policy tests**.
After the final test/probe changes, all **43 focused cases** pass. Final production
RTL matches the full-regression emission apart from source comments/whitespace
and two preserved Click probe-wire identifier renames; canonical connectivity,
manifest semantics and hashes are checked. All **137 working-tree Python tests**
and **11 pinned SRAM assets** pass. The emitted 34-port ABI matches `afd7500`.

Unchanged functional oracles reject **91 actual RTL defects**: 33 existing source
controls, 32 new recovery controls, 20 capture-timing defects and six exported
constant corruptions. Another **989 metadata mutations** and **six dynamic-binding
substitutions** are rejected. Compilation failures and global deadlines are not
passing negative controls. Deduplicated child modules are copied and rebound at
only the selected owner; original source and oracle hashes are retained.

Actual D/trigger pin checks pass **130 publication** and **212 recovery** positive
replays, covering every seed and directed skew, legal distribution, setup/hold,
high/low pulses and observed reset overlap. The six earlier Click custom registers
remain covered; both new debt registers are checked separately. All 27 publication
and 54 recovery reset fixtures satisfy their per-case overlap obligations. Native
and coupled tests also separate publication from grant return, stall reservation
ingress while empty after reset, hold stale recovery replies, offer CPU work during
recovery, and exercise reset after debt clear and prolonged-reset maintenance.

Fresh design, implementation, qualification and final-evidence reviews found
and addressed test/tool gaps without weakening implementation oracles. Retained
failures include duplicate metadata, missing probe preservation, absent reset
capture overlap, surviving publication/fence mutants, deduplicated-owner mutation
and malformed nested-pin replacement. The first BD strict probe lacked activity
on the new recovery command marker. A source-only joint-state campaign now covers
that conjunction while retaining every generic campaign, binding check and
dynamic-bit polarity assertion. Its six checker controls pass. The corrected BD
and Click exports pass their first probes; earlier failed attempts remain evidence
and are not counted as passes.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| four-phase | 2402 | 703584232 | `28294e9a3064947789f9d5e105473aed717356366efdbb64230465e0cc8b1ffa` |
| click | 2120 | 597678880 | `341b05728c1f3f770722f39e1d029da8eb41d82159c29d23e222fad5f96aab31` |

Full cell/path, capture/reset, CDC and routed qualification remain item 17. The
residual clocked-state inventory and removal obligations are in the checklist.

## Native publication ownership — digitally verified, 2026-10-10

Substep 10b2c1 replaces the clocked Telemetry/Housekeeping CPU-pending bits with
separate native exclusive owners. Atomic reservations precede CPU acceptance;
publication receipts and persistent drain offers preserve independent histories
across cancellation. Five POR clocked-client crossings per source, recovery
attribution, full-return debt fencing, dispatch/staging and projections remain.

Evidence: `build/async-publication-source-migration/qualification-evidence.json`.
The first full run passes **330 cases across 39 verification suites**, plus both
core physical-policy tests. Review adds four Housekeeping receipt/drain cases
and stronger native progress bounds; `focused-reviewed.log` passes all **25**
native/coupled cases. Fresh XML reports total **334 verification cases**, with
no failures, errors, skips or pending tests. Production RTL is unchanged between
those runs, and final emission matches the strict inputs. The full run includes
independent core references, firmware, sleep, watchdog, serial and SRAM effects.
All **113 working-tree Python controls** and **11 pinned SRAM assets** pass.
The 34-port public ABI matches `e87f531`, including emitted declarations.

The original functional oracles reject **49 actual RTL defects**: 33 source and
integration mutations, ten custom Click capture-timing defects, and six strict
constant corruptions. Another **857 metadata mutations** and **six dynamic-binding
substitutions** are rejected. Source and oracle hashes are retained; compilation
failures and deadlines are never counted as passing negative controls.

The custom Click register campaign passes **130 positive replays**: every seed
and directed-skew fixture plus a legal 100 ps distribution case. All six custom
EventRegisters are checked at actual D/trigger pins for setup, hold, high/low
pulse and distribution. All 27 reset-capture fixtures observe publication
capture, drain capture and publication ACK-propagation overlap with reset.
These are digital assumptions, not physical capture or routing qualification.
Extracting shared pin monitors preserves the prior program-owner results:
127 positive replays and ten rejected timing defects.

Both strict exports pass their first probes. Complete dynamic endpoint activity,
sleep-clock backgrounds, reset bindings, native Click and SRAM checks remain.
The strengthened TimingMarker policy reproduces the original probes unchanged;
`contract_first_probe.sv` and first simulation output remain the evidence.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| four-phase | 2396 | 701328368 | `8774103778a84005a60936c422954b171a20bee4a5df3db0ae44c90abdd46a6c` |
| click | 2112 | 594612480 | `10d3d5a5f3602b7f92fc2a863195c888b91bb555604aaed9b4e0475847b37774` |

Fresh implementation review expanded reset offsets through Click's complete
guard interval and required actual-pin/reset-overlap controls. Fresh qualification
review added independent Housekeeping publication/reset and drain/reuse cases,
with matching actual bridge mutations. Both reviews' findings are resolved and
affected checks pass. Failures remain in the evidence folder: initial generic
bridge-name compilation, capture-testbench declaration/alias compilation,
incomplete marker WIDTH policy, and a Click reset mutation reaching only a global
deadline. The latter prompted scoped drain/ACK progress assertions; immediate
reuse, fast timing, phase/count and reset oracles remain intact.

The residual non-primitive state inventory has 67 candidate owners per design:
BD 1,138 registers / 8,712 bits; Click 1,137 / 8,713. Ten temporary bridge owners
add 76 registers / 86 bits relative to 10b2b despite removing CPU-pending flags.
This is an ownership migration checkpoint, not minimum area/power or physical
necessity evidence. Items 10b2c2a/b and subsequent interconnect steps explicitly
remove convenience recovery/debt and crossing state. Older P&R cannot qualify it.

## Native program source ownership - digitally verified, 2026-10-10

Substep 10b2b replaces clocked program-read and Stored-pending ownership with
separate BD and native Click controllers. Tagged reservations precede word
acceptance; actual loader publication creates exactly one native Stored token.
Five POR crossings and clocked client/drain projections remain explicit.

Evidence is under `build/async-program-source-migration/`.
`full-regression-r4.log` passes **309 tests across 37 verification suites** and
both physical-policy tests, with no failures, errors, skips or pending cases.
This includes both cores against independent references, all firmware, sleep,
watchdog, native/service, serial I2C and actual SRAM effect regressions. Fresh
XML reports are copied and hashed in `verification-summary.json`. Final SoC
re-emission is byte-identical to the strict inputs (`final-emit-equivalence.json`).
`python-capture-reviewed.log` passes all **105 working-tree Python controls**,
including the preserved P&R controls; all 11 pinned SRAM assets pass validation.
The 34 public ports and emitted declarations match baseline `396bf7d` exactly.

The final actual-RTL campaigns reject **50 defects**: 34 native/source/Stored
integration mutations, ten custom Click register timing defects, and six strict
completion-boundary constant corruptions. A further 218 metadata mutations and
six dynamic-binding substitutions are rejected. Receipts are
`program-controls-final/results.json`, `capture-controls-reviewed/results.json`
and `boundary-controls/results.json`; none counts compilation failure or timeout
as a successful negative control. Original source/oracle hashes are preserved.

The custom Click pin campaign replays all 126 original seed/skew oracles plus
one legal 100 ps clock-distribution case. It requires the complete fixture set
before simulation, asserts activity at every targeted register in mixed and
fast histories, and checks the actual D/trigger pins of all six EventRegisters.
Setup, hold, high/low pulse and distribution defects are exercised independently
of the functional assertions. The declared 100 ps aperture/distribution envelope
is a digital assumption, not measured physical timing.

Both production strict exports pass on their first full r4 probes with dynamic
bit activity, sleep-clock stimulus, exact constants, reset policy and native
Click checks retained. Their `contract_first_probe.sv` and first simulation logs
are preserved; no paired fallback pass is substituted. Final policy revalidation
proves the stronger Stored writer/reset policy leaves each dynamic probe unchanged.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| four-phase | 2254 | 657563928 | `56c19c784f3b3c2019a9ca860dcd829646c77e1f3f2546ec773a7347261c3e21` |
| click | 1942 | 542276312 | `92da31d9786c68557daeb7bf01a00209d09ae8c00f22c577d8b9ef8e0c71dc93` |

Receipts are `bd-strict-r4.log`, `click-strict-r4.log`, both `*-soc-r4/resolved.json`,
`final-policy-recheck.json` and `qualification-evidence.json`. Fresh independent
review covers native timing/history, reset/priority, Stored CDC, export-policy
closure and capture-checker completeness. All actionable findings were fixed and
the affected checks rerun. No physical qualification is implied.

Failure evidence is retained. The first full run passed 303 of 305 tests and
failed both earliest 400 kHz WRITE-status cases at 3.2 MHz with
`I2C_EARLIEST_WRITE_STATUS`. Stored accounting published one service edge after
snapshot capture. The specialized Stored crossing now keeps two request
synchronizers and producer-held data, acknowledging only Control acceptance;
removing redundant payload/capture state saves two service edges. Both original
I2C timing/status oracles pass in the final Scala-generated full run.

Earlier native metadata, return-phase fixture and integration failures remain
in their original logs. `debug-begin/simulation.log` records a fixture's NBA idle
sampling transient. `debug-late/simulation.log` records a late BEGIN invalidating
a held CPU read: the ABI requires exactly one access fault and zero word effects,
not zero CPU admissions. Review corrected that oracle to require both effects.
A first Stored-reset mutation reached only a deadline; the strengthened
independent phase/count and model-bounded receipt assertions now reject it
directly. The failed control is not counted as a pass.

The first r3 strict probes failed at the newly gated program-word ingress.
Review identified missing tagged-grant and publication source combinations.
The checker now drives only catalogued source registers, with all binding and
activity checks intact; new unit controls reject omitted source fields and bad
bindings. Those first failed probes and stopped fallback state remain recorded.
The r4 source-copy setup failures are also retained. Capture preflights preserve
an inactive Stored negative fixture and injected-wire declaration errors; the
reviewed campaign uses active mixed histories and compiles every mutation.
Interrupted runs and targeted diagnostic replays are never counted as full passes.

## Native RAM source ownership - digitally verified, 2026-10-10

Substep 10b2a adds separate native BD and Click reservations before CPU RAM
acceptance. Grant, commit receipt and word acceptance agree; cancellation drains
queued grants without issuing a word. Actual publication retires accepted effects,
while application reset removes CPU reply eligibility. Four explicit POR crossings,
clocked drain projection and the existing SRAM word round trip remain for later
substeps. Program-memory ownership is still tracked separately in 10b2b.

Evidence is under `build/async-ram-source-migration/`. `python-r4.log` passes all
96 working-tree Python controls, including six preserved P&R controls, and
`sram-assets.log` validates all 11 pinned assets. `public-abi.json` confirms the
same 34 public ports per variant as 10b1. `full-regression-r3.log` passes all
276 verification cases across 34 suites and both core timing-policy cases, with
no failures, errors, skipped, canceled, ignored or pending cases. Fresh XML
receipts and hashes are in `verification-summary.json` and `final-reports/`.

The final focused run (`selection-guards-r2.log`) passes all 33 RAM/Completion
cases, including directed single-gate minimum/maximum skew. Fresh independent
review has no remaining finding. Both strict exports pass. Final emit comparison
confirms identical manifests and functional RTL against those exact receipts;
`qualification-evidence.json` collects source, probe, report and checker hashes.

The new fixtures independently count CPU acceptance, word acceptance, real SRAM
byte writes and publication. They cover queued reservations, grant/decision
stalls, every held byte lane, publication debt, repeated sub-cycle reset pulses
and earliest native return/reuse. Publication-only tests hold the selected receipt
back after every other retirement condition is satisfied. Eligibility by itself
is never a valid-response signal.

The original `boundary-first.log` and `debug-publication/simulation.log` retain
a Click phantom-completion failure after a short reset. The old two-edge release
could expose a delayed previous completion phase. Both application islands now
assert reset asynchronously and hold it for eight ungated service edges, restarting
on every raw pulse. At the 20 MHz ceiling, the minimum 350 ns hold exceeds the
250 ns digital settlement budget. The original short pulses and result/count
oracles are unchanged. Accepted SRAM effects and source phases stay POR-owned.

Fresh independent review findings and fixes are recorded in `review-notes.md`.
The emitted reset audit checks the actual release logic, every application-owned
child and its nested timing bounds. The reset-binding probe and budget audit use
one complete ownership classification. Custom BD/Click timing policies must fit
the budget. RAM eligibility has one narrowly validated POR-or-application reset
exception; all other source state retains the normal POR checks.

Both production exports pass their first strict probes without paired fallback.
`guard-export-comparison.json` verifies identical BD RTL and metadata against the
latest emitter. The Click receipt below includes both selection-guard fixes.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase | 2,167 | 630,755,191 | `f9debaf7815e9d2c7886aad3bbc03e9eb6efe0d7bdca4f61e372f58562f158ff` |
| Native Click | 1,845 | 513,103,725 | `ad48fffd345fdf05de86fc2a660efa182de216f3ecc515161942f4bbf36c034c` |

BD receipts are `bd-strict-r2.log` and `four-phase-soc/resolved.json`.
Click receipts are `click-strict-r4.log` and `click-soc-r4/resolved.json`.
All three SRAM macros and every dynamic endpoint's activity
obligations remain. The strict RAM publication stimulus may force only the
catalogued, exactly validated eligibility EventRegister output. It never forces
a derived response endpoint. Final policy revalidation preserves the successful
probe obligations and hashes.

The RAM, admission, completion and full-SoC boundary controls reject all 55 actual
RTL mutations, 191 metadata mutations and six dynamic-binding changes using
their original oracles. Earlier compile, alias, monitor-order and strict-stimulus
failures remain in the evidence directory. The native fixture's ACK reaction is
2 fs after observation so it cannot race the existing 1 fs monitor snapshot;
all timing/payload assertions remain active. These are digital results, with
physical reset, capture/return, CDC and routed timing qualification still open.

The publication-only test exposed a Click RAM selector race in
`final-focused-emit.log`; `debug-publication-required/simulation.log` preserves
the trace. The new 221.200001 ns pre-comparator decision guard settles selection
before retirement admission. Review also reproduced the same class of race in
Click Completion with one randomized selection gate at 10 ns and the other
randomized control cells at 1 ns, with fixed guards unchanged.
Its existing input phase guard is now 210.200001 ns. Both feedback paths bypass
these input guards. The unchanged absent-source oracles reject actual guard
mutations. Earlier random sweeps alone missed the Completion race. Superseded
`full-regression-r2.log` and `click-strict-r3.log` were interrupted and are not passes.

## Native admission credit - digitally verified, 2026-10-10

Expanded substep 10b1 replaces Services' clocked CPU occupancy and synchronized
retirement tracking with separate native BD and Click credit owners. One seeded
grant is consumed at the existing CPU commit edge and recycled from retained
native response acceptance. HALT holds that credit until application reset.
Source-specific cancellation and the explicit clocked grant client remain;
accepted POR effects and the public ABI are unchanged. See the
[admission contract](async-soc-migration.md#native-admission-credit-scope-10b1-digitally-verified).

Evidence is under `build/async-admission-migration/`. The full final run in
`full-regression-first.log` passes all **253 verification cases across 32 suites**
and both core physical-policy cases, with no failures, errors, skipped, canceled,
ignored or pending cases. It includes both cores against independent references,
real serial loader/firmware workloads, SRAM retention and production-ratio
Groundlark watchdog/deep-sleep regressions. Fresh report hashes and counts are in
`verification-summary.json` and `reports/`. `python-startup-final.log` passes all
90 working-tree Python controls (six belong to preserved P&R work), and
`sram-assets.log` validates all 11 pinned macro assets. `public-abi.json` confirms
the exact same 34 public ports in each variant as 10a.

Six AsyncAdmissionSpec cases cover native one-credit conservation, stalled
grants, reset, HALT-like credit retention, both Click parities and BD response
RTZ. Ten AdmissionSpec integration cases cover real HALT, repeated resets,
offered MMIO clear/event preservation, WAIT lease/wake behavior, boot sleep and
grant stalls. Two added AsyncCompletionSpec cases hold retirement acceptance
while offering a following plan. CompletionSpec proves retirement progresses
with the service clock stopped, including an old BD grant ACK still high.

Fresh reviews and fixes are recorded in `review-notes.md`. Review drove the
integration cases, mandatory production owner identities, exact native channel
schemas and strict bridge bindings. `admission-controls-r5/results.json` rejects
seven actual RTL mutations and 26 contract mutations; the RTL results explicitly
distinguish behavioral oracles from strict wiring oracles. The completion controls
in `completion-controls-r2/` reject 19 RTL mutations and 29 contract mutations.
`boundary-controls/` rejects six actual constant rewires with unchanged full
probes and six dynamic-driver substitutions during literal classification.
All original oracle/export hashes are preserved. Total: 32 rejected RTL
mutations, 55 contract mutations and six dynamic-binding substitutions.

Strict validation proves the three new literal credit-return leaves are exact
single-driver scalar zero aliases and checks their values at every step before
masking impossible one-polarity activity. Every dynamic bit retains its original
activity obligations. Joint grant states and Click startup values are driven
only at catalogued source registers; no derived endpoint is forced.

Both final strict SoC attempts pass their first probes without paired fallback:

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase | 2,106 | 611,988,858 | `1246ca7ee0e7b01d7f8de98d9b78bec5e28c3fd0b307263645cf4c2830d7bccf` |
| Native Click | 1,778 | 493,105,186 | `86dd11cc30c16b735d2cda20f0ff1151bfd49815267558495b1e22492b80dc6c` |

Receipts are `bd-strict-r3.log`, `click-strict-r4.log` and both `*-soc/resolved.json`.
`final-policy-recheck.json` validates the final owner/schema/literal policy and
requires an identical successful probe. `qualification-evidence.json` binds the
final reports, probes, emitted-source hashes, ABI and control evidence.

Earlier failures are retained: `admission-integration-first.log` caught a new
test's incorrect assumption that AsyncTest counters reset; `focused-r2.log`
records a boot fixture kept busy by its accelerated timebase and same-delta
stimulus crossing a delayed native monitor. The focused fixtures now use
cumulative counters, a stopped timebase for admission-only sleep checks and
explicit monitor-settling intervals. Existing running-timebase regressions and
all effect/reset assertions remain unchanged. The behavior-only consumption
bypass survived its initial campaign; it is now rejected by the unchanged strict
wiring oracle and is reported as a mapping control, not behavioral coverage.
The initial strict checks rejected incomplete layout and alias parsing. Click's
first simulation in `click-strict-r3-failed/` exposed missing startup stimulus:
the generic two-bit one-hot/one-cold walk never reaches 11. The added complete
source-register walk resolves that gap without changing RTL or coverage checks.

Physical qualification remains open. Digital passes do not qualify native
capture/return/reset timing, crossing setup/hold, routed closure or minimum power.

## Native completion assembly - digitally verified, 2026-10-10

Expanded checklist item 10a replaces periodic-clocked CPU response retention and
the selected Telemetry/Housekeeping completion join with separate native BD and
Click controllers. Production replies connect directly to Fabric. At the 10a
checkpoint, admission and source cancellation remained explicitly clocked
pending items 10b1/10b2; accepted
effects retain their POR ownership. See the
[completion scope](async-soc-migration.md#native-completion-assembly-scope-10a-digitally-verified).

Evidence is under `build/async-coordination-migration/`. Fresh scope and
implementation reviews and fixes are recorded in `review-notes.md`. The review
corrected BD source reuse/return sequencing, Click phase feedback outside the
capture aperture, fixed guard names and incomplete strict wiring bindings.
The existing clear/event race exposed an event lost while a previous response
drained; observation now starts when the held MMIO request arrives. Reset fixtures
retain their original CPU-reset injection and every accepted-effect assertion.

`native-final-r2.log` passes all eight focused cases across AsyncCompletionSpec and
CompletionSpec. They cover all selected-input masks and arrival orders, early
inputs, immediate source reuse, unselected pending tokens, stalled responses and
repeated partial-join/held-reply resets. Both integrated completion paths progress
with the service clock stopped after plan launch. Min/max/random cell experiments
preserve fixed guards and monitor the complete Click payload/phase capture pins.
The final campaign exercises both values of the selected memory error bit and
all six arrival permutations for every fixed mask. `final-export-focused.log`
records the preceding successful production re-export and focused rerun.
`full-regression-r1.log` passes all 235 verification cases across 30 suites and
both core physical-policy cases, with no failures, aborted suites, skipped,
canceled, ignored or pending cases. The final focused rerun includes the port
preservation annotations; no functional RTL changed after the full run compiled.
Fresh report timestamps/hashes are in `verification-summary.json` and `reports/`.
`public-abi.json` confirms both public 34-port nodes exactly match item 9.

`wiring-controls-reviewed-r2.log` and `wiring-controls-reviewed-r2/results.json` pass both standalone
strict baselines, reject all 16 actual broken RTL variants and 27 contract
mutations, and preserve the original probes and exports. The checker binds the
complete mux, selection, feedback, control, retirement and reply output paths.
`python-r4.log` passes 87 working-tree Python controls, including six preserved
P&R controls. `sram-assets.log` verifies all 11 pinned assets.

Strict mapping adds joint admission/publication source states for the four new
crossings. Only catalogued source registers are forced; generic campaigns,
mapping comparisons and every dynamic bit's two-polarity activity remain.
The memory bridge input error is literally zero; the two effect-token bridge
inputs are literally one. Their exact parent-instance bindings, scalar input
schemas and packed endpoint bits are checked before three narrow activity masks
are permitted. Every mapping step also asserts their values. Native completion
inputs and stored bridge outputs retain full dynamic coverage, including the
memory error bit. A dynamic expression cannot qualify as a literal merely by
remaining constant in the simulation campaign.

Earlier failures remain in `integration-first.log`, `integration-r1.log`
(explicitly aborted after known failures), `integration-r2.log`, and both
`*-strict-r1.log` files. Initial strict exports lost a constant memory error port;
preservation annotations retain the full declared interface without relaxing ABI
validation. `strict-final-attempt-status.txt` records the later interrupted strict
attempt, which entered a large fallback without retaining its first simulation.
The preserved original probes and diagnostic-only replays identified eight new
inactive input endpoints per SoC; joint source states and exact literal obligations
resolve those diagnostic gaps. Diagnostic replays are not strict passes. The
checker now saves first-pass probe/output before fallback. `python-r3.log` retains
the missing new fallback anchor in the synthetic checker fixture; the fixture now
also verifies evidence retention and rejects missing/duplicated fallback anchors.
The first actual-boundary control attempt (`boundary-controls-final.log`) exposed
CRLF in its classification copy; normalization now applies to that copy only.
`boundary-controls-r2.log` and its `results.json` reject all six actual constant
rewires with the full original probe bytes unchanged, plus six dynamic-driver
substitutions before granting any literal exemption. Both original exports are
hash-preserved. Together with the standalone controls this rejects 22 actual RTL
mutations, 27 contract mutations and six dynamic-binding mutations.

Both final strict SoC exports pass on their first probes, without paired fallback:

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase | 2,043 | 593,207,523 | `97f9bcef78974fe63fc2b2311e7b6810503247db81e9327a475c025f25ab8c19` |
| Native Click | 1,741 | 482,474,625 | `413032531c26bc1fd0b532bd4561e7c4f0332732f89a54f354a90e1b2fa05c64` |

Receipts are `four-phase-strict-reviewed-r2.log`, `click-strict-reviewed-r2.log`,
and each `*-final-soc/resolved.json`. Both retain all three physical SRAM macro
instances, generated application-reset checks, exact interface validation,
clock-enabled source stimulus and packed four-state-equivalent coverage.
`final-review.md` records the independent review closeout.

Reproduce the new boundary controls after emitting and strictly validating both
SoCs (choose a fresh output directory for each control run):

```powershell
python tools/check_completion_boundary_controls.py --bd build/async-coordination-migration/four-phase-final-soc --click build/async-coordination-migration/click-final-soc --out build/async-coordination-migration/boundary-controls-new --library P:/Personal/chisel-async
```

No physical qualification or maximal feasible asynchrony is claimed.

## Native slow-domain housekeeping - digitally verified, 2026-10-10

Item 9 implements separate native BD and Click time/deadline/lease/wake-mask,
watchdog kick authorization and low-power cadence loops. Clocked elapsed ingress
feeds measurement/supervisor histories independently. The LF reference/watchdog,
Gray/ACK crossings, heartbeat delivery and safe clock/source gating remain
clocked. See the [scope and timing contract](async-soc-migration.md#housekeeping-scope-and-timing-contract).

Evidence is under `build/housekeeping-migration/`. The fresh scope and implementation
reviews, findings and fixes are in `independent-review.md`. Focused tests cover
clockless native stalls, ordered writes, large elapsed intervals and wrap,
replacement, POR at three handshake phases, cadence/discard/update races, joined
CPU completions, continuous-tick CPU progress, sample aging under held publication,
period-pending host reads and whole watchdog-reset recovery. SupervisorSpec now
also stalls Housekeeping while checking independent power policy and repeated
application resets. SleepSpec's clear/event race runs on both implementations.

`full-regression.log` passes all **227 verification cases across 28 suites**,
including both core/reference implementations, plus both physical-policy cases.
There are no failed, aborted, canceled, ignored or pending cases. Fresh XML hashes
and timestamps are in `verification-summary.json` and copied reports in `reports/`.
The obsolete report for the removed FreshLogicReviewSpec is retained separately
and is not counted as a current suite. `reset-race-fixed.log` also passes all 18
focused HousekeepingSpec/SupervisorSpec cases.
`python-final.log` passes all 84 working-tree Python controls (six are preserved
P&R controls), and `sram-assets.log` verifies all 11 assets. The added generated
reset controls exercise both Housekeeping owners, descendants and crossings.
`public-abi.json` confirms both public 34-port nodes exactly match item 8.

The fresh production exports `four-phase-soc/` and `click-soc/` both pass strict
`--soc --vector-coverage --sleep-clock` validation, including unchanged generic
endpoint activity, generated reset ownership, native Click and three-SRAM checks.
Exact receipts are `bd-strict-current.log` and `click-strict-current.log`.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| BD | 1990 | 575633370 | `ceec74b75ae1c7ada0c98f4ad1837049e22134dff6b917e010bf021b3b046294` |
| Click | 1696 | 467965408 | `661a2932f8fcf5d699ae84bb6d1b511071bea6775633f024c9ea925ddb248a53` |

Retained failures are part of the evidence. `first-integration.log` records the
initial Click bridge namespace compile failure. `integration-second.log` and
`review-integration.log` retain sleep-window failures; empty ACK-retry transactions
were removed from native policy and the unchanged thresholds pass in
`crossing-reviewed.log`. `focused-first.log` records invalid fixture parameter
combinations and continuous-tick CPU starvation before the reviewed admission fix.
`focused-second.log` and `focused-final.log` retain the watchdog fixture timeout.
Detailed copied-RTL traces in `bd-reset-trace-current/` exposed active-edge stimulus
races; falling-edge pause changes preserve every reset/effect assertion and pass.
The original failed exports/logs remain intact.

`bd-strict.log` and `click-strict.log` retain the initial
`CONTROL_PROBE_DRIVER_MISMATCH`: the NOW register moved into the Housekeeping
projection. The strict stimulus now binds its actual 32-bit source register,
`fabric_housekeepingState_now`. The independent reviewer checked both emitted
register declarations and MMIO muxes. Walking vectors, comparison/coverage checks
and broken-binding controls are unchanged; `control-binding-tests.log` passes.

Reproduce with one sbt process at a time:

```powershell
python tools/sbt.py 'verification/test' 'physical/test'
python tools/sbt.py 'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/housekeeping-recheck/four-phase-soc' 'twoPhaseClick/runMain riscay.click.EmitClickSoc build/housekeeping-recheck/click-soc'
python tools/check_export.py build/housekeeping-recheck/four-phase-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
python tools/check_export.py build/housekeeping-recheck/click-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/sram_assets.py
```

All digital completion gates pass. No analog circuit or physical budget changed;
prior P&R cannot qualify the new controllers. Physical requalification is now
expanded checklist item 17, following the remaining migration and residual audit.

## Native SPI ADC migration - digitally verified, 2026-10-10

Item 8 has independent BD and native Click conversion owners, immutable pin
recipes, complete-frame rendezvous, native extraction/priming/scaling/offset and
consumer-accepted retirement. Clocked admission/publication, fixed-rate pin
playback and complete MISO capture remain explicit boundaries; item 9 subsequently
migrates low-power cadence. See the
[scope and timing contract](async-soc-migration.md#spi-adc-scope-and-contract).

Evidence is under `build/spi-adc-migration/`. `regression-first.log` passes all
202 verification cases across 26 suites and both physical-policy cases. After
fresh independent review, `reviewed-regression.log` passes the 18 focused SPI
cases, including four added independent-admission and exact age-edge cases;
all 36 affected SoC/core/firmware/sleep cases also pass. The final current reports
contain 206 passing verification cases across 26 suites, with no failures, errors
or skips, plus both physical-policy cases. `verification-reviewed-summary.json`
records the report hashes and timestamps.

The focused campaigns cover clockless native request/response stalls and POR,
all leading nibbles, alternating/walking sample bits, odd-slot noise, first-complete
frame discard, exact gain/offset, complete watchdog episodes, buffered old frames,
age saturation, coincident launch/publication ticks and stale-then-fresh supervisor
history. At 20 MHz service and two-cycle half-periods, maximum native model delays
must preserve every 100 ns half-phase and complete admission through return within
6.8 us. These are digital stress bounds, not physical or ADC electrical signoff.

`python-all.log` passes all 83 working-tree Python controls (six belong to the
preserved earlier P&R work); `sram-assets.log` verifies all 11 pinned assets.
`public-abi-reviewed.json` shows that both public 34-port nodes match committed
item 7 (`c9076b1`) exactly.

Final production exports are `four-phase-reviewed-soc/` and `click-reviewed-soc/`.
Strict checks with `--soc --vector-coverage --sleep-clock --probe-timeout 7200`
pass all endpoint activity, mapping, generated-reset, native Click and three-SRAM
obligations:

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| BD | 1892 | 491630524 | `ab5cf024c1acd71fbafe2b964cb22b4ea88f9bd3eb446aed210d143e3035f03e` |
| Click | 1625 | 404395875 | `f21be51efff38a5982a8b8a9bb2010e5a9726d2ea359b3ffb4f3e070b250dfaa` |

Exact receipts are `bd-strict-reviewed.log` and `click-strict-reviewed.log`.

Retained failures: `age-first.log` records two fixture API mistakes (`Option`
indexing and `BoringUtils` argument placement), fixed before simulation. The first
strict exports failed `PORT_ABI_RTL_MISMATCH`: compiler structural deduplication
coalesced the new 33-bit capture payload with CPU response storage/bridges and
renamed their declared fields; a constant calibration output was also removed.
`initial-abi-failure.json` records the exact mismatches. Both variants now preserve
the capture subtree/bridge ABI with no-dedup annotations and retain ADC IO. No
mapping check or behavioral expectation was relaxed.

`wiring-controls.log` retains the initial negative-control diagnostic mismatch:
the broken initial-CS load was rejected by `SPI_FRAME_START` before the anticipated
clock-high check. The runner now requires the observed frame-start diagnostic;
the wire oracle is unchanged, as confirmed by independent review.

The fresh review and fixes are recorded in `independent-review.md`. Exact native
constant checks and native-to-recipe wiring checks retain the generic endpoint
activity campaigns. `tools/check_spi_wiring_controls.py` additionally mutates real
emitted register loads and MISO capture under the unchanged wire oracle, and real
native constants under the unchanged strict probe. All 22 mutations compile and
fail their required assertions; both unchanged wire baselines pass, and the
completed strict runs supply the positive mapping controls. Original export
hashes remain unchanged. Receipts are `wiring-controls-reviewed.log` and
`wiring-controls-reviewed/results.json`.

Reproduce with one sbt process at a time:

```powershell
python tools/sbt.py 'verification/test' 'physical/test'
python tools/sbt.py 'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/spi-recheck/four-phase-soc' 'twoPhaseClick/runMain riscay.click.EmitClickSoc build/spi-recheck/click-soc'
python tools/check_export.py build/spi-recheck/four-phase-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
python tools/check_export.py build/spi-recheck/click-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/check_spi_wiring_controls.py --bd <bd-spi-wave-export> --click <click-spi-wave-export> --bd-strict <bd-strict-soc-export> --click-strict <click-strict-soc-export> --out <fresh-evidence-directory>
```

The wire export paths are generated under `build/soc-tests/` by `SpiAdcSpec`.
Older P&R results do not qualify this RTL. Independent LF/watchdog housekeeping
remains necessary. Item 9 results are recorded above.

## Native I2C migration - digitally verified, 2026-10-09

Item 7 uses separate BD and native Click protocol loops, an immutable eight-slot
sampled-edge ring, independent held frame/read-start effects, and explicit clocked
wire, timeout and host-publication boundaries. See the migration checklist for
reset, sleep and timing scope. No physical qualification is claimed.

Evidence is under `build/i2c-migration/`. The broad `regression-first.log` ran
188 tests across 24 suites: 186 passed and two immediate SocSpec BEGIN pin
observations failed. `review-final.log` passed all 26 SocSpec/I2cSpec/AsyncI2cSpec
cases after the reviewed observation fixes, plus both physical-policy cases.
The later POR admission change was followed by `admission-regression.log`:
SoC, sleep, deep-sleep and compiled firmware cases all passed; ten I2cSpec cases
failed to compile a new monitor's optimized-away hierarchical signal reference.
That test reference was corrected by exposing the actual read-start output.
`i2c-reviewed-final.log` passes all 21 I2cSpec/AsyncI2cSpec cases, including two
new held-snapshot POR/recovery cases. No expectation was removed to clear a bug.
The final reports for all 24 suites contain 190 passing verification outcomes,
with no failures, errors, skips or pending cases; both physical-policy cases also
pass. `verification-reviewed-summary.json` records each suite and timestamp.

`python-internal.log` passes all 80 working-tree Python controls (six belong to
the preserved earlier P&R work). `sram-assets.log` verifies all 11 pinned assets.
Both public 34-port ABI nodes match item 6 exactly
(`public-abi-admission-verified.json`). Final production exports are
`four-phase-admission-soc/` and `click-admission-soc/`; strict checks with
`--soc --vector-coverage --sleep-clock --probe-timeout 7200` pass all endpoint
activity, mapping, generated-reset, native Click and three-SRAM obligations:

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| BD | 1698 | 434360286 | `33a7642087d01f7df0e2519d52cf065b60d72913a6e200515b307596980867bc` |
| Click | 1459 | 357167577 | `e82781cf2819e0e0f637e8d1841478f43666ff5a7780f9e76994e50a30936d1a` |

Exact strict receipts are `bd-strict-reviewed.log`, `click-strict-reviewed.log`
and `strict-reviewed-summary.json`. Source-only mapping stimuli additionally
exercise valid native read-address and completed-write STOP contexts, preserving
all generic campaigns, comparisons and endpoint activity requirements.

Fresh independent review reproduced BEGIN/LOCK pin publication at STOP +1.6 us:
frame delivery was +0.9 us, Control admission +1.0 us, while the old immediate
assertion ran at +1.2 us. Both original full SocSpec scenarios pass with bounded
pin-completion observations. Untouched failures and replay receipts remain in
`review-command-publication/` and `regression-first.log`. Earliest legal 400 kHz
wire reads at 3.2/20 MHz and maximum native delays independently check SELECT
with repeated START, BEGIN replacement, WRITE accounting/CRC, VERIFY and LOCK.
Neither an extra SELECT nor polling delays hides command publication latency.

The reviewer also disconnected an actual Click internal gate input and found
that the old probe incorrectly passed (`review-internal-gate-binding/`). Added
pin comparisons cover all nine internal connections of the three composed ANDs.
`tools/check_i2c_wiring_controls.py` now independently disconnects the actual
request input, capture trigger and internal gate inputs in isolated export copies.
All thirteen mutations compile and fail `DATA_PATH_BINDING_MISMATCH` using the
byte-identical baseline probe; original exports remain unchanged. Baselines pass
124560 BD and 124500 Click checks. See `wiring-controls-internal.log` and
`wiring-controls-internal/{commands.json,results.json}`. Run the tool with
`--bd <BD-publication-export> --click <Click-publication-export>
--library <chisel-async> --out <new-evidence-directory>` after AsyncI2cSpec emits
the standalone fixtures. Synthetic comparison checks alone are insufficient.

Retain initial compile/elaboration/latency failures in `loader-*.log`,
`native-first.log`, `focused-second.log` and `wire-*.log`. The first broad focused
run passed 11/19: six immediate pin observations needed the reviewed completion
contract, while two unchanged foreign-bus recovery cases exposed a real retained
rejection wake bug. Native rejection now produces one synchronized service event.

The overflow negative control exposed previously uninstantiated Chisel assertion
layers. `chisel3.layer.elideBlocks` now emits their bodies inline for Icarus.
Each SRAM lane's full-width address assertion checks its actual `fire`, equivalent
to the old selected-lane assertion, while avoiding an Icarus variable-array/slice
limitation. All final clocked regressions execute these assertions; deliberate
edge-ring overflow must fail with its specific assertion.

Earlier strict failures are preserved: `*-strict-first.log` found optimized-away
observation ports; `*-strict-final.log` found an unnamed packed wire-input source.
Explicit retention fixes both. The first activity probes then found only the two
permanently high bridge ready inputs in each design. Diagnostic copies preserve
all stimulus/mapping checks and print every inactive endpoint; their completion
marker explicitly is not a validation pass. Their logs remain in
`*-checked-soc/activity_diagnostic.log`. Both bridges now require local POR release
before service publication, with direct reset/ready/read-start monitors and held
frame/snapshot recovery tests. Interrupted fallback/probe runs are also retained
and are not counted as passes. No ABI, binding or activity check was removed.


## Asynchronous SRAM access sequencing migration

Item 6 is digitally verified on 2026-10-09. Separate `FourPhaseSram`
and `ClickSram` pipelines retain word ownership, sequence four byte rendezvous
and assemble read data. A consumer-returned native execution credit prevents the
next word's byte effects before response acceptance. Each design retains its own
clocked single-byte macro boundary; CLK remains the service clock. See the
[scope and timing contract](async-soc-migration.md#sram-access-sequencing-scope-and-contract).

Fresh independent review prompted actual-lane/held-completion reset tests,
late loader completion checks, low-power drainage observations and strict
POR-owner inventory controls. `AsyncSramSpec` independently checks every mask,
bank boundaries, early next requests, independent request/response return stalls
and POR at each byte/held final response without a service clock. `SramSpec` retains
its original full-capacity, byte-effect, reset and loader assertions, supplemented
with maximum-delay native crossing and macro-lane tests. Delivery counters remain
cumulative across reset; recovery checks use observed baselines.

Evidence is under `build/sram-migration/`. The initial native testbench failures
in `focused-initial.log` came from an incorrectly escaped SV system-task name.
The same run's Click full-capacity case exceeded the 180-second host-process
limit. Replaying that exact unchanged `sim.vvp` completed successfully in
189.2 seconds (`click-capacity-replay.log` and its time receipt). That test now
allows 300 host seconds; its 400 ms simulated deadline, traffic and assertions
are unchanged. The standalone native strict check in `native-bd-strict-initial.log`
caught optimized-away constant credit input ports. Interface retention exposed
an inactive constant-data endpoint in both protocols (`native-*-strict-credit.log`).
The feedback payload now carries the retained completed word's operation bit,
which is stable before the response offer and through credit capture. Token
presence alone gates execution. Independent review approved this lifetime;
`native-*-strict-retired-bit.log` passes both standalone exports with the
unchanged validator. Obsolete full-SoC probes were stopped after confirming the
same constant-data issue; their probe artifacts remain in `*-constant-credit-probe/`.

The same initial run's two Groundlark deep-sleep cases exceeded their 90-second
host limit. The exact unchanged simulator images passed in 111.7 and 113.6 seconds
(`bd-deep-board-replay.log`, `click-deep-board-replay.log` and time receipts).
Their host limit is now 240 seconds; the 1.2-second simulated deadline is unchanged.

`focused-review.log` passes all four native cases; the initial new integration
fixtures failed Chisel elaboration because they referenced grandchildren. Direct
child port wiring fixes that restriction. `crossing-review.log` passes both
actual-macro reset/stall cases. Its late-loader cases and `loader-review.log`
retain real `SOC_DEADLINE` failures. A transition trace and independent review
identified a testbench race: releasing held ready exactly on a sampling edge let
parent and child registers observe different values. Off-edge release with setup
time passes both cases in `loader-edge-review.log`, with unchanged RTL and every
assertion retained. These are fixture corrections, not relaxed failure expectations.

The first full run retains two `PROTECTED_STORE_DID_NOT_TRAP` failures at the
old fixed 100 us checkpoint. Replays of both unchanged RTL exports show the
18-instruction application reaches the correct final store fault at about
142 us after START (`bd-soc-latency-diagnostic.log`,
`click-soc-latency-diagnostic.log`), then passes all remaining assertions.
The strengthened test checks every retirement PC/instruction, no earlier trap,
final cause 7 with no register write, and unchanged program bytes before checking
MODE. The global simulation deadline is unchanged; no controller timing or
protection requirement is waived.

The generic strict-probe stimulus could not put all five SRAM return
synchronizers in the idle state together. A diagnostic retained in
`idle-diagnostic.log` identified inactive command and byte-completion endpoints
in BD; its Click diagnostic exceeded its host timeout and is not a pass. Both
obsolete generic-only probes were stopped, with their initial sources retained
in `*-idle-diagnostic/`. Added coherent idle, loader/RAM admission and each byte
return tag exercise only catalogued source registers. Existing campaigns,
mapping comparisons, activity checks and the paired fallback remain intact.
Independent negative controls prove the original inactivity, added coverage and
rejection of bad mappings or missing/wrong-width source registers.

The RAM request payload is now offered independently of valid, allowing all
32 address bits to remain observable instead of forcing invalid offers to zero.
The original admission/range/permission guards are unchanged, and bridges still
capture only accepted requests. Independent review approved both changes; the
final full regression and strict checks use this regenerated RTL.

The initial production strict checks (`bd-strict.log`, `click-strict.log`) also
caught unused/constant word ready ports being pruned from `SramAccess`; explicit
interface retention preserves the declared ABI.

The final clean full regression passes **169 verification cases across 22
suites** and **two core physical-policy tests**, with no failure, skipped,
canceled, pending or aborted case (`final-regression.log`). It includes the
retired-operation credit payload, full RAM payload offers and all review fixes.
`full-regression.log` retains the earlier fixed-checkpoint failures;
`post-retention-focused.log`, `credit-path-native.log` and
`credit-path-integration.log` retain the intervening successful focused runs.
The final full run covers independent core/reference, full-capacity SRAM,
firmware, sleep/deep-sleep, native routing and all earlier migration checks.
Raw XML remains in `full-run-reports/`, `post-retention-reports/`,
`post-credit-reports/` and `final-full-reports/`; `verification-summary.json`
identifies the final report for each case. All **74 working-tree Python controls**
pass (six belong to the preserved earlier P&R work), and all **eleven pinned
SRAM assets** verify (`python-probe-final.log`, `sram-assets-final.log`).

Both regenerated production-capacity SoCs pass strict exports with all three
physical macros, generated CPU/POR reset ownership, native protocol checks and
packed-equivalent vector coverage enabled. The public **34-port ABI** exactly
matches item 5. The fresh reviewer found no remaining code/test issue after
reviewing the fixes and boundary contracts.

| Export | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 1599 | 348,103,899 | `42e8ea35f0e854440904b2c7febb9d1cba47e812c4669a78d4b92aa649fa7bbb` |
| Native Click | 1383 | 289,679,031 | `2d172571715f5745443b809da01151c26eed6b533e04d06ae1a9fd1d58a9d3e9` |

Receipts are `four-phase-strict-final.log`, `click-strict-final.log`,
`strict-summary.json` and `public-abi-verified.json` under `build/sram-migration/`.
The exported RTL is in `four-phase-preserved-soc/` and `click-preserved-soc/`.
Strict stimulus adds coherent idle and per-lane completion source states for
SRAM crossings, Click startup, elapsed-time admission and a selected BD service
response. Only catalogued registers and the metadata-validated native address
latch output are forced; all original campaigns, comparisons, activity assertions
and fallback remain. Independent SV controls prove activation and reject broken
aliases or absent/wrong-width source drivers. Initial inactive diagnostics,
host diagnostic timeouts and interrupted paired probes remain in
`*-activity-diagnostic/`, `*-idle-diagnostic/`, `*-admission-diagnostic/` and
`*-paired-before-service-vectors/`; none is counted as a pass.
Full probes use a 7200-second host simulation allowance with no removed checks.
Reproduce with fresh output directories:

```powershell
python tools/sbt.py 'verification/test' 'physical/test'
python tools/sbt.py 'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/sram-recheck/four-phase-soc' 'twoPhaseClick/runMain riscay.click.EmitClickSoc build/sram-recheck/click-soc'
python tools/check_export.py build/sram-recheck/four-phase-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
python tools/check_export.py build/sram-recheck/click-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/sram_assets.py --verify-only
```

No physical timing or power qualification is implied. Native transforms,
feedback, crossings and macro paths still require item 17 qualification; older
baseline P&R results remain inapplicable.

## Asynchronous permanent supervisor migration

Item 5 moves Groundlark power policy, safety samples, confirmation counters and
dwell epochs into independent `FourPhaseSupervisor` and `ClickSupervisor` loops.
Profiles retain immutable descriptors/policy. Dedicated POR-only crossings and
retained ingress/projection preserve supervision through application reset and
Control/Telemetry stalls. See the [exact migration contract](async-soc-migration.md#permanent-supervisor-scope-and-contract).

Fresh independent review prompted two safety fixes: include the coincident upper
time increment in first/later publication freshness gaps, and retain bad sensing
consumed between ticks until policy evaluation even after a separate recovery
command. Strict reset validation now recognizes the complete supervisor/bridge
set and all descendants as POR-owned, with deliberate miswire and missing/unknown
owner controls. The physical emitter selects the new immutable board descriptor.

`AsyncSupervisorSpec` has ten clockless cases across both protocols: randomized
native delay seeds, reply stalls, cold boot/current-boot ACK, minimum-off and
shutdown dwell feedback, low-voltage confirmation boundaries and recovery,
three-timeout latch, sensing-history gaps, counter saturation, disabled policy
and POR during requests/held replies. `SupervisorSpec` adds six real crossing
cases: first/subsequent coincident-tick freshness boundaries, accumulated failure
and GPIO history, stalled SHUTDOWN/OFF projections, independent progress during
Control/Telemetry stalls and repeated production-ratio 32-edge watchdog resets.
Its timers wait for applied GPIO transitions, then assert configured dwell in
the test's logical-time model. These checks do not bound LF phase, fractional
rounding or elapsed-publication latency in physical wall time.
The existing SoC, sleep, deep-sleep and firmware expectations are unchanged.

On 2026-10-09, `full-regression.log` passes **161 verification cases across 21
suites** and **two core physical-policy tests**, without failures, skipped,
canceled, pending or aborted cases. XML snapshots and counts are preserved in
`verified-reports/` and `verification-summary.json`. All **71 working-tree Python
controls** pass (six belong to the preserved earlier P&R work), and all **eleven
pinned SRAM assets** verify. The original full-capacity SRAM, independent core
reference, firmware, retained/deep-sleep and reset assertions remain intact.
Evidence lives in `build/supervisor-migration/`.

The final six-case `SupervisorSpec` rerun in `watchdog-hold-focused.log` passes
again after requiring at least two new application watchdog resets during each
tested held reply, excluding earlier startup resets. Its XML and receipt are
in `post-strengthening-reports/` and `post-strengthening-summary.json`. Enabled
and disabled POR campaigns are included in the full clockless suite. The fresh
reviewer found no further issue after these strengthenings.

Both production-capacity exports pass strict `--soc --vector-coverage --sleep-clock`
validation, retain the exact prior-item **34-port public ABI**, and contain three
pinned SRAM macros each. Native Click is checked throughout; supervisor roots,
bridges and all descendants are checked against POR.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 745 | 835,219,500 | `0e5f3986a2e5a4c4c3fa9b1d6f903502c5e2c9830e8255c51a4bd2634cb5461f` |
| Native Click | 599 | 658,292,015 | `199a2b45f18057c95e6c3fef708163cb7bd40f0ca5e4cfbedbec0559c324c72c` |

Receipts are `four-phase-strict-final.log`, `click-strict-final.log` and
`strict-summary.json`; exports are `four-phase-preserved-soc/` and
`click-preserved-soc/`. ABI comparisons are in `public-abi-verified.json`.
The larger complete probes use a 7200-second simulation allowance; coverage,
reset, native-protocol and mapping assertions remain enabled.

Use fresh output directories for reproduction:

```powershell
python tools/sbt.py 'verification/test' 'physical/test'
python tools/sbt.py 'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/supervisor-recheck/four-phase-soc' 'twoPhaseClick/runMain riscay.click.EmitClickSoc build/supervisor-recheck/click-soc'
python tools/check_export.py build/supervisor-recheck/four-phase-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
python tools/check_export.py build/supervisor-recheck/click-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 7200
```

The interrupted pre-retention regression remains in
`regression-before-boundary-retention.log`; it is not counted as a completed pass.
Earlier failures remain in `first-integration.log` and `integration-repair.log`
(Boolean status padding during elaboration) and `*-strict-initial.log` (constant
acquisition flags removed from the registered ABI). Explicitly retaining the
complete registered capture boundary fixes the ABI; no check is removed.

No physical timing or power qualification is claimed. Entire native transforms,
feedback forks, capture pulses and crossings require item 17 characterization.
Historical baseline `8637099` P&R is not applicable to this RTL.

## Asynchronous scaling and CRC migration

Item 4 moves elapsed fractional time and ADC rational arithmetic into separate
native pipelines, with POR-only capture/publication bridges. Four byte stages in
each Control feedback path precompute CRC candidates; Stored commits accounting
atomically. The [migration contract](async-soc-migration.md#scalingcrc-scope-and-contract)
defines the remaining clocked boundaries and timing limits.

A fresh independent review prompted a live-target guard on one-tick observation
credit. Regression fixes preserve the existing host reply path by keeping CRC
precomputation in feedback, and preserve sleep opportunities by allowing the
unchanged seven-edge ordinary drain guard to overlap tracked native maintenance.
BD telemetry return tracks the existing clocked bridge ACK; Click reply acceptance
restores bridge idle. Full synchronized demand and falling-edge gating remain.
The original Groundlark sleep, loader/brownout and firmware assertions are intact.

`AsyncScalingSpec` uses independent wide-integer oracles without a service clock:
fractional and zero elapsed updates, target/quotient wrap, large denominators,
backpressure and POR during an actual arithmetic stage or held reply. The existing
exhaustive 4096-code ADC checks and fractional catch-up oracle remain. Their
in-flight stimulus now waits for observed native handoff instead of assuming a
fixed number of service edges. Wrapper tests stop the service clock after handoff,
check that native arithmetic finishes without premature consumed-time publication,
and reject stale one-tick observation credit. Repeated real application watchdog
resets leave these POR-owned calculations intact.

Maximum-cell-delay tests check sample start through complete bridge drainage at
10 ns, 100 ns and 1 ms service periods, preserving the 16-edge plus 1 us digital
budget. SPI integration checks first-conversion discard, negative offsets,
calibration, exactly-once publication and POR. Native Java CRC32 oracles cover
all-zero/all-one/random images, early/duplicate completion, queued recovery and
POR inside a byte stage. Sleep tests check stalled publication, accelerated
maintenance, ordinary activity on the last maintenance edge and reset after
grace has expired, retaining all seven guard edges.

The final audit tightened watchdog activity evidence to exclude POR pulses and
require at least two application resets during each elapsed/sample path's pending
lifetime. The fresh reviewer confirmed the counter separation and unchanged
oracles. All eight `ScalingSpec` cases pass again in `watchdog-counter-focused.log`,
with XML and counts under `post-strengthening-reports/` and
`post-strengthening-summary.json`. This covers busy lifetime, including capture
and drainage; it does not assert a particular internal arithmetic stage at reset.

On 2026-10-09, `full-regression.log` passes all **145 verification tests across
nineteen suites** and **two core physical-policy tests**, with no failed, aborted,
skipped, canceled or pending cases. Evidence is retained under
`build/scaling-crc-migration/`, including XML snapshots in `verified-reports/` and
counts in `verification-summary.json`. The working-tree Python run passes **70
controls** (six belong to the preserved P&R work), and all **eleven pinned SRAM
assets** verify (`python-feedback.log`, `sram-assets.log`). Focused guard and
drainage results remain in `guard-export.log` and `registered-drain-focused.log`.

Both production exports pass strict `--soc --vector-coverage --sleep-clock`
validation, retain the prior item's exact **34-port public ABI**, and contain
exactly three pinned SRAM macros each. Native Click is checked throughout.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 638 | 538,434,358 | `e199754ebc99e73519f744a20ea86714401900a3e9f3204d990618546be30a76` |
| Native Click | 517 | 430,199,836 | `d41c5448c6aa4debef40f248340c9e1156be2b40cc9496310af39f2817a3507b` |

Exports are `four-phase-preserved-soc/` and `click-preserved-soc/`; receipts are
`four-phase-strict-final.log`, `click-strict-final.log`,
`strict-summary.json` and `public-abi-verified.json`. The larger hierarchy uses a
3600-second simulation timeout with every mapping and coverage check retained.
The fresh reviewer found no further actionable issue after the observation and
gate-drainage fixes.

```powershell
python tools/sbt.py 'verification/test' 'physical/test'
python tools/sbt.py 'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/scaling-crc-migration/four-phase-preserved-soc' 'twoPhaseClick/runMain riscay.click.EmitClickSoc build/scaling-crc-migration/click-preserved-soc'
python tools/check_export.py build/scaling-crc-migration/four-phase-preserved-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 3600
python tools/check_export.py build/scaling-crc-migration/click-preserved-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock --probe-timeout 3600
```

Earlier failure evidence remains: `initial-focused.log` (constructor signature),
`stage-signature-focused.log` (old fixed-edge test stimulus),
`expanded-focused.log` (test bindings plus genuine sleep/host-latency failures),
`review-fixed-focused.log` (test utility typing), `feedback-crc-focused.log` and
`boundary-binding-focused.log` (binding/latency iterations),
`explicit-drain-focused.log` (redundant BD return synchronization), and
`*-strict-first.log` (optimized-away declared boundary fields). No strict ABI,
coverage, reset or native-Click check was removed; declared boundaries are retained.
The `*-strict-preserved.log` attempts reached their 1200-second simulation limit;
`*-strict-final.log` reruns the same complete probes with a longer time allowance.

No physical timing or power qualification is claimed. The new entire arithmetic
transforms, feedback paths, capture pulses and crossings need item 17
characterization. Historical baseline `8637099` P&R remains inapplicable.


## Asynchronous GPIO, events and telemetry migration

Item 3 adds separate native `FourPhaseTelemetry` and `ClickTelemetry` state loops
for software GPIO/application words, pending flags and host sample records.
Clocked ingress compacts publications without losing attempt counts, latest
status, last successful value or elapsed age. At item 3 completion, the permanent
supervisor's safety view was still clocked; item 5 later replaces it with a
dedicated native loop consuming the same publications. See the
[exact scope and contract](async-soc-migration.md#gpioeventstelemetry-scope-and-contract).

A fresh independent reviewer caught a host-visible event flag disappearing while
its Observe command was in flight. Both implementations now retain dispatched
flags in an application-reset-owned projection until reply. The reviewer also
requested direct host freshness coverage during publication stalls; those tests
check both queued and dispatched updates, retained coherent value/sequence,
advancing age, and fresh-valid suppression while the stale bit is still false.

`AsyncTelemetrySpec` adds four clockless cases: sixteen delay seeds per ordinary
stream and three POR-abort seeds per variant, with independent expected states.
`TelemetrySpec` adds ten integration cases with actual native bridges paused:
accepted-publication reset retention, short raw-reset pulses, stalled host event
visibility, compacted successes/failures, exact sequence/age accounting, CPU
progress when every edge ticks, deadline replacement and host freshness.
Existing test assertions and activity limits are unchanged.

Initial evidence under `build/gpio-telemetry-migration/`: all 37 focused
AsyncTelemetry/Fabric/Sleep/DeepSleep cases pass (`focused-first.log`), all ten
integration cases pass (`integration-second.log`), and 69 working-tree Python
controls pass (`python-second.log`, including six preserved P&R controls).
All eleven pinned SRAM assets verify. `full-regression.log` passes all **121
verification tests across sixteen suites** and **two core physical-policy tests**,
with no failed, aborted, skipped, canceled or pending cases. The XML snapshots
and counts are in `verified-reports/` and `verification-summary.json`.
Both refreshed exports retain the preceding MMIO/loader exports' identical
34-port public ABI (`public-abi-verified.json`). After preserving the registered
capture boundary, all 28 AsyncTelemetry/Telemetry/Fabric cases pass again in
`checked-emit-focused.log` (XML in `post-preservation-reports/`). Both production
exports pass strict `--soc --vector-coverage --sleep-clock` validation. Each has
exactly three pinned SRAMs; native Click is checked throughout the hierarchy.

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 397 | 230,090,084 | `dce56e1ebe70d6fbf790c1891037e7272f709f8a05d954930a33bc5e71f293cf` |
| Native Click | 312 | 175,825,104 | `4a84ce3b4c4193fb25e6ddbc49042e8418ceee386758c73ed4bfb55cb8726a75` |

Exports are `four-phase-checked-soc/` and `click-checked-soc/`; receipts are
`four-phase-strict-checked.log`, `click-strict-checked.log` and `strict-summary.json`
in the same evidence directory. The fresh review's final pass found no remaining
RTL issue and corrected one outdated contract sentence. All mapping comparisons,
activity requirements and original regression expectations remain intact.

```powershell
python tools/sbt.py 'verification/test' 'physical/test'
python tools/sbt.py 'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/gpio-telemetry-migration/four-phase-checked-soc' 'twoPhaseClick/runMain riscay.click.EmitClickSoc build/gpio-telemetry-migration/click-checked-soc'
python tools/check_export.py build/gpio-telemetry-migration/four-phase-checked-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock
python tools/check_export.py build/gpio-telemetry-migration/click-checked-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock
```

Retained failure evidence includes the initial elaboration cycle, empty-vector
schema rejection, test-fixture source-info syntax error, and strict port mismatch
for a profile-constant acquisition calibration field. Native channel schemas
omit empty vectors and preserve the complete registered capture boundary.
The export adapter checks each telemetry controller, bridge and descendant uses
POR, rejects incomplete/wrong-owner inventories, and rejects hidden RTZ logic
inside standalone ClickTelemetry. Independent Python controls deliberately
miswire every telemetry reset boundary. These digital checks do not establish
physical timing qualification or validate old P&R against the new RTL.

## Asynchronous MMIO and loader migration

Separate `FourPhaseControl` and `ClickControl` state-token loops own loader
validation, image metadata/accounting, lock, command mode/error/start state,
host selector and MMIO producer/application selectors. Native MMIO preparation
is reversible; accepted staging writes use a separate retained commit command.
Clocked host ingress, arbitration, snapshots, MODE/start reset projection,
GPIO/event/timer effects, SRAM byte sequencing and wire peripherals remain.
This is checklist item 2's scope, not a fully asynchronous peripheral subsystem.

A fresh independent reviewer identified lost reset requests, stale queued HALT,
staging mutation before CPU acceptance, and host busy-context loss, including
same-edge enqueue/admission. These are fixed in both implementations.
`ControlResetSpec` has twelve directed cases that stall the real native bridges
and test reset/commit/accounting boundaries. `AsyncControlSpec` has four clockless
cases with an independent byte-frame/state oracle and Java CRC reference:
16 cell-delay seeds per normal stream and three POR-abort seeds per variant.
Existing MMIO/event, MODE reset, SRAM, sleep and firmware assertions are retained.

The export adapter distinguishes the three named POR-owned Control children
from application-reset-owned CPU children and validates their exact owners and
complete inventory. An independent negative control rejects each miswired reset.
Explicit two-slot register mailboxes avoid an unregistered inferred Queue module;
unused registered fork/bridge port fields remain present for strict ABI checks.
The reviewer checked both changes and found no further actionable issue.

Mapping-only stimulus selects real MMIO addresses and walks native command/state
storage payloads through valid frame/decode combinations. Original bit walks,
paired fallback, endpoint comparisons and activity requirements remain intact.
An independent SV fixture rejects a disconnected bit; review also corrected Vec
byte order in the new stimulus. Reply readiness requires command ownership.
The period reply carries an ungated candidate, while `periodUpdate` alone enables
its clocked effect; invalid candidates still return an error and cannot update it.

The first whole-suite run (`final-regression.log`) passed 105 of 107 cases. Its
two activity-estimate elaboration failures referenced an optimized-away work-clock
alias. The monitor now uses the actual Control command bridge clock, preserving
all activity thresholds. `first-reports/` retains those original XML reports.
Other retained failures include the original event-clear and synchronized-MODE
assertions, fixture setup/elaboration errors, unregistered Queue/port ABI errors,
and the initial strict activity failures. No failed run is counted as a pass.

Both production-capacity exports pass strict `--soc --vector-coverage --sleep-clock`
validation, including native Click throughout, separate POR/application reset
fanout and exactly three pinned SRAMs each. All 34 public top-level ports match
the preceding SocFabric exports (`public-abi-verified.json`).

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 290 | 124,673,030 | `89a837b257e6e12cc940aeda02223a44f2cbbb1c6f9de66d4edd13abe307b5f9` |
| Native Click | 230 | 96,641,860 | `c5137cfe542d02f9bad754e66d3a65488796681b898d9c512b43b799ed7b8df9` |

Exports are `four-phase-checked-soc/` and `click-checked-soc/` under
`build/mmio-loader-migration/`; receipts are `bd-strict-checked.log` and
`click-strict-checked.log`. All 68 Python working-tree controls pass
(`python-verified.log`), including six preserved P&R controls outside this commit;
all 11 pinned SRAM assets verify (`sram-assets.log`).

The final run in `verified-regression.log` passes **107 verification tests across
fourteen suites**, followed by **two core physical-policy tests**, with zero
failures, aborted suites, skipped, canceled or pending tests. This includes both
independent service/scaling implementations, native routing/control, core reference
and guard controls, real I2C firmware uploads, all sleep/reset/SRAM cases, and the
corrected activity estimates. `verification-summary.json` and `verified-reports/`
preserve the final XML results. Earlier failing runs remain available under
`build/mmio-loader-migration/`. This completes checklist item 2's digital scope.
No new controller has physical timing qualification. Its simulation transform
budget does not qualify mapped decode/CRC, fork, pulse, CDC or reset paths.

Run the whole final campaign in one sbt process:

```powershell
python tools/sbt.py 'verification/test' 'physical/test'
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/sram_assets.py --verify-only
python tools/check_export.py build/mmio-loader-migration/four-phase-checked-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock
python tools/check_export.py build/mmio-loader-migration/click-checked-soc --library P:/Personal/chisel-async --soc --vector-coverage --sleep-clock
```

## Asynchronous SocFabric migration

The following results describe SocFabric commits `7f07f01` and `c6102bd`, before
the MMIO/loader item above. At that stage, separate native fabrics handled
ROM/static faults without clocks, while stateful MMIO/loader and peripheral
logic was still clocked in each design's Services/Platform files. Historical
results apply only to their stated RTL; previous P&R does not qualify the new
controllers. The [checklist](async-soc-migration.md) defines the current scope.

The fresh independent review of `7f07f01` identified unenforced composed Click
guard bounds and optional fabric timing declarations. The follow-up enforces a
Simulation-only ClickFabric policy, the strict 80.2 ns drainage inequality,
capture setup/hold observations and a mandatory per-fabric timing inventory.
Actual guard pins are compared with the native phases and public channels.
All nine focused tests pass with capture-register setup/hold/pulse monitors;
all 66 working-tree Python controls pass, including seven fabric-export controls
and six preserved P&R controls. Receipts under `build/async-fabric-migration/`:
`review-focused-emit-2.log`, `review-python.log`, `review-bd-strict.log`, and
`review-click-strict.log`. The first focused attempt's testbench syntax error
and the later incorrect sbt project name are retained in the review logs.
The fresh Click export is `build/async-fabric-review/click-soc/`, with semantic
SHA-256 `7e8f05de6fc5ce2afe215c24a948b0bdcc1bf1662d2ef29864f1ff313cd1ad57`.
Endpoint/mapping counts remain 148/5,229,728. The unchanged BD export is rechecked
with the stricter adapter. These changes do not alter synthesized functional RTL
or establish physical timing qualification.

Run one sbt process at a time. On this Windows workstation:

```powershell
$env:JAVA_HOME='P:\Personal\chisel-async\.tools\jdk21\jdk-21.0.12.1+1'
$env:CHISEL_FIRTOOL_PATH='P:\Personal\chisel-async\.tools\firtool-1.160.0\firtool-1.160.0\bin'
python tools/sbt.py 'verification/testOnly riscay.AsyncFabricSpec riscay.FabricSpec riscay.ScalingSpec'
python tools/sbt.py 'verification/testOnly riscay.SramSpec riscay.SocSpec riscay.SleepSpec riscay.DeepSleepSpec riscay.FirmwareSpec riscay.CoreSpec riscay.NativeRoutingSpec riscay.HostSchemaSpec'
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/sram_assets.py --verify-only
```

`AsyncFabricSpec` uses clockless native ports and automatic handshake/data-hold
monitors across delay corners and seeded cell variations. Its independent oracle
checks all boot words, static faults/invalid MMIO widths, alternating local and
service traffic, endpoint errors, separate response/request return stalls, 2 fs
source reuse and endpoint latency, payload reuse, reset with a pending endpoint
or stalled reply, and HALT without a fabricated completion. The Click negative
control must reject bypassed release guards for capture-drain violation.
`FabricSpec`, `ScalingSpec` and `SramSpec` each run the same independent oracle
against both separate implementations.

The export adapter recognizes only the two MCU fabric response-mux path kinds,
checks their native port schema/storage/owner and retains all library budget,
marker, mapping and activity checks. Added probes compare the BD mux to reply
storage and the Click data/capture endpoints to event-register pins. Independent
negative controls reject wrong owners, protocols, widths, missing/changed guards
and disconnected pins. A complete Click hierarchy is also checked for RTZ
channels, four-phase helpers or closing-latch primitives.

On 2026-10-08, **89 distinct verification tests across eleven suites**, plus
**two core physical-policy tests**, have passing final results with no skipped,
canceled or pending cases. All **64 Python working-tree controls** pass, including
five new fabric-export controls and six pre-existing P&R controls preserved
outside this migration commit. All 11 pinned SRAM assets verify unchanged.

The native fabric stream uses 64 cell-delay seeds per variant, plus independent
fast-source/endpoint and reset campaigns. FabricSpec has 14 cases, ScalingSpec
two and SramSpec eight, covering both independent implementations. Both compiler
firmware workloads pass on both SoCs. The seven inherited BD failures are fixed.
Host ABI expectations, watchdog/reset, lock, sleep and memory assertions were
retained. All 34 public top-level port names, widths and directions match the
prior exports. The service-clock `commit` observation covers endpoint acceptance;
ROM/static-fault traffic now completes outside that observation boundary.

Fresh exports pass `--soc --vector-coverage --sleep-clock`:

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 183 | 29,518,632 | `4e5e1052d28c2403aa2a06fce5f8002fb7c62c3619f285d4283b20fb13d28218` |
| Native Click | 148 | 5,229,728 | `ec5902e50824ab4fe0862ef59156496bca7f8a5a661223afae210824b2661142` |

Each export retains exactly three pinned SRAM instances. Click's complete async
hierarchy contains no RTZ channels, four-phase helpers or closing latches.
Exports are `build/async-fabric-migration/four-phase-final-soc/` and
`click-verified-soc/`; receipts are `four-phase-strict-final.log` and
`click-strict-verified.log` in that parent directory.

`verification-summary.json` consolidates individual test results across the
preserved XML reports. Passing campaigns are `return-ack-regression.log`,
`focused-expanded.log`, the first five-suite command in `final-regression.log`,
`click-final-regression.log`, and `verified-focused-emit.log`. Python/asset
receipts are `python-final.log` and `sram-assets.log`.

Failure evidence remains: inherited `regression.log` (41/48), the earlier lock
error, focused port-name/handshake failures, initial strict path/scope failures,
and the later 11 Click elaboration failures in `final-regression.log` from an
unsized probe alias. That alias has an explicit width in the passing rerun.
The BD repair retains endpoint acknowledgement through request return and waits
for both endpoint channels to drain. Click guards cover its composed control
path; endpoint parity and reply payload now share the capture pulse, avoiding
a separately gated pulse that could be filtered by cell skew.

This completes **SocFabric's digital migration item**, not the remaining clocked
service-state items or physical qualification. The physical-policy tests check
the unchanged core policy; they do not qualify the new fabric controllers.
No new P&R, extracted timing closure, analog SPICE or power result is claimed.

## WAIT validation and bounded storage

The 2026-10-08 review fixes validate full-word MMIO accesses before applying
boot/WAIT blocking, parking or lease consumption. The directed fabric case
tests all 15 unsupported masks at both blocking registers, with empty and
GPIO-pending event sets, and checks prompt errors, no sleep eligibility and
unchanged events/leases. A valid WAIT still consumes its lease.

SRAM tests cover full-capacity loader counts, the highest legal entry point,
oversized/misaligned host fields, rejected writes beyond capacity, and one-word
and non-power-of-two memory configurations. These checks prevent narrowing from
turning rejected addresses or metadata into valid aliases. The loader reset
probe now observes the internal word counter; host checks remain byte-based.

All **68 distinct Scala/Icarus tests across ten suites** have passing final
results, with no skipped or canceled cases; all **44 Python controls** also
pass. CoreSpec ran in `build/review3-focused.log`, and the other nine suites in
`build/review3-regression.log`. That broad run initially hit one compile failure
because the reset test referenced the removed byte-counter signal. After fixing
the test probe, its focused rerun passed in `build/review3-loader-reset.log`.
`build/review3-test-reports/verification.json` records the final result for each
test and preserves both the original reports and corrected rerun. Python
evidence is `build/review3-python.log`; all 11 pinned SRAM assets verify unchanged.

Both regenerated production exports pass strict `--soc --vector-coverage
--sleep-clock` validation:

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 158 | 5,691,792 | `786e52b469df90eaecff3ae0420c1856249c0f1e62c8a7b3ba9162c1714108f5` |
| Native Click | 132 | 4,573,536 | `dd50c92214a28160a55fc384aa68d3132b5a5a3882fdb273d988799a19ba4571` |

The GF180 remappings under `build/review3-mapping/` retain three physical SRAM
instances and no inferred arrays. Compared with `build/sram-mapping/`, unique
flip-flop drivers for the two saved SRAM indices plus image length, entry and
received metadata shrink from 155 to 46 per design. Total mapped standard-cell
flip-flops decrease from 2,233 to 2,105 for BD and 2,235 to 2,107 for Click.
Separately, async state/join/execute payload widths shrink from 178/178/285 to
171/171/278: 21 logical storage bits removed per core. The receipt is
`build/review3-mapping/storage-verification.json`. These netlist counts are not
new whole-chip area, leakage, energy or physical timing estimates.

Export evidence is in `build/review3-{four-phase,click}-soc/` and
`build/review3-{bd,click}-check.log`. Analog circuits and pinned SRAM assets are
unchanged; transistor-level SPICE was not rerun for these digital changes.

## SRAM migration verification

The current Groundlark baseline is 2 KiB program SRAM and 1 KiB working SRAM,
using three pinned GF180 macros in both native variants. Earlier records below
that cite 256-byte working RAM or flip-flop arrays are historical.
[SRAM integration](sram-integration.md) describes the physical views and limits.

```text
python tools/sram_assets.py
python tools/sbt.py "verification/testOnly riscay.SramSpec riscay.FirmwareSpec riscay.SleepSpec riscay.DeepSleepSpec riscay.FabricSpec riscay.SocSpec riscay.HostSchemaSpec riscay.ScalingSpec"
python tools/sbt.py "verification/testOnly riscay.CoreSpec riscay.NativeRoutingSpec"
python -m unittest discover -s tools -p "test_*.py"
```

The migration passed **66 distinct Scala/Icarus tests** across ten suites,
including three SRAM tests, plus **44 Python controls**. The full-capacity sweep checks every program/data
word and all 16 byte masks, with independent macro write counts and stable
backpressured replies. SRAM input launch checks run at 20 MHz. Watchdog and POR
are injected at each word-transfer phase, including loader writes; completion
accounting, retained stores and discarded CPU replies are checked separately.
The original core corner/fastest-memory tests and deliberate checker-failure
controls remain passing. Both compiled C images run on both native SoCs with
unknown initial SRAM, real I2C uploads, sleep retention and programming lock.

Program sizes and stack bounds remain 728/20 bytes for `event_loop` and 1212/88
for `runtime_stress`. Moving the stack top to `0x20000400` changes binary hashes:
`4e397b4f7af198df7479f8ff3f4c3941b735a086ca6a0e438764976c951ae301` and
`19c8c548606dcd88f099ef0822c690f3928d8cdf026ca7c0ef47ed58b878f6e3` respectively.

Strict exports use the unchanged chisel-async contract plus a `sram.json`
technology inventory. The MCU adapter checks exact pinned model content, macro
instance paths/counts, pin widths and the elaborated 1024-by-8 array before
admitting those scopes. Missing/extra/wrong-sized/modified macros are rejected;
all existing reset, endpoint and mapping probes remain active.

Recorded full-capacity exports under `build/sram-{four-phase,click}-soc` pass:

| Variant | Endpoints | Mapping checks | Semantic SHA-256 |
| --- | ---: | ---: | --- |
| Four-phase BD | 158 | 5,897,824 | `4144eaaf28f680458f6af912e4cdd86691dc902821e934884bd4b1bf376f7e5a` |
| Native Click | 132 | 4,738,272 | `73fc23934576ffd909f2d9b8e60e970c5a7774eb311d47c8c8fec6ccab8bdffa` |

Logs are `build/sram-regression.log`, `build/sram-export-core.log`,
`build/sram-final-interface.log`, `build/sram-python-controls.log` and
`build/sram-{bd,click}-check.log`. The final interface run also verifies a host
WAKE accepted during an in-flight instruction fetch. Both synthesis mappings under
`build/sram-mapping/` retain exactly three physical SRAM black boxes and
no inferred memory arrays; `build/sram-mapping/verification.json` records the
instance and contract checks. Suite XML records are saved in
`build/sram-test-reports/`. This is a technology-binding check, not macro timing
signoff, placement or a new whole-chip area/power estimate. Icarus's unsupported
upstream vector `specify` paths are documented in the SRAM integration notes.


## GF180 estimation

The current SRAM revision requires a new macro-aware area/power report. The flow
and results in this section describe the historical flip-flop baseline; its
reporter intentionally rejects SRAM cells it cannot account for. Mapping can
still verify that the three physical instances survive synthesis. Do not quote
the old area/leakage/wake estimates as results for the SRAM design.

The [physical estimate](gf180-estimates.md) has a separate reproducible cost flow;
it does not turn simulation primitives into qualified hardware. That estimation
run used RTL baseline `4b5d105` and changed neither production RTL nor analog
netlists. Later review fixes have changed RTL; the recorded figures need
regeneration before use for current designs. `PhysicalEstimateSpec` uses full memories and
an enabled **estimate fixture** policy, while reference emitters keep their safe
disabled defaults. Its clock/ADC/firmware observations are not physical timing.

```text
python tools/sbt.py "verification/testOnly riscay.PhysicalEstimateSpec"
python -m unittest tools.test_gf180_estimate -v
```

The simulation writes `build/gf180-estimate/{four-phase,click}-export.txt`, each
containing the newly generated export path. For each path, run:

```text
python tools/gf180_estimate.py --export <four-phase-export-path> --output build/gf180-estimate/four-phase
python tools/gf180_estimate.py --export <click-export-path> --output build/gf180-estimate/click
python tools/gf180_estimate.py --export <four-phase-export-path> --output build/gf180-estimate/four-phase-activity --activity
python tools/gf180_estimate.py --export <click-export-path> --output build/gf180-estimate/click-activity --activity
python tools/gf180_estimate.py --report --output build/gf180-estimate
```

Mapping requires sv2v 0.0.13 at `.tools/physical/sv2v`, Yosys/ABC 0.33 binaries
under `.tools/physical/root/usr/bin/`, and Yosys share files at the corresponding
`usr/share/yosys/`. On the recorded Windows workstation, mapping runs through
Ubuntu WSL; Icarus runs natively. Ubuntu Noble packages `yosys` and `yosys-abc`
version `0.33-5build2` can be downloaded with `apt download` and locally extracted
with `dpkg-deb -x`; no system installation is required. The sv2v binary was copied
from the workstation's existing 0.0.13 installation. Exact binary hashes are in
[the input manifest](../tools/gf180-estimate-inputs.json).

Provide complete installed GF180 `mcu7t5v0` Liberty files under
`.tools/physical/liberty/` named `tt_025C_3v30.lib`, `ss_n40C_3v00.lib` and
`ff_125C_3v60.lib`. The recorded files come from the existing `gf180mcuD` PDK built
by open_pdks `40cee970d8a9b7eaea35a34fe7d6068f05721f0a`. Its cell data are Apache-2.0.
The upstream repository's top-level Liberty files alone are templates without
cell bodies, and are rejected. Complete-library hashes are in the input manifest.
The estimator rejects changed tool/library hashes. Intentionally changing them
requires updating the manifest, regenerating and reviewing the estimates.

Reporting also consumes the previously passed analog reports
`build/clock-reset-clock-01/report.json`, `build/clock-reset-monitor-05/report.json`,
`build/clock-reset-events-03/report.json`, and `build/lf-osc-final-pvt/report.json`.
If those ignored artifacts are absent, reproduce their documented campaigns
below into those directories. Failed or missing evidence is an error. The report
records its script, library, netlist, contract, waveform-observer log and analog
report hashes. All generated RTL/netlists/logs remain under ignored `build/`.

The 2026-10-07 run passed both activity simulations and all ten estimator tests.
Both mappings completed with only the explicitly budgeted async black boxes;
all 18,432 writable-memory bits survived as flip-flops. No placement/CTS/DRC/LVS
or extracted power check was run. Source behavior was unchanged, so the existing
functional/strict-export record below was not rerun for the estimation scripts.

## Digital build

The build consumes the chisel-async RC1 JAR; it does not compile a second copy of
the library in this repository. Required versions are Scala 2.13.18, Chisel/plugin
7.16.0, firtool 1.160.0, sbt 1.12.4, JDK 21 and Icarus Verilog 13.

Install RC1 into the local Ivy cache by running `sbt publishLocal` from a pinned
chisel-async RC1 checkout, or add the resolver for its released Maven ZIP using
the [library installation guide](https://github.com/BiscutLabs/chisel-async/blob/main/docs/getting-started.md).
Maven Central does not currently host that RC. Point `JAVA_HOME` at JDK 21 and
`CHISEL_FIRTOOL_PATH` at the directory containing firtool; put `iverilog` and `vvp`
on PATH. There is no required sibling-checkout path in this build.

From the repository root:

```text
python tools/build_firmware.py --bootstrap
python tools/sbt.py --bootstrap test
python tools/sbt.py "fourPhaseBd/runMain riscay.bd.EmitFourPhase build/four-phase-bd"
python tools/sbt.py "twoPhaseClick/runMain riscay.click.EmitClick build/two-phase-click"
python tools/sbt.py "fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/four-phase-soc"
python tools/sbt.py "twoPhaseClick/runMain riscay.click.EmitClickSoc build/click-soc"
python -m unittest discover -s tools -p "test_*.py" -v
```

The sbt bootstrap fetches and checksum-verifies only the pinned sbt launcher. It does
not install Java, the compiler, the library or a simulator. With sbt already
installed, the same task strings work directly with `sbt`.

The separate firmware bootstrap extracts pinned RV32E-capable GCC 13.2.0 and
binutils 2.42 packages under `.tools/`; on Windows it uses Ubuntu WSL. See the
[firmware guide](../firmware/README.md) for platform prerequisites and budgets.
FirmwareSpec and the Python linker controls require that compiler; missing tools
are failures. Subsequent firmware builds do not need `--bootstrap`.

Generated RTL/manifests and simulation evidence remain in ignored `build/`.
Each SoC emitter also produces `chip/` with internal LF, stoppable fast-source
and supply-monitor boundaries, a synthesizable reset sequencer, synthesis black
boxes and separately selected simulation models. See
[sleep and clocks](sleep-and-clock.md). The parent export's strict contract
checks cover the digital SoC; they do not validate the analog black box.
`CoreSpec` covers arithmetic, signedness, x0, memory widths/lanes, branches/jumps,
faults, reset during an outstanding fetch and a deliberately wrong expectation
that must fail its retirement checker. Both designs consume the same independent
reference traces. `NativeRoutingSpec` tests native phase fork/join under skewed
arrival, stalls, repeated values and reset with one unmatched operand.
The core suite also uses minimum-visible 2 fs memory responses concurrent with
request acknowledgement/return. At cell corners and varied delays, it checks
writeback completion before forwarding; a bypassed guard is a required failing
control. Register read muxes are included in the execute transform's budget.

`HostSchemaSpec` verifies the logical host catalog with Groundlark and an unrelated
counter fixture, including absent/unknown resource rejection and invalid profile
bindings. This checks schema/configuration separately from the RTL suites.

`SocSpec` drives both complete designs through modeled open-drain I2C and SPI ADC
pins. It covers bounded uploads, wrong ABI/range/incomplete/corrupt images,
validation/start/lock, RAM byte lanes, code-store rejection, bus/full resets,
independent watchdog recovery (including a stopped service clock), unprogrammed
Groundlark boot, protected control outputs, shutdown acknowledgement, minimum-off
timing and the three-timeout latch. CRC expectations come from Java's CRC32;
firmware is hand-encoded using test-only assembly helpers.

`FirmwareSpec` adds real compiler-built C images at the full 2 KiB/1 KiB
capacities. Both native SoCs receive each binary through the I2C loader and
CRC/START_AND_LOCK flow, then execute startup/data/BSS initialization, arithmetic,
stack frames and retained sleep. Retirement SP writes, a RAM watermark and a
guard check independently corroborate GCC's stack bounds. These finite generic
fixtures are not deployment firmware. `test_firmware.py` checks rejection of
unknown/dynamic/recursive stacks, unsupported ISA and real undersized links.
It also compiles the actual event helper against mapped MMIO storage on Linux
(Ubuntu WSL on Windows), requiring native `gcc`, to verify that WAIT preserves
events arriving during processing and acknowledges only consumed bits.
Full-capacity compiled-image simulations have a bounded 300-second process
allowance; other clocked harness tests retain their 90-second default.

`FabricSpec` drives both independent clocked service implementations through
the common bus schema, independently of the CPU, to check
response stability under backpressure, exactly-once acceptance, ROM/unmapped
errors, event/clear races, deadlines, failed/stale samples, interrupted upload,
reset cancellation and zero-channel/zero-GPIO configurations. Groundlark tests
accelerate the millisecond divider and ADC cadence together; their enabled
fixture is not a deployment policy. Test watchdog clocks are accelerated too.
Additional fabric cases cover queued watchdog kicks, lease writes with no kick,
sparse application-register holes and reads spanning concurrent word updates.
Deadline cases cover stale pending expiry, replacement coincident with expiry
and GPIO, rejected writes, a blocked next WAIT and an already-due replacement.
Reset cases verify two-flop assertion/release latency against the raw reset,
immediate application reset, complete gated clock pulses and POR-only crash
counting. Production-ratio Groundlark cases read counts 1 and 2 after separate
crashes while checking that power, lock and supervisor state remain retained.
`ScalingSpec` exercises both independent implementations and exhaustively
checks all 4096 ADC codes against independent integer
division, plus fractional tick accumulation, large missed-tick deltas, counter
wrap, updates during catch-up and POR during native calculation. Clock-stall
and repeated application-watchdog cases verify publication ordering and retained
fractions; maximum-delay cases check the sample bridge's full drainage budget.

`SleepSpec` covers both CPUs parked through masked millisecond ticks, timed and
host wake, finite watchdog-serviced leases, RAM/image-lock retention, runtime
ADC cadence, invalid period rejection, repeated updates without starving sensing,
and full reset with a closed clock gate. Both native variants also execute
through the chip wrapper's behavioral on-die oscillator. Independent service-bus
tests cover GPIO/entry races, held responses/exactly-once effects, pending wake
and wall-time/sample-age advancement after a short service-clock interruption.
The permanent Groundlark controller cold-starts without a program and performs
shutdown/ACK with a sleeping service island. That long-duration fixture uses
small RAM capacities to avoid unnecessary simulator cost; production-capacity
emission and strict exports remain separate checks.

`DeepSleepSpec` adds both native CPUs with the service oscillator actually
stopped/restarted, the address-only I2C wake protocol, 0/15/100 us startup cases,
8/10/20 MHz service-model frequencies, slow Gray tick transitions, nominal-time
fraction carry, conservative sample aging, board minimum-off/ACK behavior,
retained RAM/lock and watchdog recovery. LF clocks are accelerated in the SoC
fixtures; the LF model's actual nominal period is checked separately.
The Groundlark case retains the production 32-edge watchdog ratio and deliberately
traps locked firmware in RUN and SHUTDOWN, checking uninterrupted Pi power,
shutdown state, live sensing and lock preservation. Host timeout cases abandon
write/read transactions, hold SDA low, continue foreign-address data clocks and
then recover a normal read. None may keep the fast oscillator enabled indefinitely.

`test_oscillator_model.py` runs Icarus checks of POR startup/restart, nominal slow
frequency, error response, bounded period jitter and invalid-frequency
rejection. `test_service_oscillator.py` checks cancelled startup, complete final
high pulses, stopped-clock silence, restart, and rejection of invalid bounds.
These tests establish the models' behavior, not analog feasibility,
PVT accuracy, energy, metastability or physical clock-gate timing.

The clocked harness uses `ExportDesign` and the library's actual primitive models;
`AsyncTest` continues to cover the clockless cores and native routing with seeded
delay variation. Every SoC simulation has a deadline, process timeout and required
completion/assertion checks. No skipped/missing simulator is treated as success.

These are initial directed/generated tests, not complete RISC-V architectural
qualification, complete reset-phase coverage, real Pi validation or silicon
timing/metastability qualification. Deployment firmware and real Pi/analog
validation remain subsequent qualification work.

For strict export validation, use the matching chisel-async checkout's tooling
through the MCU timeout adapter:

```text
python tools/check_export.py build/four-phase-bd --library /path/to/chisel-async
python tools/check_export.py build/two-phase-click --library /path/to/chisel-async
python tools/check_export.py build/four-phase-soc --library /path/to/chisel-async --soc --vector-coverage --sleep-clock
python tools/check_export.py build/click-soc --library /path/to/chisel-async --soc --vector-coverage --sleep-clock
python -m unittest discover -s tools -p test_check_export.py -v
```

The library's 60-second component-probe limit was exceeded by both original core
exports. The adapter allows 600 seconds for each generated probe's compilation
and simulation, controlled by `--probe-compile-timeout` and `--probe-timeout`.
Other subprocess limits remain unchanged, and a timeout still fails. Complete
SoCs additionally require the explicit options above:

- `--soc` checks every async child reset against the registered `systemReset`
  endpoint and also checks the external POR contribution. The library's default
  assumption that all children directly use the external reset does not describe
  this SoC's watchdog-generated reset. Primitive-local reset checks stay intact.
- `--vector-coverage` replaces per-bit zero/one accumulation with equivalent
  packed two-state conversions of both value and inverse. X/Z count as neither.
  All drivers, mapping comparisons, endpoint coverage requirements and check
  counts are retained. The scalar full-SoC probes exceeded the practical time
  budget; this option reduces bookkeeping rather than deleting mapping cases.
- `--sleep-clock` appends a third single-driver campaign with the native
  `gate_enabled` register held high against an otherwise low background.
  The original low background closes the gate, while the high background blocks
  acceptance through other controls. The added campaign permits commit activity
  without forcing a derived endpoint. Every original stimulus case, comparison
  and coverage requirement remains; the library's paired fallback is retained.
  Use this option for retained-sleep exports, not legacy ungated fixtures.

The Python adapter tests verify timeout overrides apply only to generated probes,
correct reset wiring, deliberately missed watchdog
reset rejection, failure on unrecognized checker/endpoint shape, and coverage
equivalence for all 256 four-bit vectors over 0/1/X/Z, both singly and accumulated.
An independent clock-gated fixture demonstrates that the additional stimulus
covers an initially inactive endpoint and still rejects an incorrect binding.
Clocked helper modules are inlined into the contract root. Constant/partly unused
GPIO outputs remain in `ports.json`, with behavior checked by the SoC suites;
they are not declared as asynchronous timing endpoints that must toggle every bit.

Record actual pass/fail results separately from emitting files. The initial
Windows development run used the local RC1 JAR with SHA-256
`cc37c3baabdf03f2886912082347c34650695c472f6a788d653be9f8932a04ac`.
The version is pinned in the build; this hash records that run, not an enforced
dependency-integrity check or a cross-platform qualification claim.

## Initial Windows verification record

On 2026-10-07, `python tools/sbt.py test` passed all 16 tests in two suites,
with no skipped or pending tests. The suites include 99 passing randomized-delay
simulation runs and two intentionally rejected retirement expectations.
Both variants use the same instruction and memory-effect oracle; the oracle
also has hand-calculated signedness/x0 and branch checks.

Both strict exports passed with the longer probe timeout:

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase core | 110 | 2,367,200 | PASS |
| Native Click core | 84 | 1,563,072 | PASS |

The exported Click instance inventory contains no four-phase storage or phase
adapters. Mapping-check counts describe validator work, not hardware performance.
Raw results remain under `build/`; the final test reports are under
`verification/target/test-reports/`. No whole-MCU, firmware, Linux-host or physical
qualification is implied by this development run.

After adding the generic host schema and separate profile project, the full
`python tools/sbt.py test` run passed 20 tests in three suites on 2026-10-07,
including both core variants and all four new schema tests. No tests were skipped
or pending. A fifth schema test was then added for replacing application bindings
within unchanged hardware resource counts; a targeted HostSchemaSpec run passed
all five tests. At that stage, host/peripheral RTL and physical qualification were
outstanding. CPU RTL was unchanged, so
the strict core exports were not regenerated for this schema-only addition.

## SoC integration verification record

On 2026-10-07, the full `test` task passed 29 tests across five suites after SoC
integration. After inlining the clocked helper hierarchy for export and extending
the loader/policy assertions, a targeted `SocSpec FabricSpec HostSchemaSpec` run
passed all 15 tests. Together with the unchanged core/routing suites this verifies
31 distinct tests: 13 core, 3 routing, 6 schema/policy, 7 complete-SoC and 2 fabric.
There were no skipped, canceled or pending tests.

The SoC harness's deliberately incorrect ABI expectation was rejected as required,
as were the existing two incorrect retirement expectations. Both complete native
designs emit successfully, and Click's emitted contract inventory contains no
four-phase modules/adapters. Existing firtool `VerbatimBlackBoxAnno` warnings remain.
Physical cells, analog behavior, compiler-built applications, real Pi behavior and
Chiselator execution remain outside this digital verification record.

Both complete SoC exports passed the MCU adapter's generated-reset and equivalent
packed-coverage checks. The three Python adapter tests passed as well.

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase SoC | 152 | 16,612,992 | PASS |
| Native Click SoC | 126 | 13,403,880 | PASS |

Recorded semantic hashes:

- Four-phase: `60f883b27e965185b02210f94f85553747be8b78ba9ec221b60e415a392b9516`
- Click: `b09ddbe52d588c127bcf5cc835c93672dad15de39ad126f2a01dd8f4ac80d032`

An initial complete-chip validation rejected unregistered clocked helper scopes;
the helpers were subsequently inlined. The scalar mapping runs then exposed the
flat-reset assumption (Click) and exceeded 600 seconds (four-phase). The final
results above use the documented adapter, not a bypass of those failed runs.

## Retained-sleep verification record

On 2026-10-07, the full `test` task passed 39 tests in six suites. After the final
sampling-update change, all 17 affected tests passed again: eight SleepSpec,
seven SocSpec and two FabricSpec. The update now triggers a fresh conversion,
preventing repeated accepted interval changes from postponing sensing. Both
native variants also passed reset with the service clock gate closed and a
valid, locked image. No tests were skipped, canceled or pending.
The interruption test then passed a tighter rerun using immediate MMIO time
reads and a bounded expected delta, so host transfer time cannot hide lost ticks.
The eight-test sleep report is retained in `build/sleep-suite-report.xml`; the
latest focused report is under `verification/target/test-reports/`.

The sleep integration runs use accelerated reference
clocks and the documented small-memory long-duration fixtures. The nominal
4 kHz model period is checked separately. None of these results measures analog
oscillator accuracy, power, area, physical clock gating or metastability.

All nine Python tests passed: five export-adapter controls and four oscillator
model checks. The large paired endpoint probe initially exceeded the library's
60-second compile limit in concurrent and sequential runs. The adapter now gives
only generated-probe compilation the same bounded 600-second allowance as probe
simulation; it preserves every driver, assertion and coverage requirement.

The unaugmented paired fallback then exceeded 600 simulation seconds for
four-phase and reported inactive `commit_valid` coverage for Click. The added
clock-enabled campaign resolved that stimulus gap; no RTL or endpoint was removed
to make export checking pass. Both production-capacity digital exports passed
with `--soc --vector-coverage --sleep-clock`:

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase SoC with retained sleep | 152 | 25,190,352 | PASS |
| Native Click SoC with retained sleep | 126 | 20,330,352 | PASS |

Recorded semantic hashes:

- Four-phase: `6f719d2782e0cfae7429e4b6513cb48de5514e4d0cc2e9d76ed19347551ae3e9`
- Click: `154e7bba80464c45b1bc9c9ce1e20175b9237280a63d218fedd8d29f072de4e1`

The Click export contains no four-phase storage modules. The structural chip
wrappers are exercised by SleepSpec with the oscillator model; strict async
mapping checks cover their inner digital SoCs, not the analog macro boundary.

## Analog oscillator experiments

The separate [GF180 oscillator candidate](../analog/gf180-lf-osc/README.md) has a
transistor netlist, pinned upstream attribution and models, a parameter sweep,
PVT/startup/restart experiments, and independent measurement controls. Its
[characterization record](../analog/gf180-lf-osc/characterization.md) distinguishes
schematic simulation from physical qualification. The later slow-clock integration
uses that candidate's interface and nominal timing without modifying its circuit.

```text
python -m unittest discover -s analog/gf180-lf-osc -p "test_*.py" -v
python3 analog/gf180-lf-osc/characterize.py --fetch-models --suite nominal --output build/lf-nominal
python3 analog/gf180-lf-osc/characterize.py --suite sweep --jobs 3 --output build/lf-sweep
python3 analog/gf180-lf-osc/characterize.py --suite pvt --jobs 3 --output build/lf-pvt
python3 analog/gf180-lf-osc/characterize.py --suite controls --output build/lf-controls
```

SPICE runs use ngspice; on this workstation it is available inside WSL Ubuntu.
Use a fresh output directory for every campaign. The `controls` suite succeeds
only when the checker rejects a complete simulation with reset held asserted.
Each campaign first independently checks the PDK resistor's DC values, including
the documented ngspice compatibility transformation. Do not count model tests,
missing simulations, failed controls or raw PDK parser errors as analog success.

## Slow-reference and service-source shutdown verification record

On 2026-10-07, targeted runs passed 46 Scala tests across all seven suites:
17 SleepSpec/SocSpec/FabricSpec tests, 27 DeepSleepSpec/HostSchemaSpec/CoreSpec/
NativeRoutingSpec tests, and the two additional DeepSleepSpec probe-corner tests.
There were no ignored, canceled or pending tests. The final probe-corner rerun
uses 8 and 20 MHz, with 0 and 15 us startup; the complete-state and board tests
use 10 MHz and the maximum 100 us startup. All 14 Python export/model tests pass.
The first slow nominal model check exposed a hand-calculated expected-period
error; it was corrected to the independently calculated 1/7.7307 s. A Gray
monitor initially compared across POR and was corrected to reset its history;
Gray transitions during normal operation remain checked.

Both production-capacity slow-reference exports passed the unchanged MCU adapter
with `--soc --vector-coverage --sleep-clock`:

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase slow SoC | 152 | 25,247,808 | PASS |
| Native Click slow SoC | 126 | 20,377,980 | PASS |

Semantic hashes:

- Four-phase: `780d2d89b133315f5e1c617d635fbdc6046dec34ac9ff1f699e9765059721604`
- Click: `5ab5492d57e657e079ccbfc24aa629affdd870f8f0bb95b1b5af9dfcda24c96e`

Exports and checker evidence are under `build/four-phase-slow-soc`,
`build/click-slow-soc`, and their corresponding `build/*-slow-export.log` files.
The final oscillator-model bound/documentation update re-emits the same digital
netlists; it does not change the digital contracts validated above. The native
Click export still contains no four-phase storage/adapters. The generated chip
wrappers expose neither service nor LF clock inputs, and contain two explicitly
selected oscillator views. Strict mapping validates the inner digital SoCs;
complete-chip simulations exercise their wrappers/models separately.

No analog circuit or pinned transistor model changed in this integration, so the
prior LF SPICE campaign is unchanged rather than reported as rerun. A physical
fast oscillator, qualified POR/brownout source, LF layout/receiver validation,
actual Pi-adapter compatibility and whole-chip power measurements remain open.

## Compiled-firmware memory sizing record

On 2026-10-07, all four FirmwareSpec tests passed: two compiler-built RV32E C
fixtures on each native core, with full 2048-byte program and 256-byte working
RAM. No test was skipped, canceled or pending. All 18 Python tools tests passed,
including the four new firmware audit/linker controls. Production RTL did not
change in this sizing work; the prior digital export results remain applicable
and are not reported as rerun.

| Fixture | Loaded image | Static RAM | GCC stack bound | Four-phase SP / watermark | Click SP / watermark |
| --- | ---: | ---: | ---: | ---: | ---: |
| Event loop | 704 B | 16 B | 16 B | 16 / 16 B | 16 / 16 B |
| Runtime stress | 1204 B | 48 B | 88 B | 88 / 88 B | 88 / 88 B |

Each image includes startup, constants and initialized-data load copies. Both
SoCs loaded through I2C and checked CRC/start/lock, data/BSS initialization,
independent arithmetic expectations, a 16-byte guard and state across leased
WAIT. The terminal EBREAK is intentional for these finite fixtures. No simulator
preload or substituted handwritten image was used.

The chip models use a 10 MHz service source with the maximum 100 us startup and
an accelerated 500 Hz LF input to the slow-reference configuration. Nominal LF
frequency is covered by the separate oscillator-model checks; this campaign
does not measure analog timing or energy.

The original full-capacity run exceeded the harness's 90-second process limit;
it is not a pass. The final campaign uses supported repeated STARTs between
upload frames and a 300-second allowance per compiler/simulator process. It
preserves full capacity, wire transfers, watchdog behavior and all assertions.
The four-test suite completed in 12 minutes 49 seconds. Firmware compilation has
its separate 120-second limit; other clocked tests keep the 90-second default.

The build uses pinned GCC 13.2.0 and binutils 2.42, with `rv32e/ilp32e`, `-Os`,
no relaxation, M, C, libc or heap. ELF headers report ELF32 little-endian RISC-V,
RVE and soft-float ABI; disassembly is audited for the implemented instruction
set and x0-x15. The stack analysis rejects unknown/dynamic frames and recursion.
Actual links with 1 KiB program storage or 128-byte working RAM are rejected.

Binary SHA-256 values:

- Event loop: `eaad3454c08739d2c4ddb2929e3774b3beabf6bad1df59a79e88401ea73a95f6`.
- Runtime stress: `21bfa509b6d98eda799bd10ccc2cd6e3f05d76f7cc099d348357043b05cc33d1`.

Maps, ELF/binary/disassembly, source/compiler hashes and reports are under
`build/firmware/<application>/`; per-variant simulation summaries are alongside
them and full testbench evidence is under `build/soc-tests/`. These measurements
support the [memory budget](memory-architecture.md), not arbitrary future
firmware, physical SRAM integration or power/area claims. Remeasure when the
application, runtime, flags or compiler changes.

## Clock/reset schematic and integration record

On 2026-10-07, the new [clock/reset circuits](../analog/gf180-clock-reset/README.md)
passed 157 fast-source SPICE cases, 137 supply-monitor corner/ramp cases, 52
supply-event cases, and two deliberately broken-circuit controls rejected for
the expected measurement reasons. Each campaign independently checked nine PDK
resistor DC points. Netlist/model/report hashes and compact measurement ranges
are in [measurement-summary.json](../analog/gf180-clock-reset/measurement-summary.json).
These are schematic experiments, not extracted or statistical qualification.

Targeted digital runs passed 26 Scala tests: eight SleepSpec, seven SocSpec,
two FabricSpec and nine DeepSleepSpec cases. The latter includes new brownout
tests during sleep, partial upload and locked execution on both native cores.
All 28 Python tool tests pass, including production-length reset qualification
at 8 and 20 MHz and independent negative measurement controls. No skipped test,
timeout or simulator error is counted as success.

The first wrapper run exposed unknown reset state at simulation startup; the
supply model now emits an observable startup assertion and manual reset explicitly
forces the service clock on. Both reset-only and full-chip tests verify recovery.
The initial brownout fixture also advertised a 32-byte stack while allocating
16 bytes of RAM; the loader correctly rejected it. That fixture now allocates
32 bytes and both complete brownout scenarios pass. Other previously passing
cases were retained. Firmware capacities, instruction RTL and memory banks did
not change; the compiled FirmwareSpec corpus was not rerun in this clock/reset
turn. Its earlier results remain recorded above.

Both production-capacity exports were regenerated and passed
`--soc --vector-coverage --sleep-clock`: four-phase has 152 endpoints and
25,247,808 mapping checks; Click has 126 endpoints and 20,377,980 checks.
Their semantic hashes remain `780d2d89b133315f5e1c617d635fbdc6046dec34ac9ff1f699e9765059721604`
and `5ab5492d57e657e079ccbfc24aa629affdd870f8f0bb95b1b5af9dfcda24c96e`.
Evidence is under `build/four-phase-reset-soc` and `build/click-reset-soc`.
The new wrapper/reset logic is tested separately; the strict inner-SoC contract
does not characterize analog IP.

```text
python tools/sbt.py "verification/testOnly riscay.SleepSpec riscay.DeepSleepSpec riscay.SocSpec riscay.FabricSpec"
python -m unittest discover -s tools -p "test_*.py"
python3 analog/gf180-clock-reset/characterize.py --suite clock --output build/clock-check
python3 analog/gf180-clock-reset/characterize.py --suite monitor --output build/monitor-check
python3 analog/gf180-clock-reset/characterize.py --suite supply-events --output build/supply-check
python3 analog/gf180-clock-reset/characterize.py --suite controls --output build/clock-reset-controls
```

The LF schematic and its transistor models remain unchanged. The common model
preparation helper now uses atomic writes to prevent concurrent readers seeing
a truncated library; the transformation and prepared-model hash are unchanged.
Physical estimates are the next proposed stage and should use the selected
flip-flop memories. No synthesis area, whole-chip power or layout estimate is
claimed by this clock/reset work.

## Review fixes: recovery, host wake and storage

On 2026-10-07 the complete nine-suite regression passed **57 Scala/Icarus tests**
with zero failures, cancellations or skips. The Python controls passed **30 tests**.
A subsequent four-test FabricSpec run also passed after strengthening the coherent
snapshot test to modify a later word before the serializer reaches that boundary.
Evidence is in `build/review-regression.log`, `build/review-emit.log`,
`build/soc-tests/`, and the Scala XML reports.

The new cases cover production-ratio watchdog crashes while Groundlark is RUNNING
and SHUTDOWN, retained Pi power/lock/image and continued sensing, explicit locked
image restart, abandoned I2C writes/reads, held-low SDA, foreign-address data
traffic, queued kicks during CDC busy, lease writes without kicks, sparse register
holes, and coherent read snapshots across concurrent software updates. Scaling
checks exhaust all 4096 ADC codes and independently calculate elapsed fractions,
large tick deltas, wrap and updates during serial catch-up. The actual C event
helper is compiled and executed against mapped MMIO to detect blanket clears.

Both complete SoCs passed real I2C upload and execution of the revised firmware:

| Workload | Image | Static RAM | Compiler / observed SP / watermark stack |
| --- | ---: | ---: | ---: |
| Event loop | 728 B | 16 B | 20 / 20 / 20 B |
| Runtime stress | 1212 B | 48 B | 88 / 88 / 88 B |

Binary SHA-256 values are `8c3d0486f6a778a0c7f909c5782f1e24a72467cfdbd29de0bead147e8ec3b673`
and `87d90f3712f1abc92f9b5a154a658536728d5d11b52fdf5a73b8dde8db017595`, respectively.
Earlier firmware sizes above describe the preceding versions. The selected
2 KiB/256-byte flip-flop memories, 128-byte stack reserve and 16-byte guard remain.

The exported control token is 178 bits, down from 728; one 480-bit architectural
register bank sits outside the loop, and the 107-bit trace stays at execute output.
Groundlark allocates no software application-word bank. Elapsed time uses
fractional accumulators and bounded serial catch-up, ADC scaling is serial, and
the coherent host snapshot shares one word selector. These are structural RTL
changes, not mapped area, energy or physical timing measurements. Analog circuits
are unchanged, so their earlier SPICE campaigns were not rerun for these fixes.

Both regenerated production-capacity exports passed
`--soc --vector-coverage --sleep-clock`: four-phase has 162 endpoints and
29,472,336 mapping checks; Click has 136 endpoints and 24,547,456 checks.
Their semantic hashes are `63c4c88e171a14ff12bc0a3c389f6732126134b3d15d7fd9f08ba1c126cec91a`
and `5d2173a1d2946c0fd068eb99529b933dae0fcd1cb0068442bc3215f96a6681f9`.
Evidence is in `build/four-phase-review-soc`, `build/click-review-soc` and
`build/review-*-export.log`.

Initial export attempts exposed compiler-renamed diagnostic aliases and an
inactive operand-read path under the library's default mapping stimulus.
The register bank now uses its interface endpoints and registered primitive-port
probes. The MCU checker adds a full original bit-walk campaign with the registered
x1 storage output prefilled, allowing a valid source index and nonzero operand
to occur together. It forces no derived endpoint and retains every original
comparison, activity assertion and fallback. An independent negative control
proves that this extra stimulus activates the mux and still rejects incorrect
wiring. This changes mapping-test stimulus, not functional RTL or the library.

## Second review: reset crossings, writeback and deadline replacement

On 2026-10-07, **58 distinct Scala/Icarus tests across seven relevant suites**
passed: CoreSpec (17), NativeRoutingSpec (3), HostSchemaSpec (6), SocSpec (7),
FabricSpec (6), SleepSpec (8) and DeepSleepSpec (11). The two production-ratio
Groundlark deep-sleep cases then passed again with stronger checks that MODE
remains FAULT for the two synchronization edges before returning to READY.
The Python suite passed **40 tests**, including oscillator/reset models and the
existing estimator controls. No test in these runs failed, skipped or canceled.

New evidence includes minimum-visible memory response latency, register Q valid
before forwarding, required rejection of a bypassed writeback guard, deadline
replacement coincident with GPIO/expiry, rejected deadline writes, full gated
pulses, exact two-flop reset latency and successive host-visible crash counts.
The library's existing firtool annotation warnings remain. These digital checks
do not simulate metastability or establish physical timing closure.

Both regenerated production-capacity SoCs passed strict validation with
`--soc --vector-coverage --sleep-clock`:

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase SoC | 158 | 28,835,632 | PASS |
| Native Click SoC | 132 | 23,901,504 | PASS |

Semantic hashes are
`c9c049bec577857854c94d32619772f4168fe2b0f8c670b42fbb00858efbb768`
and `b4ef47a697d30b48d5b30548aef204ec3af79df9cf1c831e9d6ba277951a4c09`.
The four removed RF read endpoints are now part of the execute input/transform;
the single 480-bit register bank and 178-bit control token remain. Click retains
native phase routing throughout.

Evidence is in `build/review2-test-reports/`,
`build/review2-mode-regression.log`, `build/review2-{bd,click}-export.log`,
`build/review2-four-phase-soc/` and `build/review2-click-soc/`. Earlier full-firmware
and scaling results above were not rerun for this change. Analog circuits are
unchanged, so SPICE was not rerun. The `4b5d105` area/leakage/wake estimates are
historical baseline results; mapping and activity must be regenerated before
using them to compare the revised RTL.

## GF180 implementation preparation

On 2026-10-08, the relevant digital regression passed **54 Scala/Icarus tests**
across CoreSpec, SocSpec, FabricSpec, SramSpec, SleepSpec and DeepSleepSpec. Two
additional PhysicalTimingSpec tests passed dependent arithmetic with the fastest
memory response using the final 20/180 ns physical data budgets. The Python suite
passed **53 tests**, including mapping safety, deliberate event-monitor
violations, relative-margin rejection and stale-evidence rejection.

The final physical exports passed strict `--soc --vector-coverage --sleep-clock`
validation: BD has 158 endpoints and 6,050,768 mapping checks; Click has 132 and
4,873,440. Each contains exactly three SRAM instances. Enabled evaluation-only
Groundlark policy retains the complete supervisor in both implementation tops.

Both GF180 mappings passed exact protected-cell/connectivity audits, 23 adapter
specializations per variant and **5,810 independent functional vectors** in total.
All five pinned Liberty corners passed standalone cell/distribution bounds and
whole-transform 20/180 ns budgets. Conservative relative-envelope checks passed
11 BD and 31 Click inequalities. The seven C-element circuits passed **140
transistor-level PVT cases**, including retention and reset; their observed delay
range was 1.065–5.570 ns. Generated event monitors also compiled against both
final mapped hierarchies. Compilation checks binding, not event coverage.

Evidence is in `build/physical-final-regression.log` and
`build/physical-qualified-inputs/`: `policy-tests-rerun.log`, `python-tests.log`,
the strict export logs, `bd-dly/`, `click-dly/`, their `-pvt`, `-stages` and `-sta`
directories, the envelope receipts and `keeper-pvt/`. Earlier failed timing
iterations remain available; they are not the final results.

**This is prelayout preparation, not physical closure.** Five-corner full-chip
STA completed and resolved the constraints but still reports reset/recovery,
electrical and conservative async-path violations. No extracted SDF campaign,
padframe, analog layout or P&R was performed. Follow
[GF180 implementation preparation](gf180-implementation.md) for reproduction,
limitations and the remaining routed checks.
