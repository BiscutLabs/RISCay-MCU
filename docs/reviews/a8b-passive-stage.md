# A8b: one passive whole-transform allowance

This isolated experiment replaces the 101-bit `data_delay` of RAM's standard
`prepare` stage in each variant. It does not change the production RTL, library
release, generic mapper, request guards, storage cells or periodic clocks.
The matched baseline is the 11b1 repaired pre-placement graph. No saving from
this experiment is booked against the current production design.

## Contract being tested

The existing `ChiselAsyncControlGate_v1` buffer models a whole transform and
forces its output to zero during reset. The experimental, separately named
`RiscayPassiveAllowanceExperiment_v1` is an inertial wire in simulation and a
plain alias in the physical graph. Its model delay still represents the entire
upstream transform, rather than an additional physical delay line. It has no
reset mask, storage, clock or control function. This is an intentional semantic
change, not a different physical binding for the existing versioned primitive.

The native payload storage retains its original reset and capture control.
Consequently, after reset settles, the stored output is zero and the stage is
empty even when the input and storage D contain unknown bits. While empty,
BD's transparent payload may subsequently track unknown or changing input;
only the native offer authorizes consumers to use it. Click's payload captures
only on its existing local pulse. The experiment adds no invalid-data mask.
Production adoption must audit every invalid-data fanout and retain explicit
masks wherever data reaches architectural or isolation logic without valid
qualification.

This pilot accepts only the existing **unseeded** standard stage. Seeded owners
and phase-decoupled Click stages are rejected by the standard-stage descriptor;
their initial-token reset and startup semantics require separate work. No
MOUSETRAP controller or four-phase adapter is substituted for Click.

The physical obligations are measured at the actual retained source Q, payload
D and E/CLK pins, and actual ACK receivers. At each corner and input slew:

- Maximum data propagation plus Liberty setup must precede the earliest capture.
  The result is the allowed input-data lag relative to the conditional request
  event; upstream Join launch remains an additional composition obligation.
- Minimum capture-to-ACK propagation must follow the latest capture and Liberty
  hold requirement, assuming immediate source reuse and **zero** data-path
  contamination credit. The fastest data path is also measured and retained.
- Literal lanes retain their capture and ACK ordering checks. Every capture
  branch remains present; no lane is removed from timing coverage.

Only paths with a failed hold bound would justify added hold buffers. A local
positive bound does not close reset distribution, pending admission/BD returns,
Click pulse self-hold, electrical limits, mismatch or extracted wire RC.

## Reproducible scope and controls

`tools/experiment_passive_stage.py` validates the original repair receipt and
mapper contract, resolves the actual deduplicated standard stage, and binds the
digital stage and each compiled library model to `mapping.json` source hashes.
It changes one model instance in an isolated generated source copy. The
independent transform oracle checks the original request concatenated with a
zero 32-bit result; request address, data, mask, write and ignored credit all
exercise the original stage interface.

Each protocol runs its original and passive digital views through 27 captures,
26 completed testbench offers, three reset epochs, unknown invalid payload,
stalled output, immediate legal source reuse and reset during an occupied or
incoming transaction. Reset starts with a real edge, including at time zero.
Removing payload reset and making data late must fail at the exact intended
testbench filename, line and diagnostic. Compiler errors, unrelated assertions
or timeouts do not count as detected faults.

For the physical experiment, only the selected adapter hierarchy is cloned.
A whole-chip pin/top-port partition proof removes that adapter's leaves and
aliases exactly `q[i] = a[i]`; it rejects every other cell removal, resize or
rewire. The live capture trees, native control and remaining parent repair cells
stay in place. A Yosys Verilog round trip separately verifies the graph that
OpenSTA actually reads. All five pinned corners and both 0.02/2 ns input slews
run on each baseline and candidate: 40 total stage/corner/slew cases.

