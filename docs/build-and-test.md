# Build and test

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
feedback, crossings and macro paths still require item 10 qualification; older
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
feedback forks, capture pulses and crossings require item 10 characterization.
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
transforms, feedback paths, capture pulses and crossings need item 10
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
