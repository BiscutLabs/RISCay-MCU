# Conditional Control capture retention

Status: **conditional measurements; physical qualification remains open**.
This follow-up to [Join setup composition](control-join-timing.md) changes only
analysis tools and documentation. It adds no hardware clocks or storage and
changes no RTL, guards, simulation budgets or mapping policy.

## What is measured

The runner consumes the sealed, loaded Join/update slice from the previous
campaign. It verifies every original input and artifact hash, the configured
runtime, and the positive setup results before extending the evidence. It
repeats each original request context and requires identical path results.
Both operands and both Click phases are included.

For each actual update capture lane, the new bound is:

```
earliest update ACK − latest update capture − Liberty hold requirement
```

Both arrivals use the same physical update `long_hold` or `fire` event. Click
ACK includes the actual phase-register clock distribution, CLK-to-Q, output
buffers and acknowledgment guard. The calculation grants **zero delay** to
source Q reuse, ACK distribution and the transform: it allows the data to
change instantaneously at the actual update ACK driver. A positive result is
a sufficient local hold bound if the source stayed stable until that ACK.
It is not a measurement of the earliest next-token capture.

The event and ACK slew bounds must match the corresponding original request
context, at each corner, operand and phase. The ACK observation port has zero
load; all physical cells and connections retain the prior slice's loading.
Literal destination lanes keep their capture obligations. Analysis-clock
periods supply no timing budget.

## BD's conditional long-hold fork

When the source's B state has already settled high and A is held high, ACK
must reach the actual long-hold OR's ACK input before A falls at its other input:

```
earliest A fall at OR.a − latest ACK rise at OR.b > 0
```

The tool identifies these pins from their actual net identities. It evaluates
the mapped A Boolean network for both request levels and both ACK values,
with B=1, keeper=1 and reset=0. This proves that the request minterm is inactive
and that the changing logic forms exactly one ACK-to-A path. It rejects unknown
cells, changed topology, omitted changing arcs and request-dependent behavior.

Whole-path STA automatically cuts the ACK inverter in the later return loop.
That cut's missing/zero delay is not used. Instead, `control_fork_arc.tcl`
evaluates each actual loaded Liberty arc directly and passes its measured
output slew to the next actual input. Both minimum and maximum calculations
retain the raw delay reports, loads, transition polarities and wire arcs.
The parser verifies report/row agreement, complete graph coverage, adjacent
slews and independent sums. Only prelayout zero-RC wires or explicitly declared
pure-transport fault annotations may preserve slew this way; nonzero unmodeled
wire delay is rejected. This method is a composed first-transition envelope,
not a complete-path STA result.

This fork result is conditional on **B already high before ACK**. It does not
prove that ordering, overlapping B/ACK behavior, a global earliest A fall,
return-to-zero retention or latch reopening. Those transition cases remain
open. Click's source pulse and phase self-hold likewise remain open; the local
hold bound does not prove absence of an extra capture before ACK.

## Campaign and controls

The input remains the original A2b mapped RTL at
`6aa8033f5978dfde0a00432f82952f7999d93178`, without the opt-in Control repair.
The campaign covers five pinned Liberty corners and 0.02/2.0 ns input slew in
both variants. Results and controls are bound by the
[evidence manifest](control-retention-timing-evidence.json).

All **20 corner/slew cases resolve**, with no negative reported bounds:

| Minimum across five corners and two slews | BD | Click |
| --- | ---: | ---: |
| Zero-contamination hold margin | 1.175 ns | 52.864 ns |
| ACK after latest capture | 1.369 ns | 53.102 ns |
| Settled-B ACK/A fork margin | 2.464 ns | Not applicable |

The BD margin is small and **has no mismatch or routed-wire allowance**. It is
not a basis for reducing delay. The campaign records 38,380 BD and 51,480 Click
path rows, plus 520 loaded BD cell arcs and 600 wire arcs. All 922 Python tests
pass, including 28 new focused tests. Both final control campaigns pass
(five BD and three Click controls). Fresh independent review found no remaining
blocking finding within the documented conditional scope.

Final receipts are `build/control-retention-corners-r1/{bd,click}` and
`build/control-retention-controls-r1/{bd,click}`. The full Python result is
`build/control-retention-python-r1.log`. Existing electrical violations remain
in the per-context reports; these are measurements, not electrical closure.

Actual physical fault controls cover:

- Changing the analysis period: every parsed row, path, slew and summary must
  remain identical.
- Delaying one actual update capture branch: exactly its 16 storage lanes
  move, ACK stays unchanged, and a positive hold bound becomes negative.
- Accelerating the actual ACK cells, including Click's phase launch: both ACK
  bounds move earlier, captures stay unchanged, and the hold bound fails.
- BD only, delaying the exact ACK-to-OR.b interconnect: only that branch moves
  and the positive fork inequality fails.
- BD only, zeroing the A path's actual cell arcs: equality must fail the strict
  fork ordering test.

Unit controls also reject missing paths, wrong phase/driver/CLK-to-Q evidence,
nonfinite or reversed slew bounds, wrong cofactor functions, broken arc/slew
chains, report mismatches and undeclared wire timing. No functional test
expectation is weakened.

Reproduce with `RISCAY_PHYSICAL_TOOLS` configured as described in
[the stage survey](native-stage-timing.md#controls-and-portability):

```powershell
python tools/control_retention_timing.py `
  build/control-join-corners-r1/bd build/my-retention-bd --campaign
python tools/check_control_retention_controls.py `
  build/my-retention-bd build/my-retention-bd-controls
```

Repeat for Click. The original sealed Join campaign and its unchanged inputs
are required. Output directories must be fresh. Only tools/docs changed;
the existing RTL is rehashed, not re-elaborated or resimulated.

Earlier failed probes remain under `build/control-retention-pilot-r1` and `r2`:
the first Click falling-ACK query incorrectly selected a falling analysis-clock
edge, and BD whole-path queries exposed unsupported endpoints and an automatic
return-loop cut. The revised query retains a rising launch and the actual
falling phase Q; BD uses the explicit cofactored arc composition above.
`build/control-retention-controls-pilot-r1/click` retains an incomplete ACK
speedup that left the phase output buffers intact and did not cause the
expected failure. The final control includes that real launch path.

## Remaining work

These results remain conditional on the previous setup envelope, stable source
data through ACK, legal single captures and no reset. Complete BD pending,
B/ACK and return histories, Click pulse/phase feedback, simultaneous C-element
switching, mismatch, electrical limits, reset distribution and routed min/max
RC remain open. Electrical violations in the original loaded maps persist.
No guard shortening, area/power improvement or physical closure follows.
