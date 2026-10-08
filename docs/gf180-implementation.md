# GF180 implementation preparation

Both native variants now have experimental GF180 cell bindings, an implementation
top, three physical SRAM instances and generated constraints. These are inputs
to a first floorplan/P&R experiment, **not a timing-closed or tapeout-qualified
chip**. Placement, routing, analog layouts and the padframe remain outstanding.

## Physical top and policy

`physical/runMain riscay.physical.EmitPhysical` emits separate `bd/` and `click/`
designs. It enables `PowerPolicy(enabled=true)` to retain the complete Groundlark
supervisor during synthesis. Those threshold defaults are an **evaluation
fixture**, not qualified battery settings. Ordinary reference emitters retain
their disabled policy.

`RiscayMcuDigital` includes the 100,000-cycle reset qualifier and complete SoC.
Its pad-facing signals are three GPIOs, SCL, SDA sense/pull-low, ADC MISO/CS/SCLK,
and manual reset. Trace/commit/status bundles are not package interfaces; status
remains available through I2C. Internal oscillator and supply-monitor connections
are exposed at this digital implementation boundary.

`RiscayMcuChip.sv` connects the existing analog macro boundaries and presents nine
logical signal pins plus eventual supply pads. GPIO/SDA tristates are **logical
pad placeholders**. GF180 I/O cells, ESD, package and analog layouts still need
integration. Do not synthesize the shell as core logic and call it a finished
chip. `RiscayMcuDigital` is the P&R top.

Exactly three `gf180mcu_ocd_ip_sram__sram1024x8m8wm1` instances provide 2 KiB program
and 1 KiB working memory. `power.tcl` binds actual SRAM VDD/VSS and standard-cell
VDD/VSS/VNW/VPW LEF pins. No behavioral SRAM array enters implementation RTL.

## Technology binding

The local adapter binds each complete primitive parameter tuple, checks the RTL
inventory and rejects unknown models/parameters. It explicitly admits the pinned
SRAM source: the current library ASIC exporter rejects that additional source,
and its timing exporter deliberately rejects Click propagation-only signoff.
The sibling chisel-async repository is unchanged.

| Primitive | Existing GF180 standard-cell implementation |
| --- | --- |
| Asymmetric C-element | One preserved AOI21/NOR2 keeper implementing the complete n-ary set/hold equation and input inversions |
| Event register | Exactly WIDTH resettable DFFs with local clock/reset trees |
| Closing latch | Exactly WIDTH resettable latches; invert `closed` to obtain latch enable |
| Phase register | One reset/set DFF with inverted internal-Q feedback |
| AND/XOR | Explicit reset-dominant gates, inversions and characterized padding |
| Matched guards | Preserved native `dlyd_1` chains |
| Data allowance | The mapped transform and reset gating; no second long delay chain per data bit |

The C-element is a standard-cell composite, not a custom layout. Preserve its
feedback and qualify placement/routing explicitly. The netlist audit verifies
every protected leaf cell **and connection**, including all delay stages.

`physical/gf180/pdk-lock.json` pins the installed open_pdks GF180MCU-D snapshot
(revision `40cee970d8a9b7eaea35a34fe7d6068f05721f0a`), including Liberty, Verilog,
SPICE, LEF, GDS and transistor models. Keep these Apache-2.0 assets in ignored
`.tools/physical/pdk/`. SRAM assets have their own `soc/sram-lock.json` and
`.tools/gf180-sram/` directory. Preserve upstream notices.

## Timing targets

Whole-stage STA includes the register-read mux, decode/ALU and reset-gating path.
It found an approximately 13 ns address path and 102–134 ns execute paths at the
slow corner. The original 10/20 ns simulation budgets are unsuitable as physical
constraints; the physical policy allows 20/180 ns. Default simulation policies
remain unchanged.

| Target, ns | Four-phase BD | Native Click |
| --- | ---: | ---: |
| Normal / execute data | 20 / 180 | 20 / 180 |
| Normal / execute request guard | 29 / 189 | 26 / 186 |
| Offer guard | 31 | 36 |
| Acknowledgement guard | — | 36 |
| Stage control propagation | 1–10 | 1.5–10 |
| Local capture distribution | 4 | 2.5 |
| Storage propagation envelope | 10 including latch closure allowance | 10 |
| Setup / hold | 8 / 1 | 5 / 1 |
| Capture pulse high / low | 1.8 / 2 | 1.8 / 2 |

Auxiliary/RF controls retain 1–10 ns bounds. The RF forwarding guard remains
31 ns, exceeding three 10 ns writeback envelopes. DLYD chains have a lower
characterized area per guaranteed delay than long BUF chains; this is an
area-conscious candidate, **not a measured energy optimum**. Counts retain margin
over the five-corner minimum. Slew must remain at most 2 ns and adapter output
load at most 0.05 pF; recheck these with routing.

