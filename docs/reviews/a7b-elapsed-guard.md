# A7b: same-corner elapsed request-chain experiment

Status: **measured isolated candidate; production shortening is disabled**.
The production RTL, timing policy, mapper recipe and all physical defaults are
unchanged. This is the first bounded A7b experiment, not completion of A7b or
physical qualification under migration item 17.

## Change and result

The current inventory identifies 199 BD ordering-only adapters. The elapsed
step's request adapter is the largest ordering guard supported by the existing
standard-stage template: 86 DLYD cells, 0.0064451072 mm² including its reset
inverter and AND gate. Larger I²C publication/return adapters have custom
ordering/distribution contracts and are not silently treated as standard stages.

`tools/experiment_elapsed_guard.py` makes one isolated candidate from the
**actual repaired 11b1 chip**. It removes 61 interior DLYD cells, retaining 25,
the original reset mask and the exact terminal driver. Every other logic cell,
capture branch, parent load, feedback connection, ACK and output guard stays.
A fresh Yosys readback proves the candidate Verilog is exactly that graph;
it does not receive a forged production mapping or repair receipt.

The adapter falls to **0.0018922624 mm²**, a **70.6% component reduction**.
The exact LEF leaf delta is **−0.0045528448 mm²**, about **0.16%** of current BD
mapped logic. This one guard cannot deliver the broader area milestone alone.
No fresh global repair, placement or routing was run, so this is a component
delta on an otherwise identical repaired graph, not an accepted new chip-area
or energy result. Clock sinks and RTL/model wake activity are unchanged.

All ten candidate cases (five Liberty corners × 0.02/2 ns source slew) resolve.
The existing stage tool measures the complete loaded data/request/capture/ACK
paths at preserved native leaf pins, using the actual parent distribution.

| Corner | Current latest capture, ns | Candidate latest capture, ns | Candidate minimum local setup allowance, ns | At 15% two-sided sensitivity, ns |
| --- | ---: | ---: | ---: | ---: |
| TT 25°C 3.3 V | 297.737 | 92.537 | 34.413 | 12.423 |
| SS 125°C 3.0 V | 622.855 | 192.736 | 76.188 | 30.930 |
| SS −40°C 3.0 V | 425.693 | 132.117 | 52.684 | 21.757 |
| FF 125°C 3.6 V | 238.078 | 74.218 | 24.902 | 6.883 |
| FF −40°C 3.6 V | 160.927 | 50.309 | 16.791 | 4.579 |

Latest capture is the maximum across lanes, min/max timing queries and the two
source slews, referenced to the upstream request source Q. It is not the guard
adapter's standalone delay or a complete owner-transaction latency. Local setup
allowance is the earliest capture minus the latest same-lane data arrival and
the conservative Liberty setup aperture. It assumes the source boundary's
request/data launch alignment; the owner FIFO's actual launch is still open.

The initial count proposal is calculated **within each corner**, maximizing
across lanes and corners only after each ratio is formed. The proposal scales
the baseline request path to suggest a candidate count; it is not treated as a
calibrated chain model. Acceptance of the local result uses fresh timing of the
actual shorter graph, including its real interstage loading and slew.

The sensitivity check is `(1 − d) × capture_min − (1 + d) × data_max − setup`.
At `d = 0.15`, the smallest margin is **4.579 ns**. Reports also retain 0%, 5%,
10% and 20%; at 20%, the smallest margin is **0.508 ns**. These are sensitivity
values, **not a justified GF180 statistical mismatch bound**. The study makes
no mixed-cell tracking claim and does not remove or reinterpret a fixed-time
requirement.

The measured data cone is exactly unchanged in every case. Zero-source-reuse
hold and ACK-after-latest-capture are also unchanged, with respective minima
**1.154 ns / 1.348 ns**. This experiment does not consume their existing margin,
but their complete source-release and mismatch qualification remains open.

## Evidence and limits

The retained evidence is under `build/a7b-elapsed-guard/`:

- `baseline/results.json`: current recipe, all ten cases, source/tool/PDK hashes.
- `candidate-r2/results.json`: real shortened netlist, exact graph readback,
  loaded measurements, component delta and mismatch sensitivity.
- `controls-r1/`: analysis-period invariance and actual-arc short-request,
  early-ACK and late-capture controls. Final verdict is in `results.json`.
- `tools/test_experiment_elapsed_guard.py`: 12 deterministic graph and sizing
  controls, including changed reset masking, a branch/cycle, a changed terminal,
  invalid counts and the cross-corner-extrema error.

The original candidate attempt rejected the actual chain because the helper
expected a terminal buffer; the real recipe ends in a DLYD. The correction keeps
that original terminal DLYD and removes only interior cells. This tooling failure
is retained in `build/a7b-elapsed-candidate-r1.log`; it is not a timing result.

Whole-chip electrical reports still contain up to 645 violation rows in a
context, and queried paths reach 3.928 ns slew at the slow/hot corner. Those
violations are preserved. Positive local numbers do not establish electrical
closure, valid extrapolation or routed setup/hold margins.

Before production shortening, compose the elapsed FIFO/admission launch and
retention, pending admission, both BD return orders, pulse/reset envelopes and
capture distribution. Establish a GF180 mismatch policy and remeasure with
extracted min/max wire RC. The original reset mask remains, but removing delay
can alter reset/return ordering; logical masking alone does not prove that
envelope. Full-chip physical requalification stays at item 17, while other
independent ownership reductions can proceed.

Reproduction uses the same pinned tool configuration as the baseline mapping:

```powershell
$env:RISCAY_PHYSICAL_TOOLS=(Resolve-Path build/control-join-tools.json).Path
python tools/native_stage_timing.py build/control-frame-borrow/completion-final-map-bd build/a7b-elapsed-guard/baseline --variant bd --stage FourPhaseSoc.ca_child_elapsed_scaler.ca_child_native.ca_child_step --campaign
python tools/experiment_elapsed_guard.py build/control-frame-borrow/completion-final-map-bd build/a7b-elapsed-guard/baseline build/a7b-elapsed-guard/candidate-r2
python tools/check_elapsed_guard_controls.py build/control-frame-borrow/completion-final-map-bd build/a7b-elapsed-guard/candidate-r2 build/a7b-elapsed-guard/controls-r1
python -m unittest discover -s tools -p test_experiment_elapsed_guard.py -v
```

Each output directory must be new. Runtime configuration is hash-bound to the
accepted mapping; changing tools requires new matching evidence.

Fresh independent review recomputed all ten corner/slew margins and sensitivity
values, verified 244 input/evidence hashes and the four exact control verdicts,
and reran all 12 unit controls. It found no blocking issue in the isolated scope.
