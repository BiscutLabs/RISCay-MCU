# Build and test

## Fast gate

Run one sbt process at a time across RISCay-MCU and chisel-async. The supported
library source is pinned in
[`project/chisel-async-source.json`](../project/chisel-async-source.json).
`build.sbt` reads that pin and uses an exact-commit Git source dependency. sbt
fetches and compiles it automatically; no sibling checkout or `publishLocal`
artifact is required. The selected revision is `856fc75`, which retains the
passive primitives from `06b1216`, the generation-time structural audit and
opt-in resetless BD payload storage. Only explicitly audited transient owners select it.
The first build needs Git/network access and the normal Maven dependencies.
Use JDK 21, firtool 1.160.0 and Icarus 13. The library provides checksum-verified
bootstrap scripts for those tools. Set `JAVA_HOME`, `CHISEL_FIRTOOL_PATH`,
`CA_IVERILOG` and `CA_VVP` to their installed paths.

```text
python tools/ci.py --output build/ci-local
```

The output directory must be new. This runs Python discovery, then one sbt process
for timestamp arithmetic and the selected core, fabric, Control, CRC, housekeeping, frame, reset bridge,
retained register-view, event-oracle, sleep, I2C wire/earliest-loader-status and
boot-ingress suites, the generic SPI boot cases and physical export/core
policy suites. It checks fresh, nonempty JUnit results for every requested suite.
SRAM is part of this gate, and the unchanged earliest-status test body also runs
on the clocked implementation at 400 kHz SCL with 3.2/20 MHz test clocks.
The retired shared-oscillator prototype and its fixtures have been removed.
Reference CI exports the clocked chip and runs the Phase 0 equivalence harness
against itself; this is explicitly not generated multi-bank acceptance.
The rebuild additionally needs flow comparison, folded combinational equivalence,
whole-chip graph and area gates before it can pass. Solver tests reject changed next-state
logic and changed fixed-memory inputs. Repeated exports must preserve every RTL
and interface file; address sets are ordered before constructing hardware.
Yosys and sv2v are required even for the
Python gate; CI installs Yosys 0.33 and checksum-pinned sv2v 0.0.13.
Missing suites, failed cases and unexpected skips fail the run. Linux may skip
only the Windows mounted-drive translation test. CI runs the same entry point on
every push to main and on pull requests, bootstraps the exact library source and
pinned simulator, and retains logs, JUnit XML and one run receipt. The 60-minute
job limit allows a cold compiler/simulator bootstrap; it is not a simulation timeout.
The single run receipt includes the actual source-built library JAR, recorded by
the `libraryRuntime` sbt task. Its version label may still say SNAPSHOT; dependency
resolution is by the full immutable Git SHA, not a SNAPSHOT repository coordinate.

For Python alone:

```text
python tools/ci.py --python-only --output build/python-local
```

The cleanup inventory and deliberately retired coverage are documented in
[test-suite cleanup](test-suite-cleanup.md). Historical counts are evidence, not
assertions that future designs must match.

## Desync storage-area experiment

For the desync storage-area experiment, select the same physical-tool
configuration used for the clocked reference (currently Yosys 0.62/ABC), then run:

```text
python tools/map_desync.py build/desync-multibank/generic/netlist.json physical/desync/bank-map.json build/storage-reference --reference
python tools/map_desync.py build/desync-multibank/generic/netlist.json physical/desync/bank-map.json build/storage-candidate
```

Both directories must be new. These runs share generic input, ordinary
optimization, tools and Liberty. The candidate has external bank-enable
placeholders; its report is explicitly storage-only and cannot satisfy the
whole-chip budget or timing gate. No production desync export is emitted.

## Extended chip verification

```text
python tools/sbt.py --bootstrap verification/test physical/test
```

Use affected suites during development. Boot/loader changes require the complete
`GenericBootSpec`, including full-capacity persistence, lock, interrupted update,
watchdog and shared ADC-bus cases. Reset changes require `ResetBoundarySpec`,
`ResetBoundarySocSpec`, `ControlResetSpec` and `RecoveryOwnershipSpec`, followed by
service, sleep, loader and firmware regressions. Memory changes require both
variant SRAM/loader tests. `AsyncMacroByteOwnerSpec` runs actual pin-level scenarios
for the isolated self-timed SRAM experiment; it does not qualify production SRAM
or physical pulse/aperture timing. `FirmwareSpec` builds the generic RV32E fixtures
using `tools/build_firmware.py`; no Groundlark firmware is built by this repository.

Keep failing logs. Do not weaken functional deadlines, retention checks or error
oracles to accommodate an implementation failure. A host-process timeout is
distinct from a simulated deadline and must be reported if changed.

