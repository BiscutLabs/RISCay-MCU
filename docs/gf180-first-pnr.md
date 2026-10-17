# First GF180 place-and-route experiment

Current flow note (2026-10-17): `gf180_pnr.py --placement-density` exposes the
placement target independently of `--die-side-um`. The default remains 0.50.
The requested comparison uses 0.60 and 0.70 with a common 3250 µm outline and
unchanged macro positions for both variants. Density is bound into the run's
geometry; changing it on resume is rejected before any output write or tool
launch. Use new output directories for each case. This adds the comparison
control; those density runs and their area/electrical conclusions remain open.

On 2026-10-08 both native variants completed digital-block floorplanning,
placement, clock-tree synthesis, global routing, detailed routing and nominal
wire-parasitic extraction. **Both route; neither has timing closure.**

The pre-P&R work was committed and pushed as
`8637099bb603543b4d8e1d76de2bf165bbaa171a`. Inputs are the final 20/180 ns
physical-policy exports described in [implementation preparation](gf180-implementation.md).
The enabled Groundlark policy remains an evaluation fixture.

These are historical results for `8637099`, before the asynchronous SoC migration
and reset-boundary corrections. They do not qualify the current RTL. Re-export,
remap and repeat physical verification for the current implementation.

## Results

Both designs use the same 1440 × 1440 µm digital-block outline (2.0736 mm²),
the same three SRAM positions, and the pinned GF180MCU-D five-metal stack.
The nominal core rectangle is 30,30 to 1410,1410 µm, snapped to legal rows.
This is not a minimum-area result or a complete chip/wafer.space slot claim.

| Measurement | Four-phase BD | Native Click |
| --- | ---: | ---: |
| Placed logic + SRAM area, including inserted clock/tie cells | 1.074506 mm² | 1.094996 mm² |
| Nominal core occupancy, as reported by OpenROAD | 57% | 58% |
| Detailed-route signal/clock wire length | 1.336803 m | 1.360332 m |
| Global-routing overflow | 0 | 0 |
| Detailed router's remaining violations | 0 | 0 |
| Protected async cells verified unchanged | 4,350 | 4,076 |
| Physical SRAMs | 3 | 3 |

BD uses about 1.9% less placed cell/macro area in this run. Both received the
same block area; this small difference does not establish an energy winner.
The area excludes pads, analog macros, final fill and a chip-level boundary.

The router's zero-violation result is **not foundry-deck DRC/LVS signoff**.
The technology reader reports unsupported LEF58 via-enclosure properties, and
PDN generation reports skipped candidate vias at small SRAM pin overlaps.
Both supply grids pass the floorplanning connectivity check, and every
standard-cell/macro power and well terminal has a net connection. IR drop,
antenna, full layout rules, fill and final physical connectivity remain open.

## Timing findings

Five cell corners were analyzed using the extracted **nominal** wire RC.
Minimum/maximum wire corners and local variation are still outstanding.

- Reset distribution is a major electrical problem: a small inverter drives
  over a thousand loads. Typical-corner reported slew reaches about 106.6 ns
  against a 2 ns limit. These overloaded paths need buffering; extrapolated
  timing values outside the characterized envelope are not qualified estimates.
- Reset recovery/removal and clocked setup/hold reports retain violations.
  The independent LF clock and its reset/startup sequence also need a sound
  release model. A large negative LF slack must not be interpreted as a CPU
  frequency measurement or hidden with a blanket false-path exception.
- At SS/125 °C/3.0 V, BD's longest measured local capture-distribution path is
  **5.46 ns against 4 ns**; Click's is **3.96 ns against 2.5 ns**. Placement/local
  distribution needs work before reconsidering the guard budgets.
- Several individual control paths exceed their 10 ns maximum at that corner:
  up to approximately **10.53 ns for BD** and **11.72 ns for Click**.
- Reported SRAM-input setup/hold paths have positive slack at all five cell
  corners: the minimum reported margin is **13.10 ns for BD** and **13.55 ns for
  Click**. This does not close every SRAM read/response or clocked-island path.

The internal async probes are deliberately separate from ordinary clocked STA:

| Cell corner | BD: pass / violation / uncovered | Click: pass / violation / uncovered |
| --- | ---: | ---: |
| TT, 25 °C, 3.3 V | 83 / 0 / 2 | 82 / 0 / 1 |
| SS, 125 °C, 3.0 V | 76 / 7 / 2 | 77 / 5 / 1 |
| SS, -40 °C, 3.0 V | 83 / 0 / 2 | 79 / 3 / 1 |
| FF, 125 °C, 3.6 V | 83 / 0 / 2 | 82 / 0 / 1 |
| FF, -40 °C, 3.6 V | 83 / 0 / 2 | 82 / 0 / 1 |

