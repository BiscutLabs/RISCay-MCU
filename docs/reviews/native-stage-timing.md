# Reusable local native-stage timing measurements

Status: **conditional local measurements; physical timing remains open**.
This follow-up to [the Control pilot](control-relative-timing.md) changes tools
and documentation. RTL, native handshakes, guard lengths, simulation timing
policies and the default mapping/P&R flow remain unchanged.

## What is reusable

`tools/native_stage_timing.py` selects exact logical stage instances from the
exported contract, resolves their actual mapped hierarchy after module
deduplication, and applies the reviewed BD/Click capture templates. The mapped
inventory contains 35 BD and 33 Click canonical stage instances. It does not
claim to cover every native owner. FIFOs, Joins and custom controllers require
their own templates and complete transition analysis.

Templates are shared; measured numbers are not. Every selected stage retains
its own transform, payload width, request guard, capture tree, electrical load,
corner and input slew. CPU execute uses a 21 ns request model; the Control
pilot's 11 ns model is not substituted for it.

The contract's endpoint paths, widths, primitive parameter tuples and timing
references must agree with the mapper record. The actual controller graph and
adapter cells are checked, and Yosys rereads the queried Verilog to prove that
its full connectivity agrees with the JSON used to select pins. Input files,
executables, runtime configuration, generated queries and raw logs are hashed.
Changed inputs reject the evidence.

Logical lane numbers come from actual payload D/Q connectivity, not lexical
leaf names. Literal zero/one transform lanes have no dynamic data-path query;
their capture and ACK queries remain mandatory. Unknown literals reject.
Duplicated dynamic sources are not constants. The report records static lanes
and maps every logical bit to its physical D, E/CLK and Q pins.

The reviewed Control analysis contexts are unchanged: empty BD admission,
both Click request phases, Click pending release, common-event hold and native
Click phase CLK-to-Q. This is not a state-graph enumerator. BD pending/return
ordering and Click pulse/self-hold remain unqualified.

## Scope and interpretation

The survey selects CPU execute, the elapsed loop step, RAM preparation, RAM
lane-zero issue and capture, and I²C protocol update. It uses the original A2b
mapped netlists in `build/async-loader-width-finish-r2/candidate-mapped-*-r1`,
without the opt-in Control electrical repair. Each corner compares data and
request paths from the same Liberty corner. Output load is the pilot's chosen
0.05 pF; wire RC and statistical mismatch are absent. Electrical violations
remain in every context's logs.

**I²C protocol update is not I²C publication.** The publication owner is a custom
`I2cPublication` controller and is explicitly rejected by the canonical-stage
selector. Its frame/scratch copy and return ordering still need a separate
template and physical envelope.

The setup quantity is **permitted input-data lag behind input request**, not
complete source-to-capture setup slack. A negative value requires data to be
stable that much earlier than request. Until upstream storage/Join launch is
measured, neither sign qualifies the complete stage. Negative quantities are
explicitly labelled `NEGATIVE_LOCAL_MARGIN`; no result reports physical pass.

Nominal-corner measurements at 0.2 ns input slew illustrate why uniform guard
shortening is unsafe:

| Permitted input-data lag | BD | Click |
| --- | ---: | ---: |
| CPU execute | −0.214 ns | −2.423 ns |
| Elapsed step | −32.583 ns | −22.309 ns |
| RAM prepare | 36.897 ns | 39.223 ns |
| RAM lane-zero issue | 36.697 ns | 38.965 ns |
| RAM lane-zero capture | 36.383 ns | 38.673 ns |
| I²C protocol update | 27.020 ns | 29.327 ns |

All **120 selected stage/corner/slew cases** resolve: 72,680 BD path rows and
128,060 Click path rows. The minimum permitted input-data lag across all five
corners and both slews is:

| Stage | BD | Click |
| --- | ---: | ---: |
| CPU execute | −2.518 ns | −5.079 ns |
| Elapsed step | −62.307 ns | −43.700 ns |
| RAM prepare | 19.726 ns | 21.127 ns |
| RAM lane-zero issue | 19.682 ns | 21.047 ns |
| RAM lane-zero capture | 19.425 ns | 20.802 ns |
| I²C protocol update | 13.883 ns | 15.269 ns |