## Clocked comparison design

The fast gate also runs the clocked core, SoC, fabric, reset-boundary and sleep
cases, plus the same generic SPI-boot cases. Event history is compared across the three
existing implementations (BD, Click and clocked). The extended clocked suites reuse the existing test bodies:

```text
python tools/sbt.py "verification/testOnly riscay.ClockedDeepSleepSpec riscay.ClockedGenericBootSpec riscay.ClockedFirmwareSpec riscay.ClockedPhysicalEstimateSpec"
python tools/sbt.py "clocked/runMain riscay.clocked.EmitClockedSoc build/export/clocked"
python tools/map_clocked.py build/export/clocked build/map-clocked
```

The mapping command requires configured physical tools and the same GF180 PDK.
It measures flattened mapped area before repair/CTS/routing and emits one run
receipt. `clocked.json` deliberately replaces the async timing contract; do not
run the native export checker on a synchronous design. See the
[clocked contract](clocked-design.md) for its separate clock/reset obligations.

## Desynchronization Phase 0

Phase 0 established the tooling and fair clocked reference.
The [design contract](desync-contract.md) and [ledger](desync-ledger.md) state
the boundary. The rebuild now generates banks from the clocked netlist; the
single-oscillator prototype is retired. Physical primitive recipes remain unavailable.

```text
python tools/clocked_physical.py build/map-clocked build/clocked-physical
python tools/size_desync_delays.py build/clocked-physical build/region-requirements
python tools/equiv_desync.py build/export/clocked build/export/clocked build/equiv-reference
```

Use the configured, progress-fixed OpenROAD build recorded in the ledger. The
physical command repairs, places and builds clock trees, proving graph and sink
coverage and requiring clean electrical reports at all five corners. It is not
a routing/signoff flow. The region command measures full- and half-cycle STA
requirements on that netlist; it does not invent a delay count. The recipe
loader rejects missing, stale, nonphysical or under-sized measurements. A future
loaded mixed-cell chain must pass at every corner before publishing a policy.

`tools/primitives.py` is the single registry for the new controller, delay and
join, enable gate, stop point and mutex identities. Unavailable recipes fail closed. The area reporter reads
storage from Liberty and rejects protected ordinary state/data. It emits one
JSON line per comparison and checks matched configuration/tool inputs.

Run the fast gate with both measured comparisons for each physical batch:

```text
python tools/ci.py --output build/ci-measured --area-mapping build/map-clocked/netlist.json --area-reference build/map-clocked/netlist.json --physical-mapping build/clocked-physical/cts.json --physical-reference build/clocked-physical/cts.json
```

These are reference self-comparisons. The generated multi-bank design must later
supply the candidate, including its controllers and mutex. Default portable CI has no PDK, so it runs the budget/protection/sizing
properties, solver controls and simulation gate; measured area comparisons need
the explicit arguments above. Budget increases fail both against the specified
ceilings and the prior commit. Keep two Git revisions available for that check.
Never interpret a reference ratio of 1.00 as a measured desync result.

## Exports and structural rules

```text
python tools/sbt.py 'fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/export/bd' 'twoPhaseClick/runMain riscay.click.EmitClickSoc build/export/click' 'physical/runMain riscay.physical.EmitPhysical build/export/physical'
python tools/check_export.py build/export/bd --output build/check-bd
python tools/check_export.py build/export/click --output build/check-click
python tools/check_export.py build/export/physical/bd --output build/check-physical-bd
python tools/check_export.py build/export/physical/click --output build/check-physical-click
```

Generation runs chisel-async's typed structural audit before publishing the
contract. The MCU reader checks that audit against the exact contract, typed IR,
RTL file inventory and port ABI digest, and checks fixed SRAM model contents.
It does not rewrite generated Verilog or probe testbenches. This is structural
acceptance, not the former exhaustive dynamic export-probe campaign. The retired
manifest/packing/timing-marker integration checks are listed explicitly in the
cleanup document; library-owned validation and RTL behavioral tests remain.

Run the integration-specific reset crossing proof separately on production exports:

```text
python tools/check_reset_crossings.py build/export/physical/bd
python tools/check_reset_crossings.py build/export/physical/click
```

That proof still uses synthesized graph data because reset ownership and
close/rebase containment are MCU integration properties not yet represented by
the library's generic generation audit. It also checks passive-allowance fanout.

## Physical checks

Configure `RISCAY_PHYSICAL_TOOLS` as described in
[GF180 implementation](gf180-implementation.md). Physical flows remain optional, separate
from the portable fast CI gate; they require the pinned PDK and EDA tools.

