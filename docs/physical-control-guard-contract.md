# Physical ControlGate binding

Checklist substep 17a1 repairs physical intent binding. It changes neither the
BD/Click controllers nor their digital delay budgets, ABI or reset ownership.
It removes no additional clocked state. Complete controller feasibility and
routed qualification remain open under 17a2/17a3 and item 17.
The local mapping repair, measurement audit and fresh review are complete.

## Intent is explicit

`physical/gf180/controlgate-roles.json` declares a reviewed role for each module
family and primitive ID. FIRRTL's numeric module-specialization suffix is ignored;
instance names and bus width do not determine intent. Unknown owner/ID pairs
require source and timing-contract review before extending the catalogue.

`tools/gf180_control_roles.py` also resolves every `bundled-data-path-v1`
`delay_owner` child-ID chain and exact `delay_cell`. Canonical Click and long-hold
contracts identify their own `data_delay`. Each data allowance needs at least
one such reference and a matching positive, ordered budget; a control guard
must have none. Delegated references use contract child IDs, not guessed RTL
names. Duplicate identifiers/paths, missing references, conflicting roles,
unsupported data operations and non-behavioral ControlGate views are rejected.
The latter check prevents a constraint-marker label from bypassing active mapping.

The parameterized physical wrapper selects only by exact model/parameter tuple.
Therefore a tuple used for both roles is rejected before output creation; the
mapper must never select whichever role happened to appear first. A future
collision requires an explicitly verified instance-specific binding design.
Each mapping records its catalogue hash and per-instance role/reference evidence.

The current complete SoC audit covers 1,440 instances and 60 exact parameter
tuples, with no role collisions. BD has 117 data allowances and 503 controls;
Click has 131 and 689. The old width rule misclassified 54 scalar allowances
and 12 vector controls. This inventory describes the qualified digital export
configuration, not every possible future parameter or profile combination.

## Physical graphs and limits

A whole-transform allowance retains a reset gate and one buffer per data lane,
plus its reset distribution tree. This also applies to scalar data. Its nominal
delay represents the complete upstream transform and adapter, not a physical
delay line to insert after the transform. Adapter-only measurements cannot
establish the complete path's minimum, maximum or capture aperture.

A matched control guard receives a separate preserved chain on every lane.
The existing short-control graph uses nine buffers; long guards use DLYD cells
with counts derived from the pinned all-corner cell floor and existing margin.
Reset polarity and Buffer/Invert/Or operations are preserved independently on
each lane. Actual graph measurements, not cell counts, establish delay bounds.

Restoring the missing minimum guards can produce maximum delays substantially
longer than the fixed digital model. That is a physical design constraint to
resolve, not permission to stretch the original admission deadline, add a
logical credit, weaken a reset test or report controller timing closure.
Revisit complete relative envelopes, reset settlement and related-clock hold/setup
before using these candidates in a migrated controller. All new graphs remain
unqualified for routed use.

## Verification and outstanding work

Evidence is retained in `build/async-physical-guard-migration/`. Unit controls
exercise scalar/vector roles, delegated and canonical references, bad budgets,
duplicate/unknown IDs, passive-view bypass and tuple collisions. The real mapper
inventory/grouping/wrapper writer is exercised with only unrelated asset and
chip-shell fixtures stubbed. Independent Boolean graph evaluation covers all
four-bit inputs, operations and mixed reset values. Original physical tests and
their oracles remain in place.

The independent role audit is pinned to source and the previous strict exports.
The final campaign records 1,256,960 finite measurements: 60 new tuples with
7,810 output lanes plus ten original vector-control graphs, all five pinned
corners, input slews 0.02/2 ns and loads 0.003/0.05 pF. Every lane has both
transitions, min/max, data and sensitized reset paths. All ten old graphs fail
their intended minimums. Missing-lane, missing-row, duplicate-row and nonfinite
controls reject. A separate auditor reconstructs every expected row and bound.
The final-source graph/netlist comparison preserves the original campaign's
provenance after the passive-view review fix.

All new adapters meet their declared local checks. Long guards have no finite
maximum in that adapter-level requirement, so this result does **not** show
that they fit the controllers' fixed digital delays. Measured data-pin envelopes
include:

| Vector guard model | Measured minimum | Measured maximum |
| --- | ---: | ---: |
| 11 ns | 18.329842 ns | 76.870407 ns |
| 32 ns | 50.971302 ns | 211.362762 ns |
| 110 ns | 172.470108 ns | 711.972290 ns |
| 241.200001 ns | 375.572998 ns | 1548.816406 ns |

Sensitized reset propagation reaches 712.102356 ns and 1548.834106 ns for the
last two graphs. These exceed the present 250 ns digital reset-settlement
assumption. Resolve that mismatch in the physical controller design; do not
extend failing reset stimuli or weaken original admission timing tests.
These measurements are pre-layout and do not
include upstream logic, extracted wiring, pulse/hazard or full-controller reset
qualification.

The final complete Python run passes all 375 tests, and both physical-policy
tests pass. Preserve the slow superseded r1 campaign with its interrupted
partial log, the r2 harness failure on exact one-bit reset-port spelling and
the corrected r3 results. The batched r3 path queries match all 32 keyed original
probe values and still reject an actually disconnected final lane.

17a2 must repair current physical export/policy and source inventory integration,
then stale clock/reset hierarchy bindings. 17a3 must inventory and measure every
custom complete transform, feedback, trigger, return and aperture obligation.
Historical canonical-stage totals and missing `data_max_ns` enforcement cannot
qualify the migrated SoCs. Original export/mapping failures remain evidence.
