# Wire-dependent electrical repair

The default GF180 P&R flow runs graph-checked `repair_design` twice: after
placement with estimated placement parasitics, and after global routing with
estimated route parasitics. The latter uses incremental rerouting after repair
and detailed placement. This adds no clocked RTL or native timing waiver.

All five pinned cell PVT corners are loaded, including the matching SRAM Liberty
files. Each repair writes per-corner slew/capacitance reports before and after
repair. The wire estimate uses the existing nominal layer RC model at every PVT
corner. This is **not extracted min/max wire RC**, and successful repair is not
electrical or asynchronous timing closure.

P&R uses an **electrical and real-clock optimization context**. The complete
bound `async-pnr.sdc` remains saved and hashed. A fail-closed splitter retains
every native max-capacitance constraint in `async-electrical.sdc` and records
every deferred max/min-delay and data-check command in `async-context.json`.
Unknown commands reject generation. Base limits, real clocks, boundary
constraints, keeper cuts and native protection remain loaded. Checkpoint
`*-clocked-timing.rpt` files are clocked-context diagnostics, with no async timing
coverage. Separate async analysis must use the actual repaired graph and retained
obligations; merely saving those obligations does not count as checking them.

The initial combined-context run loaded 1,167 cap
constraints, 215 broad max-delay commands and 92 data checks. At 813 seconds its
repair process used 36,436,424 KiB RSS and still reported iteration zero. A
concurrent Click run was stopped first at 17,416,652 KiB to avoid exhausting WSL
memory; BD was then stopped deliberately. Both are resource-limited attempts,
not accepted repair or timing results. The separate-context r7 retry still grew to
14,796,092 KiB at 222 seconds and was stopped for a net-level diagnostic retry.
Its five before-repair electrical reports are **byte-identical** to r6, proving
that the split retained the reported electrical problem. It did not establish a
resource fix.

The r8 live GDB stack and r9 detailed trace locate the failure in
`RepairDesign::repairNetWire`. An ordinary AOI222 output in execute drives one
OAI22 input. The resizer repeatedly inserts `clkbuf_1` at the same coordinate:
split length 0, remaining wire 117.6 um, load 0.021 pF against its derived
0.003 pF limit. The source contains an unbounded insertion loop for this case.
This supersedes the initial arrival-search hypothesis. Neither separating timing
contexts nor retrying with more memory fixes the observed defect.

The [pinned progress backport](../../physical/gf180/openroad/README.md) preserves
the upstream two-attempt and sub-DBU checks. It leaves a segment explicitly
unrepaired when buffering makes no progress. That is not proof that the circuit
is physically impossible, and residual reports remain authoritative. The
candidate runtime is isolated from the accepted mapper; P&R binds its launcher,
wrapped executable, configuration and patch/recipe before and after execution.
The backport passes all 7,631 packaged tests. The upstream stall control times
out on unmodified 26Q2 and completes on the candidate with its violations still
present. An ordinary repair control clears its violations, and a separate
zero-distance control permits two useful load reductions without triggering the
progress stop. [Compact evidence](openroad-progress-evidence.json) binds the
fixtures, logs, recipe and both executable files.
The default runtime is not silently replaced. No false path, electrical limit,
timing bound or circuit logic changed to accommodate this investigation.

## Protection and acceptance

Native leaves retain their masters and exact signal pin-net connections.
OpenROAD cannot insert a buffer before a `dont_touch` native cell in this pinned
build. The flow therefore also locks every native input net and every internal
net shared by multiple pins of one primitive. Nets directly joining a protected
pin to a top-level port are also locked: output buffering would move that native
pin to a different net. It records the exact protected-net inventory. Native
outputs driving only ordinary internal loads remain repairable.

The patched BD r10 run completed repair but was rejected by the unchanged
snapshot. Of 149,285 protected pins, only the I2C observation register's Q changed:
`sdaLow` became `net8173`, behind two added output buffers. The direct-port rule
adds exactly one protected net for this graph. Its 4.80–14.47 ns output slew
against 2 ns remains a failure; it needs an explicit parent driver, not an audit
exemption. The original before/after graphs and rejected run remain retained.

This protection is deliberately conservative: some upstream high-fanout nets
cannot be repaired automatically. Their violations remain in the reports; they
require a reviewed parent driver or native recipe change. Protection must not
be removed merely to obtain a clean report. The explicit bounded capture-tree
and SRAM-clock recipes are documented [separately](../native-capture-distribution.md).

Before/after graph files come directly from OpenDB signal pins, independently of
the Verilog writer. Acceptance requires the same complete graph proof used by
mapping: only verified noninverting added buffers, equivalent ordinary-cell
resizing and validated constant ties may differ. Original cells cannot disappear;
protected native partitions and three exclusive SRAM clock drivers must survive.
The original protected-pin snapshot is also checked at every saved checkpoint.

