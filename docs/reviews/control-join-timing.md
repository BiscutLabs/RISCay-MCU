# Conditional Control Join setup composition

Status: **conditional setup measurements verified; physical qualification remains open**.
This tools-only follow-up composes Control's two retained Join operands with
the actual update stage. It changes no RTL, clocks, guards or mapper policy.

## Boundary and graph custody

`tools/control_join_timing.py` resolves Control through the actual SoC hierarchy,
including deduplicated module names. It validates the exported operand/update
contracts, native primitive specializations, identity storage wiring and Join
rendezvous. An analysis wrapper retains the original Join and update instances
and every descendant cell. It rejects external consumers of their internal
connections. It does not substitute standalone replicas for loaded cells.

The wrapper exposes a zero-load ACK observation port; this adds no receiver or
cell. Other external outputs have the pilot's explicit 0.05 pF load. The original
Verilog/JSON graph and emitted wrapper each undergo independent Yosys round-trip
checks. Source files, maps, contracts, libraries, runtime configuration,
executables, scripts and logs are hashed.

The two source stores contain 276 state bits and 379 command bits; the update
stage captures 315 bits. Source D/Q/E or CLK pairing comes from actual storage.
Each source is measured as the last required Join arrival, with its peer already
offering the new phase. Both operand cases and both Click phases are mandatory.
The source cones reach 312 and 315 destination lanes respectively. Their union
must cover every dynamic lane; a missing STA query cannot become a static lane.

## BD: closure is not a launch clock

The source latch must already be transparent before the input data changes.
Pending admission and latch reopening are excluded: they need the E-rising-to-Q
arc and a separate transition context. The existing source contract must also
hold input data through its capture aperture.

For each physical source lane, the runner measures input-to-D propagation, the
actual loaded Liberty D-to-Q arc, and the earliest direct A-driven E-falling
closure. It requires both legal D setup and Q settlement before closure:

```
input arrival + input-to-D(max) + setup <= source E(min)
input arrival + input-to-D(max) + D-to-Q(max) <= source E(min)
```

The reported input-lag allowance is the tightest of these inequalities, relative
to that operand's request. D-to-Q reports retain rise/fall input slew, output
load, delay and output slew. Each measured output slew is applied at its own
physical Q and checked again through OpenSTA's graph vertex. Missing or
nonfinite values reject the case; no zero-slew fallback is permitted.

The downstream bound is deliberately conservative:

```
update E(min) - latest source E(max) - source Q-to-update D(max) - update setup
```

Once every Q has settled before its own closure, bounding all Q readiness by the
latest source closure overestimates data lateness. No E-falling-to-Q delay is
invented. These are analysis event references, not added hardware clocks.

Only physical ACK receiving pins are conditioned to the pre-feedback state.
The actual update ACK driver remains observable. Its earliest return is measured
and compared with the latest direct source closure, proving that the later
feedback transition cannot cause the first close in this context. Path evidence
must include the source request/A/long-hold chain and the actual Join/update
chain. This does not establish complete return-to-zero or next-token hold.

## Click: retain the real launch path

One analysis event is placed at the selected operand's actual fire driver.
Data paths retain its capture distribution, payload CLK-to-Q and full transform.
Control paths retain the separate phase CLK-to-Q, output guard, native Join
C-element, update request path and actual destination capture branches.
Neither phase Q nor payload Q is forced to a value.

The earliest destination capture is compared with the latest data arrival and
the same-corner Liberty setup requirement. Input-to-source setup is reported
separately. Minimum and maximum rising fire slew must agree between the request
and launch contexts, independently in both phases. Source payload hold,
phase self-hold and minimum pulse width remain separate obligations.

## Evidence and controls

The campaign uses the original A2b mapped RTL at
`6aa8033f5978dfde0a00432f82952f7999d93178`, from
`build/async-loader-width-finish-r2/candidate-mapped-{bd,click}-r1`.
It does not use the later opt-in Control electrical repair. Each variant is
measured at all five pinned Liberty corners and 0.02/2.0 ns input slew.

All 20 corner/slew cases resolve: **51,380 BD** and **89,580 Click** path rows.
No reported setup, input-lag or BD first-close/ACK ordering bound is negative.
The [evidence manifest](control-join-timing-evidence.json) records the sealed
receipts, controls, runtime and independent review.