```text
python tools/gf180_physical.py build/export/physical/bd build/map-bd
python tools/gf180_implement.py build/map-bd
python tools/report_repair_area.py build/map-bd build/area-bd.json
```

Default mapping runs electrical repair. Its whole-graph proof contracts only
approved buffers, equivalent resizes and ties; protected primitive cells and pins
must remain intact and added unused cells are rejected. Timing queries cut only
reviewed primitive-internal keeper arcs. Stage measurements use protected leaf
pins on the repaired graph; setup, hold and ACK checks remain distinct.
`check_native_stage_controls.py` is the shared actual-arc negative-control runner,
limited to one or two representative stage instances. There is no per-owner
successor/attestation campaign. `size_ordering_guards.py` requires every selected
owner/corner/slew obligation and fails on missing, nonfinite or negative margins.

P&R checkpoints retain their graph, clock and RC dependency checks; they are
restart prerequisites, not a second approval or attestation layer. Full extracted
min/max-RC, mismatch, reset and macro timing qualification remains item 17 of the
[migration checklist](async-soc-migration.md). Digital passes and zero-wire local
margins do not establish physical signoff.

## Historical evidence

Older review and migration documents record the tools and acceptance rules used
at their original revisions. Deleted commands there are historical recipes; use
this page for current entry points. Prior failure logs and generated evidence
remain under ignored `build/` directories. Source history remains in Git.

## Retained-bank reader timing

After accepted BD mapping and electrical repair, run:

```text
python tools/telemetry_bank_timing.py build/map-bd build/bank-readers
python tools/telemetry_bank_timing.py build/map-bd build/adc-readers --bank adc
python tools/native_stage_timing.py build/map-bd build/telemetry-stage --variant bd --stage FourPhaseSoc.ca_child_telemetry.ca_child_update --campaign
```

All outputs must be fresh directories. The bank commands inventory every periodic
reader and check per-cell apertures plus feedback ordering. The third command
uses the existing standard-stage campaign. These zero-wire checks
complement the reader-qualification assertions; routed skew/RC remains open.

Optional software sample configurations need their own closed-bank screen:
`physical/Test/runMain riscay.physical.EmitSoftwareSamples <fresh-directory>` emits
an ADC-plus-software-channel BD fixture. Map/repair it, then run
`telemetry_bank_timing.py <mapping> <fresh-output> --bank software`.
Sample runs also inventory all periodic launches into timestamp arithmetic,
including elapsed-receipt valid gating, and check them against one 50 ns period.
Native sequential outputs delimit that analysis query; their receipt-launch
composition remains a separate obligation, not a false path or timing waiver.
The sample screens also check the shared upper-time counter and every periodic
reader reached from it against one 50 ns period. The sample bank's conditional
five-edge read qualification gives no extra time to these clocked paths.

Elapsed operand ports get a separate conditional receiver-side screen: 100 ns
from synchronized request detection to earliest acceptance, and hypothetical
immediate source reuse at ACK for hold. Source publication alignment, actual
loaded source slew and unrelated native admission qualifiers remain separate
obligations. The tool samples both min/max at each source-slew scenario and
encloses their combinational arc costs before searching all paths, preserving
NLDM nonmonotonicity without an endpoint tolerance. Exact cone/profile coverage
is mandatory. This bounds the sampled mode graphs, not continuous slew or routing.

## Multi-bank preflight

`desync_partition.py` reads hierarchy-preserving Yosys JSON after `proc; opt`,
before techmap. `desync_graph.py` screens candidate bank topology:

```text
python tools/desync_partition.py build/generic/netlist.json physical/desync/bank-map.json build/partition.json
python tools/desync_graph.py build/partition.json build/graph-screen.json --flop-bank cpu --phase-aware --reachable-stop
python tools/characterize_desync_primitives.py build/desync-primitives
python tools/characterize_desync_primitives.py build/desync-primitives-broken --negative-control
```

The screen deliberately exits nonzero with `status: incomplete`. It checks the
mixed-edge abstract graph and drains every reachable marking from the selected
stop point; it cannot prove physical controller correspondence or handshake-wire
rest. The output names unresolved obligations. The schematic campaign samples
registry candidates at five PVT corners, two slews and two loads using the pinned
GF180 models and configured `ngspice`. Its negative control must exit nonzero with
`DESYNC_PRIMITIVE_STATE`. These samples do not accept a physical binding or a
minimum pulse width. Generated artifacts and failed experiments stay in `build/`.
There is no desync sbt project or generated-chip export command yet. Clocked RTL
is the sole source; the new transform and physical primitive characterization
must be implemented before chip-level desync tests are meaningful.