The existing leaf-based timing templates are reused. On each passive graph,
changing the analysis period must leave every result identical; adding 1000 ns
to one actual source-Q-to-D interconnect must fail setup only on that lane;
delaying one real capture-buffer branch must fail hold/ACK on exactly its
attached leaves, including literal capture lanes. Nine Python controls reject
wrong width, collateral resize/rewire/removal, swapped alias lanes, duplicate
model replacement, stale generated source and incorrect fatal sites.

## Measured result

The forty baseline/candidate cases are positive. The worst local bounds over
all five corners and both slews are:

| Bound, ns | BD baseline | BD passive | Click baseline | Click passive |
| --- | ---: | ---: | ---: | ---: |
| Allowed input-data lag | 19.725713 | 20.400899 | 21.127041 | 21.802022 |
| Hold, with zero contamination credit | 1.285952 | 1.285952 | 53.009023 | 53.009023 |
| ACK after latest capture | 1.479952 | 1.479952 | 53.247023 | 53.247023 |

The candidate's actual data-path min and max are both **zero** at zero wire RC:
RAM prepare copies the request and appends a literal zero result, so removing
the adapter leaves direct source-Q-to-D connections. Setup allowance improves;
the conservative hold and ACK bounds remain unchanged. No hold buffers are
flagged or added in this local experiment. BD's approximately 1.29 ns hold
margin still needs mismatch and extracted-wire analysis before adoption.

Each graph removes **212 cells / 0.0033981696 mm²** of LEF footprint: 101 AND2,
102 `buf_1`, seven `buf_4`, one `buf_8` and one inverter. Of this, the original
allowance recipe contributes 211 cells / 0.0033849984 mm²; one retained repair
reset buffer contributes 0.0000131712 mm². Guard/DLYD area, payload storage and
clock sinks are unchanged. This is an exact one-instance graph subtraction,
with all other repair cells retained; synthesis and global repair were not
rerun to claim an optimized whole-chip result. It is not multiplied by every
allowance lane to predict a production saving.

Generated netlists, commands, logs, complete lane-level min/max results and
SHA-256 custody remain under `build/a8b-passive-stage/{bd,click}-final-r1/`.
The final receipt includes the eight digital runs and six STA controls across
both variants, with nine Python source/graph/fatal-site controls run separately.
Development smoke failures are retained; only final reports with unchanged
tool/input hashes are accepted. The first Click harness lacked an initial reset
edge and correctly failed reset; it was fixed by generating a real edge, not by
changing the reset oracle. Source-edited smoke runs fail custody and are not
counted as final evidence.

Fresh independent review checked the implementation and contract, verified the
235 BD and 419 Click bound input/artifact hashes, recomputed all forty margin
cases and all six STA-control verdicts, and reran the nine Python controls.
It requested mapper-source binding and exact fatal-file matching; both fixes
landed before the frozen final campaigns. The review found no remaining issue
within this isolated experiment's scope. Production/library adoption and the
physical qualifications listed above remain open.

## Run

Use the configured physical runtime matching the retained mapping receipt. On
the development machine this was `build/control-join-tools.json`; the runner
uses the portable `RISCAY_PHYSICAL_TOOLS` interface, not hard-coded WSL commands.

```powershell
$env:RISCAY_PHYSICAL_TOOLS='P:\Personal\RISCay-MCU\build\control-join-tools.json'
python -m unittest discover -s tools -p test_experiment_passive_stage.py
python tools/experiment_passive_stage.py build/control-frame-borrow/completion-final-map-bd build/control-frame-borrow/completion-final-physical/bd build/a8b-passive-stage/bd-final-r1 --variant bd --campaign
python tools/experiment_passive_stage.py build/control-frame-borrow/completion-map-click build/control-frame-borrow/completion-physical/click build/a8b-passive-stage/click-final-r1 --variant click --campaign
```

The experiment needs no sbt launch and changes no library files. A supported
library API would need a separately reviewed passive-allowance contract/schema,
explicit endpoint and reset policy, model tests and generic export validators.
The existing timing markers are retained here; this pilot does not claim that
an edited generated export is a new supported library export.