P&R provenance v3 binds all five SRAM and standard-cell libraries, LEFs, routing
assets, audit sources, immutable Tcl snapshots, graph evidence, reports and
accepted mapping receipt. Reading or resuming a checkpoint requires every prior
checkpoint, including placement/global repair proofs and all per-corner reports.
Missing or changed evidence fails before reuse. A failed repair/proof does not
create an accepted checkpoint; its files remain available for diagnosis.

## Completed placement and global-route runs

`build/bounded-pnr-bd-r11` and `build/bounded-pnr-click-r2` complete through global
routing with the candidate runtime. Both repair passes preserve all original
cells under the permitted graph transformations, every exact native signal-pin
connection, and all three exclusive SRAM clock drivers. BD preserves 55,836
native cells/149,285 signal pins; Click preserves 61,309/157,963. No native
input is omitted. The [compact evidence](wire-repair-evidence.json) binds the
accepted run receipts and reports; independent review checked their hashes and
compared the actual native pins before/after repair.

The table counts **slew-violation report rows**, not unique nets. Each entry is
before → after that pass, using the same five cell PVT corners and nominal layer
RC. Global-route repair includes incremental rerouting and fresh parasitics.

| Cell corner | BD placement | BD global route | Click placement | Click global route |
| --- | ---: | ---: | ---: | ---: |
| TT, 25 C, 3.3 V | 4,434 → 917 | 1,003 → 1,003 | 6,060 → 1,513 | 1,610 → 1,613 |
| SS, 125 C, 3.0 V | 29,256 → 5,399 | 9,968 → 9,241 | 32,704 → 7,497 | 11,896 → 11,241 |
| SS, −40 C, 3.0 V | 8,897 → 1,443 | 2,091 → 2,097 | 10,380 → 2,295 | 2,976 → 2,980 |
| FF, 125 C, 3.6 V | 3,099 → 613 | 651 → 655 | 4,017 → 1,104 | 1,194 → 1,197 |
| FF, −40 C, 3.6 V | 1,111 → 183 | 177 → 177 | 1,288 → 298 | 269 → 269 |

Placement starts with up to 15 BD/17 Click capacitance-violation rows. All
post-placement and pre/post-global-route reports have zero capacitance
violations. Slew remains failing: the final maximum reported slews are 13.928 ns
BD and 12.193 ns Click. Several corner row counts increase slightly after global
repair/rerouting; the actual reports are retained without a monotonic-improvement
assumption. These runs establish repair execution and graph preservation, **not
electrical closure or trustworthy small timing margins**.

The placement pass adds 10,347 BD/10,928 Click buffers and resizes 1,437/1,616
ordinary cells. Global-route repair adds another 1,596/1,603 buffers and resizes
233/197 cells. OpenROAD's reported non-filler master area includes SRAM and
physical implementation cells; it is separate from mapped logic-only accounting.

| Reported design area, mm² | BD | Click |
| --- | ---: | ---: |
| Floorplan, before wire repair | 3.792616 | 4.576884 |
| After placement repair | 4.111766 | 4.911619 |
| After real-clock tree construction | 4.122654 | 4.923535 |
| After global-route repair | 4.169888 | 4.972723 |

Wire-repair passes add 0.366384 mm² BD and 0.383923 mm² Click in total; real-clock
tree construction adds another 0.010888/0.011916 mm². These costs are additional
to the [pre-placement repair accounting](../gf180-estimates.md#electrical-repair-area).
No new leakage or physical wake-energy claim follows from these area figures.

## Validation and remaining gates

The P&R/proof unit tests cover changed inputs, missing predecessor repairs,
changed reports/graphs, altered protected cells and incorrect pins. All 32 P&R
tests and two OpenDB graph tests pass, including wrapped-executable changes and
runtime changes during execution. The complete Python suite passes 1,043 tests.
The serial diagnostics r8/r9 retain the stack, full trace and pre-repair database.
They were stopped deliberately and have no accepted place/global checkpoint.
The patched runtime's completed checkpoints and measurements above accept this
execution scope; electrical and asynchronous qualification remain open.

Earlier BD runs remain evidence: r1–r3 stopped at configuration/constraint
bindings; r4 and r5 exposed OpenROAD's inability to buffer protected native
loads. Those failures led to explicit net protection, not a relaxed graph proof.
Resource stops in BD r6 / Click r1 and legacy async endpoint warnings remain
visible in their original logs. The optimization context provides no async timing
coverage. Repaired leaf-stage/Join campaigns provide only their documented local
scope. RF/elapsed launch composition, full reset propagation, mismatch, extracted
min/max RC and physical wake/energy qualification remain open.