Execute has negative allowance in 6/10 BD and 8/10 Click cases; elapsed has
negative allowance in every case. These require upstream launch composition,
not a relabelled setup pass. The [evidence manifest](native-stage-timing-evidence.json)
records these results and hashes the sealed receipts containing raw queries,
logs and input provenance. No new area or power saving is claimed.

## Controls and portability

`tools/check_native_stage_controls.py` reuses the actual mapped-arc SDF faults
from the Control pilot. CPU execute exercises period invariance, request-guard
shortening, early ACK and a delayed capture branch. Existing negative CPU
lanes are reported separately; only newly failing positive-baseline lanes count
as detected faults. Capture faults must affect exactly the selected branch;
off-branch changes in either direction reject. Dynamic hold and static ACK
ordering are checked separately.

SRAM preparation exercises period invariance, early ACK and a deliberately
selected branch containing constants. Its late-capture fault fails exactly
16 BD lanes / 32 Click lane-phase pairs, all static. CPU's capture fault covers
dynamic hold. Removing SRAM's request guard alone did not make its very short
data path fail. That attempted negative control is retained under
`build/native-stage-controls-r1` with `STAGE_CONTROL_NO_NEW_FAILURE`; it is not
reported as a successful negative control. The final SRAM campaign explicitly
selects the three effective controls, without relaxing the failure oracle.

`RISCAY_PHYSICAL_TOOLS` selects a schema-1 JSON runtime configuration. Defaults
are `physical/gf180/tools.windows.json` and `tools.linux.json`. Entries specify
the executable, optional WSL distribution, timeout executable and timeout
arguments. Native Linux commands invoke the tool directly; Windows WSL commands
use an argument vector without shell interpolation. Override the example paths
for another workstation. The configuration and executable hashes are evidence
inputs, and fault controls require the same runtime as their baseline.

The new stage runner and existing Control relative pilot/controls use this
runtime. A native Linux Python invocation of the RAM issue pilot reproduces the
Windows-orchestrated numerical result exactly. This does not make the remaining
legacy P&R, synthesis and SPICE scripts portable; their conversion remains open.

The final complete Python suite passes **871 tests**. The existing Control
pilot and all its actual-arc/period controls also pass again after the helper
changes. Fresh independent review found and verified fixes for runtime custody,
timing-reference binding and constant-branch fault coverage. No RTL or digital
timing policy changed, so Scala/Icarus suites are not claimed as newly run.

Final local evidence:

- `build/native-stage-pilot-r3/{bd,click}`: nominal survey and round-trip proofs.
- `build/native-stage-corners-r1/{bd,click}`: five-corner, two-slew survey.
- `build/native-stage-controls-r2/{bd,click}-{cpu,sram}`: effective mapped faults.
- `build/native-stage-control-regression-r1`: original Control pilot/controls.
- `build/native-stage-linux-r2/bd`: direct Linux invocation.
- `build/native-stage-python-r2.log` and `build/native-stage-review`: tests/review.

Example:

```powershell
python tools/native_stage_timing.py `
  build/async-loader-width-finish-r2/candidate-mapped-bd-r1 `
  build/my-native-stage-survey --variant bd --campaign `
  --stage FourPhaseSoc.ca_child_core.ca_child_execute
```

Output directories must be new. Omit `--campaign` for the nominal 0.2 ns case;
the campaign uses all five pinned cell corners and 0.02/2 ns input slews.

## Remaining acceptance gates

1. Compose actual upstream storage/Join launch and source reuse with these
   boundary allowances. Preserve the negative execute/elapsed evidence.
2. Enumerate complete controller transitions, including BD pending admission
   and both returns, and Click pulse/phase self-hold. Add FIFO/Join and custom
   I²C publication templates without reusing load-dependent numeric results.
3. Build the smaller uncut controller SPICE experiment with validated STA load
   envelopes, native `.meas` crossings and timestep convergence. Keep the full
   payload harness as a comparison until load reduction is justified.
4. Establish mismatch/variation margins, then parameterize and size physical
   timing policies from the measured envelope. No guard shortening is accepted
   from this local survey alone.
5. Complete electrical/reset repair, remaining tool-runtime portability and
   routed min/max-RC checks. The default physical flow remains unqualified.