These measure primitive propagation and capture distribution, not complete
end-to-end bundling, hazards or pulse/aperture correctness. OpenSTA emits its
documented nonstandard-endpoint warnings for these explicit internal path
breaks. Missing paths remain uncovered: BD's address acknowledgement primitive
and initial constant-data primitive, and Click's address acknowledgement guard.
Each measured group checks destination coverage; an absent destination cannot
count as a pass. Extracted event simulation and feedback SPICE are pending.

## Flow and safeguards

- OpenROAD revision `dcf36133a369abc8f3c5e5738cd4d82e4903c0e0` runs in the
  `nixos-librelane` WSL distribution. Existing cell/SRAM locks remain; the added
  `physical/gf180/routing-lock.json` pins technology LEF, tracks and RCX rules.
- `gf180_pnr.py` converts hierarchical SDC interfaces into connected physical
  leaf pins using the Yosys connectivity graph. It accounts for aliased ports
  and fails on missing drivers, interfaces or inconsistent widths.
- Placement uses congestion optimization without timing-driven resizing.
  Generic data/reset timing repair is deliberately absent from this first run;
  remaining electrical failures are reported. Service, gated-work and LF clock
  roots are selected explicitly. Self-timed capture trees are preserved.
- Protected cell identities and every protected signal-pin net are checked
  after each phase. Protection is released only around power-net binding,
  because OpenDB otherwise skips supply connections on protected cells.
- Two newly inserted BD tie-cell names confused SPEF hierarchy lookup. The
  extraction step gives hierarchical-looking tie instances simple flat names;
  cells, nets, placement and routes are unchanged. Analysis uses the matching
  `extract.odb`; unknown SPEF instances/nets fail the analysis script.
- Six new Python controls test interface aliasing and missing/constant paths.
  The complete Python suite passed **59 tests**. Negative controls against both
  actual routed databases detected deliberately disconnected and rewired
  protected pins. No RTL or physical cell graph changed in this P&R experiment;
  the preceding RTL regression was not repeated.

## Reproduction and evidence

Starting from a mapped, audited export with generated constraints:

```powershell
python tools/gf180_pnr.py build/physical-qualified-inputs/bd-dly build/pnr-new/bd
python tools/gf180_pnr.py build/physical-qualified-inputs/click-dly build/pnr-new/click
python tools/report_gf180_pnr.py build/physical-qualified-inputs/bd-dly build/pnr-new/bd
python tools/check_gf180_routed.py build/physical-qualified-inputs/bd-dly build/pnr-new/bd --corner ss_125C_3v00
```

Run both report tools for each variant and all five `--corner` values with each
`--wire-corner nom|min|max` for a complete internal-probe sweep.
`report_gf180_pnr.py` covers all fifteen cell/RC combinations itself. Current
runs extract three independent RC views; the historical nominal-only records
below are not accepted by these tools. `--die-side-um` sets the outline before
placement; matched comparisons must use the same feasible geometry. `--only`
on the probe tool creates an explicitly partial diagnostic report.
Use `--run-tag <new-tag>` for a fresh analysis of an unchanged route; existing
output directories are never overwritten. Local probes prepare their isolated
timing graph once and still require every expected pair, polarity and min/max
result, with fail-closed query limits.
`--from-stage` resumes a saved checkpoint; `--to-stage` stops after one.
Keep failed evidence when changing an experiment. New runs snapshot their Tcl
flow sources using the hashes of all three input files. Resume and reporting
reject changed mapping/constraint inputs, generated configuration, snapshots,
protected-connectivity baselines, databases or extracted parasitics. Resume keeps
the original checkout identity and copies all existing top-level experiment
files into a new `resume-history/` attempt before overwriting logs or outputs.
An archive failure stops the retry. This can require substantial disk space.
Resume invalidates
downstream checkpoint records before rerunning a stage. The checkout identity is
the flow's checkout, while the recorded mapping hashes identify its actual RTL.
Successful process completion means the experiment ran, not that its reported
timing violations passed.

The archived first-run records below predate this complete input binding. They
remain historical evidence; the current tools reject their resume/reanalysis
with `PNR_FRESH_RUN_REQUIRED`. Start a fresh run rather than adding provenance
fields to old records. The pre-commit controls exercise input tampering, both
report entry points, immutable snapshots and resume history without launching
OpenROAD; they do not constitute a new physical run.

Final evidence is under `build/pnr-first/bd-v5/` and `build/pnr-first/click-v2/`:

- `route.odb`, `route.def`, `extract.odb`, `extract.v`, `routed.spef`, `layout.png`;
- `results.json`, `run.json`, `route-drc.rpt`, clocked and electrical reports;
- `sta-*/check.log`, `async-*/results.json`, and `audit-controls.log`.

Older directories record bring-up failures; `pre-tie-annotation-fix/` preserves
analysis before the SPEF naming correction. Generated files remain ignored.

The next iteration should repair reset distribution/release, improve local
capture distribution, and complete coverage of the routed timing obligations.
The [matched comparison](gf180-matched-comparison.md) adds minimum/maximum RC
extraction and broader probe coverage. Event/feedback checks and full physical
verification remain required before optimizing the block outline.
