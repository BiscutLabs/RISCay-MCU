# GF180 same-corner guard policy

The engineering policy is **20% two-sided variation plus 2 ns residual margin**.
For each loaded instance, corner and source-slew case:

```
0.8 * earliest_required_later_event
  - 1.2 * latest_required_earlier_event
  - Liberty_aperture >= 2 ns
```

This is a conservative project choice, **not measured GF180 mismatch data, a
foundry OCV recommendation or a statistical yield claim**. The public
[GF180 statistical model reference](https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_9.html)
provides transistor process and mismatch models. The
[layout matching guidance](https://github.com/google/gf180mcu-pdk/blob/main/docs/physical_verification/design_manual/drm_10_6.rst)
distinguishes local random variation from distance/layout-dependent systematic
variation. Neither supplies a qualified numerical delay derate for this MCU's
placed standard-cell logic and DLYD chains. A transistor Monte Carlo and layout
study remains part of item 17. A small [transistor variation screen](../analog/gf180-guard-variation/README.md)
now compares actual DLYD cells and a sensitized mixed-gate path using the pinned
PDK's process/mismatch models. It supports screening the engineering choice,
not statistical signoff or reducing the derate. The 192-run screen observes a
worst normalized ratio of 1.049791 in either direction, within the 1.5 envelope;
the 20/10 ps convergence control changes delays by at most 0.1741%. Keep 20% and
the 2 ns floor. Twenty percent here accelerates the request path
while independently slowing the data path; it is more conservative than a
single 1.2 multiplier on data.

The earlier elapsed pilot's 25 cells leave only 0.508 ns at this derate, so
that count does **not** meet the new 2 ns floor. Counts are selected from actual
same-corner data/capture/return measurements and then measured again. They are
reversible implementation parameters: local and digital acceptance permits
adoption before the full-chip item-17 qualification. Later extracted evidence
may require lengthening.

## Memory Source/Return owners

The BD memory-owner batch treats the nine historical 200 ns model guards
separately from standard stage templates. Six waits are replaced by existing
completion signals: Source grant and reservation ACK in each owner, and Return
cleanup in each owner. The three remaining chains have explicit owner/purpose
entries in `physical/gf180/ordering-guards.json`; no other custom guard gains an
override through that allowlist. The [review](reviews/bd-memory-guards.md)
records the causal changes and the retained failure that exposed a missing
delayed-decision return dependency.

Use `check_memory_owner_timing.py` on the repaired map for these custom owners.
Each role/eligibility publication, decision-to-use, capture-to-offer,
request-inhibition/history, completion-proof and keeper obligation is checked at
the same corner and actual load. A Source grant receives no credit from the
clocked receiver's synchronization latency. The decision check charges sender
CLK-to-Q without crediting its preceding clock cycle. Neither digital model
parameters nor another owner's path delays size these chains.

The two Source reservation `output_delay` policy rows also own
**eligibility-before-grant**, beyond LongHold's own publication constraint.
Their `retained_obligations` each impose an eight-cell minimum. A required-ID
inventory prevents dropping or moving these obligations silently; the mapper
and fast CI enforce it. The proposer carries the stricter archived/current
obligations even when its input map predates these annotations, and rejects a
proposal below the minimum. Updating the minimum requires a new composed Source
measurement and review. A standard-stage publication pass cannot discharge it.
This cheap gate preserves a measured recipe; it does not rerun STA in fast CI
or prove timing after unrelated changes to loading, logic, clocks or placement.

RamSource's short decision guard remains fallback-sized, but its decision setup
was measured in the same Source campaign: the minimum residual is **+10.720 ns**.
Measured adequacy at its current count is distinct from measured count selection.

The Return tail covers both rising capture and falling history. Deleting its
separate cleanup timer requires `released` to remain set through the tail;
merely wiring cleanup directly while retaining the old pending-owned release
would have a different pulse/keeper obligation. Selected native paths must stay
inside the declared slew envelope and Liberty table ranges. Local acceptance
still excludes routed RC, coupling, whole-chip reset distribution and statistical
variation. Keep the 0.05 mm² routed hold-repair reserve.
Item 17 explicitly retains the released and completion keeper pulse obligations;
the payload hold reserve cannot repair an inadequate keeper set pulse.

`check_fast_guard_soc.py --model-delay OWNER/ID=FEMTOSECONDS` supplies an explicit
digital stress delay for each custom owner. It rejects custom guards without one.
These stress values are not physical cell counts converted to nanoseconds; the
original SoC fixture and every behavioral assertion stay unchanged.

## Campaign and obligations

The candidate proposer now consumes measured paths instead of the historical
hard-coded eight-cell publication / 28-cell elapsed guesses. It does **not**
replace every mapper fallback with measured counts: on `a5a68cd`, 38 overrides
cover 330 of 3,603 DLYD cells; 3,273 cells still use the simulation-derived
fallback. The fallback is unqualified, not an absolute silicon requirement.

Run `size_ordering_guards.py <map> <output> --variant bd --propose
--measurements <file>` to estimate counts without editing a graph or policy.
The UTF-8 JSON uses schema `riscay-guard-sizing-measurements-v1`, the exact
`mapping_sha256` and `netlist_sha256`, and a `guards` list. Each guard names its
`instance`, `previous_stages` and nonempty `obligations`. Each obligation supplies
an `id`, `basis`, `kind` (`relative-ordering` or `absolute-minimum`), `edges`,
and `cases` covering every pinned corner × 0.02/2 ns source slew × declared edge.
Cases contain `corner`, `slew_ns`, `edge`, `earliest_ns`, loaded `cell_min_ns` /
`cell_max_ns`, and `electrical_pass`. Relative cases additionally contain
`latest_ns` and `aperture_ns`; absolute cases contain `required_ns`.

At the existing count N, removal of k cells estimates the later event as
`earliest_ns - k * cell_max_ns`; addition uses `earliest_ns + k * cell_min_ns`.
Apply the same 20% two-sided policy and 2 ns floor separately at each corner;
absolute requirements are not scaled as competing logic. Take the largest
required count across all declared cases. Only the later path may depend on
this chain; a shared dependency needs a different composition. Loaded arcs
must bound the cells being changed, not come from another owner's chain.
These are **estimates**: changed loading/slew requires fresh measurements.
Missing measurements are listed, never assigned eight, 28 or another guess.

The v1 proposer does **not** prove its later-path-only dependency assumption from
the graph. Do not use it for a chain on both sides of an ordering, including the
Return arm/history chain. The custom memory adapter remains required for that
already measured cohort; its allowlist is an adoption boundary, not a dependency
proof. Before expanding custom sizing, replace per-owner arithmetic with one
declaration-driven composed-path evaluator: bind launch/capture/ACK/keeper leaves
and phase cofactors, enumerate actual chain traversal on **both** compared paths,
and evaluate shared-chain changes with separate min/max bounds on each side.
Reject missing, overlapping or unresolved path coverage and report all affected
obligations for any changed chain. Require exact reproduction of the retained
Source/Return results and existing reusable negative controls before adoption.
This is open tooling work, not a feature of the current proposer.

`--candidate --measurements <file>` can replay shortening through the existing
BD stage templates: `setup` on request rise, or `publication` on both edges.
It rejects custom/absolute declarations those templates cannot remeasure,
independent vector lanes, focused request checks and lengthening (which needs
a fresh map). A template timing pass is explicitly electrically unqualified;
it does not adopt a count, close reset/full return, or change production policy.
Supplied baseline electrical results do not qualify the candidate graph.

`tools/size_ordering_guards.py` records every guard's purpose and disposition,
and uses the existing leaf-bound stage templates on the complete repaired chip.
No per-instance number is borrowed from a different owner. A shared mapper
recipe uses the largest count required by its members; all members are measured
with their actual parent loading and capture distribution for the selected
ordering obligations. The focused campaign does not measure unchanged data
transforms, except for the elapsed stage whose request guard changes.

The initial production cohort is the 92 BD Stage/LongHold controllers (184
ordering guards) and 75 Click Stage/Buffer ACK guards. It covers the largest
ordering-only family: BD output guards account for 2,484 DLYD cells in the
11b2/11b3 baseline. The inventory retains the remaining custom owners and their
specific obligations rather than treating a different controller as a standard
stage. Stage fusion changes the live count and must be reconciled explicitly.

The baseline's other **15 ordering-only BD guards** remain at their existing
counts in this campaign:

| Owner / guard | Count | Retained obligation |
| --- | ---: | --- |
| PublicationSource / request delay | 2 | Persistent publication identity and capture across coordinated application reset |
| Completion and Fabric / request guard | 2 | Selection and CPU/service source launch, beyond the standard stage controller |
| FrameStore / route request, offer request, return | 3 | Native bank route, selected bank copy and complete internal return before reuse |
| ProgramReturn and RamReturn / request guard, output delay | 4 | Reservation identity, permission capture, source hold and cleanup before rearm |
| Core / writeback request guard | 1 | Actual RF writeback-to-next-launch composition |
| Control / parent ACK guard | 1 | Existing measured source-release protection outside the local stage |
| I2cPublication / frame output and snapshot return | 2 | Wide independent frame/snapshot capture trees and publisher retention |

This is a complete disposition of the 199 baseline ordering guards, not 199
shortened or physically qualified guards. A10 removes the two RAM/program
prepare stages: four historical ordering guards disappear with those stages,
leaving 180 canonical guards and 15 retained custom ordering guards. The active
policy explicitly removes their records and retains their baseline inventory.

| Recipe | Baseline cells | Adopted cells | Active changed guards |
| --- | ---: | ---: | ---: |
| BD standard publication | 27 | 8 | 90 |
| BD elapsed request | 86 | 28 | 1 |
| Click standard ACK | 28 | 8 | 73 |

The table records the original adoption. The current BD elapsed arithmetic
uses **34 request cells**, remeasured in [area loop 2](reviews/bd-area-loops.md#loop-2--bounded-elapsed-arithmetic-accepted-after-a-timing-fix).
After factoring the increment, the old 28-cell recipe fails local setup; 34 gives
+3.790 ns minimum with the same 20% two-sided/2 ns setup policy, and a 257.435 ns
latest conditional capture. The historical 5.337 ns/28-cell provenance below and
in the policy file describes the older cone, not the current one. The current
active policy row is authoritative; the new ledger/review records its scope.
No other request count changes in that loop.

The other 89 active canonical BD request guards retain their original recipes.
That is the historical adoption inventory. The generic MCU removes supervisor
owners; regenerate the live count after the architecture work in
[the current work order](architecture-followups.md), then size all surviving BD
request guards in one campaign. Click optimization is frozen as a reference.
The policy is now `locally-measured` after complete local evidence sealing and
independent review. The default mapper consumes it. Future provisional policies
marked `candidate-not-yet-accepted` require `--candidate-guards`.
The accepted policy carries the measured provenance without depending on an
ignored build directory being present in every future checkout.
Changing an owner's logic, parent loading or capture fanout requires rerunning
its affected local checks, even if its primitive name and parameter tuple still
match the stored recipe.

- **BD request:** earliest closure versus latest transform, with same-corner
  setup aperture. Source launch alignment and return restrictions remain named
  composition obligations; no data-age credit is invented.
- **BD publication:** earliest offer at each actual receiver versus latest
  capture leaf, plus a conservative complete Liberty latch propagation bound.
  Both rising and falling branches are queried with measured loaded A-output
  slew. The falling publication query is a conditional A-to-offer versus
  A-to-capture branch bound with downstream ACK low; actual A falls while that
  ACK is high. It does not close pending admission or the complete return-to-zero
  composition. No transparent-latch credit is used. The long-hold fork's
  Boolean/reset circuitry is unchanged.
- **Click ACK:** earliest external ACK versus latest capture and hold aperture,
  for both phases. The ACK guard is downstream of the input-phase register;
  internal input/output comparators use phase Q directly, before this guard.
  The candidate retains that pulse-feedback graph and every first/terminal
  driver, so it does not shorten the existing pulse-width path. Request and
  output guards, phase self-hold and the capture tree remain unchanged.
  ACK additionally follows the latest falling capture leaf plus the worst
  Liberty pulse aperture and the 2 ns residual, preventing immediate source
  reuse from outrunning rearm. Q-to-rearm queries use measured phase-Q slew;
  the one CLK-to-Q launch arc is split only for that measurement and added once
  from the separate sequential ACK context.
- **All:** preserve reset masks, first/terminal drivers, actual source pins and
  all nonselected leaves. Keep electrical violation rows visible. Local results
  do not establish extracted min/max RC, complete reset-distribution timing or
  statistical qualification.

No fixed-time requirement is converted to relative sizing. SRAM CLK/pin minima,
watchdog/LF timing, reset-hold counters, external SPI timing and seed/reset
admission retain their existing independent obligations. Functional 1 ns-model
Boolean/feedback adapters are not removed as waits.

The campaign retains baseline and candidate graphs, actual path rows, exact
negative controls and a DLYD-by-purpose inventory. DLYD is a subset of guard
area, not an additional area to add to the ledger.

The final guard campaign uses `--focused`: BD publication guards retain actual
request-to-A and return-to-A slew measurements plus both publication/capture
branches. Click ACK guards retain both request/release phases, loaded fire and
phase-Q slews, every capture branch, sequential ACK, rearm and pulse apertures.
The elapsed request guard keeps the full data/setup/hold survey. Other data-cone
setup and upstream composition are explicitly **unmeasured by this guard-only
receipt**; the passive-allowance and SRAM fusion checks supply their separate
changed-data obligations. Ten-case representative BD and Click runs reproduce
the corresponding complete-survey guard margins exactly. Interrupted broad
surveys, source snapshots, tool crashes and timeout logs remain evidence rather
than being relabelled as passes.

`tools/check_guard_models.py` checks immediate source-payload reuse, downstream
stalls, both protocol histories and occupied/in-flight reset on an actual
exported standard stage. Deliberately too-short guards must fail at the exact
offer-before-capture or ACK-before-rearm assertion. The mapped-path controls
also require exact short-chain/late-capture failures, event-period invariance
and rejection of a wrong slew handoff or contradictory return cofactor.

`tools/check_fast_guard_soc.py` copies the final SoC activity fixture and changes
only selected ordering-guard model parameters. Its 8 ns publication/ACK and
35 ns elapsed-request settings are digital stress values, **not physical cell
counts converted to nanoseconds**. The unchanged whole-SoC oracle passes in
both variants. All selected instances are modified; this does not claim event
coverage of every instance or replace the per-instance physical campaign.

The seal-ordering campaign is retired. `tools/size_ordering_guards.py` now
checks every selected owner at all five corners and both source slews exactly
once, using the shared `timing_properties.validate_cases` acceptance rule. Missing,
nonfinite or negative setup/hold/publication/pulse/rearm evidence fails. It records
one run receipt. Successor snapshots and seal attestations are not accepted;
changed inputs require a new run. Local passes do not qualify unmeasured source
compositions, mismatch or routed timing.

The pinned OpenSTA build crashes or times out in its synchronous common-clock
pessimism-removal calculation for five BD cases across three owners. Those
failures remain in the original campaign. A separately frozen retry disables CRPR with
`sta::set_crpr_enabled false`, preserving the graph, cases, keeper cuts, roots,
queries and tool version. These guard equations use raw propagation and explicit
apertures; they do not use a synchronous common-clock slack bonus. Acceptance
requires all ten cases for each affected owner, exact equality of every raw
result from successful original cases, the single-line generated-script delta,
and fresh period and fault controls. This workaround does not waive or modify
the independent sampled hold checks. The retry receipts are inputs to the seal,
so an execution failure cannot disappear into a reported margin.
The complete retries cover 30 cases; all 25 successful original results match
their retries exactly. Runtime worker increases consume the original immutable
task queue, with every Future and case identity preserved. Their source, capacity
samples and chained before/after receipts are included in the campaign hashes;
they change concurrency only, never queries, results or timeouts.

The final mapped mutation receipts are retained in
`build/guard-sizing/{bd,click}-final-controls-r1/results.json`. Each passes five
exact controls: period invariance, short guard, delayed capture, wrong slew, and
BD return-cofactor / Click delayed-rearm faults. These controls were independently
reviewed against their source and generated artifact hashes. The whole-SoC and
focused digital receipts remain separate evidence from these physical queries.

## Accepted local evidence

The final seal covers **900 BD cases across 90 owners and 730 Click cases across
73 owners**. Independent review reproduced both seals and checked the raw case
results and artifact hashes. Minimum measured margins are:

| Changed obligation | Worst margin after the engineering derate and aperture |
| --- | ---: |
| BD publication | 4.159930 ns |
| BD elapsed setup | 5.337013 ns |
| Click ACK after rearm | 4.244298 ns |
| Click high pulse | 4.801602 ns |
| Click capture hold | 12.847456 ns |

The unchanged zero-source-credit BD elapsed local hold is positive at
0.584962 ns; it is separately reported and is not a 2 ns source-composition
claim. The guard-only data/setup and full return qualifications excluded above
remain excluded.

`build/guard-sizing/final-seal-r1.json` retains the complete evidence seal.
`policy-equivalence-r1.json` in the same directory proves that acceptance changed
only the policy's top-level status/provenance: all active and fused record bytes
and every effective mapped count equal the measured candidate copies. All five
mapping-policy controls pass again. Compact hashes, per-owner minima, recipe
rationale and retained obligations are committed in
`physical/gf180/ordering-guards.json`; future mapping does not require the build
directory. This adoption is reversible local evidence, not full physical closure.