| Minimum across five corners and two slews | BD | Click |
| --- | ---: | ---: |
| Conditional Join-to-update setup margin | 54.685 ns | 66.292 ns |
| Allowed Join-input data lag behind request | 19.809 ns | 21.243 ns |
| Returning update ACK after latest direct source close | 72.919 ns | Separate pulse/hold work |

These larger setup margins include the Join operand's output guard and actual
storage launch. They are not the earlier boundary-local allowance measured
only from the update stage input, and do not justify shortening either guard.
The logs retain 521–1,505 BD and 481–1,504 Click electrical-violation rows per
context, including repeated reports of the same cells in different contexts.

`tools/check_control_join_controls.py` checks analysis-period invariance and
annotates actual mapped arcs: a late input lane, a late source capture branch,
a late offer, a late rendezvous and shortened offer/request guards. Input and
capture faults must affect the exact physical members; controls require a new
failure from a positive baseline where failure is expected. Delayed offer and
rendezvous are ordering controls and must increase the setup allowance.

Graph controls cover deduplicated parents, identity permutations, extra internal
loads, operand wiring and a dynamic lane driven outside either data cone. Unit
controls cover arithmetic, missing paths, wrong pin/phase, reversed bounds and
changed launch slew, including minimum rising slew in both Click phases.
Both final control campaigns pass all 11 verdicts. Shared-cell mutations rerun
both operands; period invariance compares every parsed row, path, slew and
summary exactly. All **894 Python tests** pass, including the 23 new focused
checks. A fresh independent reviewer checked the implementation and
revised campaigns and found no remaining blocking issue within this scope.

Final receipts are in `build/control-join-corners-r1/{bd,click}` and
`build/control-join-controls-r3/{bd,click}`. Python evidence is retained in
`build/control-join-python-r2.log`; focused controls are also recorded in
`build/control-join-focused-r2.log`. Tools/docs-only changes do not require a new
RTL elaboration or sbt regression; the mapped input is unchanged and rehashed.

Earlier evidence is retained:

- `build/control-join-explore-r1`: unsupported direct latch queries and missing
  source slew. These failed attempts are not timing evidence.
- `build/control-join-pilot-r3/bd`: a conservative negative bound containing the
  later ACK reconvergence path as a second first-close candidate. The subsequent
  direct-close and explicit ACK-arrival checks separate these transitions.
- `build/control-join-controls-r1/bd`: a failed period control exposed numerical
  cancellation when subtracting a period/2 epoch from BD falling-data paths.
  Fixed event offsets remove this dependence; the tolerance was not relaxed.
- `build/control-join-controls-r2`: superseded controls reused the unmodified
  right-operand result for shared-cell faults and compared only summary minima
  for period invariance. Independent review caught both gaps; r3 reruns shared
  faults on both sides and requires complete result equality for period changes.
- Early pilot runs also retain rejected input-custody/runtime and invalid
  internal-endpoint diagnostics. The final campaign uses one configured WSL
  runtime for Yosys and STA, avoiding an expired second-distro UNC executable.

Reproduce using configured tool paths (`RISCAY_PHYSICAL_TOOLS`, as described in
[the stage survey](native-stage-timing.md#controls-and-portability)):

```powershell
python tools/control_join_timing.py `
  build/async-loader-width-finish-r2/candidate-mapped-bd-r1 `
  build/my-join-bd --variant bd --campaign
python tools/check_control_join_controls.py build/my-join-bd build/my-join-bd-controls
```

Repeat with the Click map and `--variant click`. Use fresh output directories;
the runner rejects overwritten evidence and changed inputs.

## Remaining qualification

Positive conditional setup margins do not authorize guard shortening. Electrical
violations remain in the logs. No wire RC, routed capture distribution or
statistical mismatch is included. Simultaneous C-element input switching is not
qualified by single-input Liberty arcs. BD pending/reopening/return histories,
Click pulse/self-hold, source reuse and full reset distribution remain open.
The producers before the Join input boundary still owe the reported input
aperture and retention contracts.

The follow-up [capture-retention check](control-retention-timing.md) measures
local zero-contamination hold and the BD fork with B already settled high.
Full source reuse and overlapping transition histories remain open.
Next, complete those transition cases and establish a justified
mismatch allowance before parameterizing or sizing Control's physical policy.
The negative execute/elapsed allowances in the earlier stage survey remain
unchanged. No area, power or timing-closure improvement is claimed here.