Characterization covers TT/25 C/3.3 V, SS/125 C/3.0 V, SS/-40 C/3.0 V,
FF/125 C/3.6 V and FF/-40 C/3.6 V, at 0.02/2 ns input slew and 0.003/0.05 pF load.
All 23 exact adapters in each variant pass propagation/distribution bounds.
Click phase feedback passes Liberty hold checks. Largest local distribution is
about 2.13 ns for Click and 3.48 ns for BD; latch distribution plus propagation is
also checked against its combined 10 ns envelope.

`check_gf180_envelopes.py` combines independent minimum/maximum cell bounds with
the whole-stage results. It passes 11 BD and 31 Click inequalities covering
writeback, setup, visibility and Click pulse settling. Receipts must match the
current mapping and netlist; equality or missing margin fails. Wire delays still
need to fit these margins after routing.

The complete transistor-level C-element circuits passed 140 input-order,
retention, reset, slew/load and PVT cases, with observed delays about
1.065–5.570 ns. These are schematic results without extracted wires or statistical
mismatch. Reuse evidence only when circuit graphs and pinned sources match.

## Separate analyses

`gf180_constraints.py` resolves the audited synthesized hierarchy, including
generated names. Missing or ambiguous objects fail.

- `base.sdc` defines a 50 ns service clock, 12 Hz LF clock and electrical bounds.
- `clocked.sdc` defines the related gated work clock and specific first-stage
  synchronizer exceptions. Gray transfer has a separate 50 ns bound. SRAM retains
  falling-edge launch/rising-edge capture and normal 25 ns half-cycle checks.
- `async.sdc` supplies output-load, conservative transform and BD fork checks.
  Its clocked view includes upstream storage propagation and can overconstrain
  transparent async latch networks. Use **isolated-stage STA** to characterize
  the transform; periodic-pipeline STA does not prove the async protocol.
- `preserve-mapped.tcl` protects exact physical cells. `feedback-cuts.tcl` cuts
  C-element feedback for analysis only; never remove the physical feedback.
- `check-async-paths.tcl` measures internal paths separately, removing each
  exception before the next. Use a fresh STA context. OpenSTA diagnoses these
  internal path-break endpoints as nonstandard; absent paths are errors.
- `event-monitors.sv` binds exact leaf pins for SDF setup/hold, pulse and recovery
  checks and prints capture counts. Phase feedback hold uses Liberty checks.
  Zero activity cannot establish coverage. Independent tests reject deliberately
  bad setup, hold, pulse high/low and reset recovery.

**Full-chip timing remains open.** Unplaced clocked reports retain reset/recovery,
electrical and conservative async-path violations. No broad clock-group/reset
exception hides them. The next P&R experiment must address clock/reset trees,
CDC rationale, inter-stage wiring, BD relative ordering, extracted Click
pulse/aperture behavior and SRAM setup/hold. Standalone-cell/stage passes do not
replace these checks. The falling-SDA START detector also needs external SCL
setup/hold qualification. I2C is limited to 400 kHz; provisional ADC input/output
budgets are 10 ns and must be checked against final pads and board timing.

## Reproduction

The current Windows flow uses repository-pinned Yosys 0.33/sv2v in Ubuntu WSL,
ngspice 42, and OpenSTA 2.7.0 in `nixos-librelane`. Its explicit executable path
is in `characterize_gf180_liberty.py`. Supply hash-matching PDK files and use
`tools/sram_assets.py` to fetch/verify SRAM views. Java/firtool setup follows
[build and test](build-and-test.md). Missing tools/views are errors.

```powershell
python tools/sbt.py 'physical/runMain riscay.physical.EmitPhysical build/gf180'
foreach ($designVariant in @('bd', 'click')) {
  python tools/gf180_physical.py "build/gf180/$designVariant" "build/gf180/$designVariant-mapped"
  python tools/check_gf180_cells.py "build/gf180/$designVariant-mapped"
  python tools/characterize_gf180_liberty.py "build/gf180/$designVariant-mapped" "build/gf180/$designVariant-pvt"
  python tools/gf180_implement.py "build/gf180/$designVariant-mapped"
  python tools/gf180_sta.py "build/gf180/$designVariant-mapped" "build/gf180/$designVariant-sta"
  python tools/characterize_gf180_stages.py "build/gf180/$designVariant-mapped" "build/gf180/$designVariant-stages"
  python tools/check_gf180_envelopes.py "build/gf180/$designVariant-mapped" "build/gf180/$designVariant-pvt" "build/gf180/$designVariant-stages" "build/gf180/$designVariant-envelopes.json"
}
python tools/characterize_gf180_keeper.py build/gf180/bd-mapped build/gf180/keeper-pvt
python tools/sbt.py 'physical/test'
python -m unittest discover -s tools -p 'test_*.py'
```

Use fresh output directories. Successful `gf180_sta.py` execution means binding
and analysis ran, not that timing closed; inspect JSON and logs. Use the mapped
`filelist.f` and matching Liberty/LEF/GDS views, never the behavioral ChiselAsync
models. Load power and preservation rules before physical optimization. For
event verification, annotate extracted SDF and define `RISCAY_DUT` when compiling
the generated monitors.
