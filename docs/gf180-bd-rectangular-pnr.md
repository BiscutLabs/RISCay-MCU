# BD layout on a 3.93 × 2.53 mm outline

> **Void for routed electrical/timing qualification:** this run predates the
> wire-resistance unit and explicit SPEF-load fixes. Geometry/area and retained
> DRC observations are historical only. See [withdrawn results](gf180-routability.md#withdrawn-physical-results).

Historical comparison run. The [1.94 × 2.53 mm rerun](gf180-bd-1940x2530-pnr.md)
uses the same mapping and physical recipes on a narrower outline.

This run places and routes the generic MCU digital top, `RiscayMcuDigital`, in
GF180MCU-D. BD is the only implementation run. The outline is **3,930 × 2,530 µm**
(**9.9429 mm²**), with a 30 µm core inset and a 0.60 placement-density target.
The density target is a placer setting, not the final fraction of die occupied
by cells. Pads, analog macros and their integration are outside this layout.

The input is the accepted BD mapping in `build/generic-mcu-r10/map-bd`, from the
generic-MCU correction. Checkout `517c272` changes no RTL, ROM payload, mapping
recipe or SRAM assets relative to `d690e8f`, so this mapping remains applicable.
This batch adds rectangular-outline support to the P&R runner without changing
RTL or timing recipes. All three 1 KiB SRAM macros retain their fixed identities;
their lower-left locations are (100, 1954), (1814.35, 1954) and (3530, 1954) µm.

## Routed result and structural checks

Detailed routing completes with **zero router DRC violations** and 5,448,279 µm
of reported routed wire. Final cell footprints total **3.628786 mm²**, unchanged
from global-route repair: 36.50% of the die or 37.96% of the core. This is not a
foundry DRC/LVS or timing-closure result.

All six stages complete, including independent nominal/minimum/maximum wire RC
extractions. The [original image](images/bd-layout-3930x2530.png) is the unmodified
2,400 × 1,545 pixel OpenROAD render of `route.odb`, visually checked for the full
outline and all three SRAMs.

Areas below sum cell footprints from the pinned LEFs and the actual OpenDB
instance inventories. Logic excludes SRAM, tap cells and endcaps. The three SRAMs
occupy 0.466241 mm², and taps/endcaps occupy 0.266857 mm² from floorplanning onward.

| Stage | Logic, mm² | All cell footprints, mm² |
| --- | ---: | ---: |
| Accepted mapping before floorplanning | 2.283901 | 2.750142 |
| Floorplan, including added tie cells | 2.297784 | 3.030882 |
| After placement repair | 2.714029 | 3.447127 |
| After clock-tree synthesis | 2.762082 | 3.495180 |
| After global-route repair | 2.895688 | 3.628786 |

Placement repair adds 0.416245 mm², clock-tree insertion adds 0.048053 mm² and
global-route repair adds 0.133606 mm². These are physical implementation costs,
not changes to the mapped RTL area. The clock proof covers all 4,125 periodic
storage sinks, including the work clock and all three SRAM clock drivers. The
SDA event path is excluded from CTS. Full graph proofs pass after both repair
passes and CTS; all 26,793 protected native cells and their connections survive.

## Reproduction and evidence

Use the pinned physical tools and assets described in the
[build guide](build-and-test.md). The selected OpenROAD is the existing patched
26Q2 build, whose executable and wrapped binary are recorded in `run.json`.
`RISCAY_PHYSICAL_TOOLS` selects the local runtime configuration; `--openroad`
overrides only the P&R executable, preserving the mapper's existing receipt.

```powershell
$env:RISCAY_PHYSICAL_TOOLS='P:/Personal/RISCay-MCU/build/control-join-tools.json'
python tools/gf180_constraints.py build/generic-mcu-r10/map-bd
python tools/gf180_pnr.py build/generic-mcu-r10/map-bd build/pnr-bd-3930x2530-r1 `
  --die-width-um 3930 --die-height-um 2530 --placement-density 0.60 --threads 8 `
  --openroad /nix/store/hrxjpkkppbzkcnzf44f60lsm0cj1f4yh-openroad-26Q2/bin/openroad
python tools/render_gf180_layout.py build/generic-mcu-r10/map-bd `
  build/pnr-bd-3930x2530-r1 build/pnr-bd-3930x2530-render-r1
```

Use fresh output directories when repeating the commands. The P&R directory
retains stage databases, graph proofs, clock coverage, per-corner electrical
reports and nominal/minimum/maximum RC extraction evidence. The renderer reads
`route.odb` directly with the same OpenROAD GUI in offscreen mode. Its receipt
binds the input database, tool and PNG; the image dimensions are checked against
the requested outline. The archived documentation image is a copy of that PNG.

The 295 Python tests pass (`build/pnr-bd-3930x2530-python-r2/`), including the
rectangular-geometry property and existing graph/clock/provenance controls.
Independent review reproduced the LEF area totals and checked the graph proofs,
clock inventory and rendered outline. No RTL changed, so no new Scala simulation
result is claimed for this physical-only batch.

## Qualification boundary

Completing routing and extracting parasitics does not establish async timing
closure. Residual electrical violations, composed setup/hold/ACK paths, reset
distribution, SRAM clock pulse/aperture checks and mismatch qualification remain
explicit gates. Detailed-router DRC is narrower than foundry-deck DRC, antenna
and LVS. No routed hold cells are claimed as part of this run; the separate
0.05 mm² hold-repair planning reserve remains unspent.

The extraction-stage electrical reports at nominal wire RC still report
80 / 1,689 / 98 / 80 / 0 slew-violation rows at TT 25°C / SS 125°C / SS −40°C /
FF 125°C / FF −40°C respectively. The worst reported slew is 5.041401 ns at
SS 125°C against a 2 ns limit; those reports contain no capacitance violations.
These are pin rows, not unique nets or a complete relative-timing assessment.

The additional `report_gf180_pnr.py` combined timing campaign **did not complete**:
`async-pnr.sdc` still references the original tie-cell pin
`soc/ca_child_completion/$auto$hilomap.cc:48:hilomap_worker$410/ZN`, which exists
in the routed database but is renamed for SPEF lookup during extraction.
It stops with `UNRESOLVED_PHYSICAL_PIN`; the original failure is retained in
`build/pnr-bd-3930x2530-reports-r1.log` and the run's `sta-*/check.log` files.
The reference must be rebound before that campaign can produce a valid combined
timing report. No timing constraints were waived or dropped to bypass it.
