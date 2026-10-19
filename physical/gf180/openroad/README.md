# OpenROAD runtime patches

## Regional placement accounting

`region-blockage.patch` fixes the 26Q2 GPL placement-region accounting used by
the BD hierarchy experiment. The original code builds a full-core site grid
for every group, then counts every blocked site against each region's area.
The MCU's first bounded run consequently charged 0.828853 mm² of obstruction
to every region, reported negative utilization and diverged with `GPL-0305`.

The patch clips dummy obstacles to the current region, includes overlapping
fixed cells regardless of movable group membership, counts their intersection
area, and respects actual row holes in grouped regions. Fixed sites overwrite
blocked sites before dummy construction, avoiding double counting. It does not
delete physical keep-outs or change circuit graphs. Our generated regions have
one rectangle each; this does not add support for nonrectangular region unions.

Correction is enabled consistently for the whole block only when every
region-attached group is `PHYSICAL_CLUSTER` with one rectangle, and every row
has the same horizontal site, spacing and grid phase. A bounded MCU run requires
the `MODULE_REGION_ACCOUNTING corrected-uniform-physical` diagnostic. Other
layouts retain upstream accounting. An earlier unrestricted version changed
the mixed-row UPF regression and stranded an ungrouped resizer buffer; that
failed evidence is retained. This scoped patch neither fixes power-domain
ownership nor qualifies the future always-on power island. The UPF test and
its expected results remain unchanged.

`check-region-blockage.py` compares the old and candidate tools on unchanged
upstream fixture data: outside and partially intersecting blockages, a fixed
cell wholly/partly inside a region, overlapping fixed/blockage geometry, and
ordinary top-level and unchanged power-domain accounting. Its receipt records
the tools and fixture.
These are initialization controls; full-chip convergence and final geometry
are separate checks in [the floorplan experiment](../../../docs/hierarchical-floorplan.md).

## Detailed-placement search origin

`dpl-search-origin.patch` clamps the diamond-search seed to its already clipped
search rectangle. A fractional fence corner can otherwise round outside both
axes; none of its four neighbours is in bounds, so the search cannot reach any
legal site even with a large displacement allowance. The patch does not change
the rectangle, site occupancy, group membership or full-cell placement checks.
An empty rectangle returns failure.

`check-dpl-search.py OLD NEW SOURCE OUTPUT` exercises the upstream single-buffer
fixture with an unaligned corner, an ordinary in-bounds start and a completely
occupied one-cell region. The old corner must fail, the new one must legalize,
the in-bounds placements must match, and both tools must reject the full region.
Every successful result also passes `check_placement` and a full-bbox fence check.

`dpl-search-golden.patch` updates only the upstream `fence01` placement and
stdout snapshots. Tcl/Python output matches; all ten cells independently pass
row, orientation, fence and non-overlap checks. Five placements change, with
connectivity and masters unchanged. Total displacement improves 15.29→9.12 µm
and maximum displacement 4.63→3.23 µm; HPWL increases 85.7→89.9 µm. No legality
assertion or HPWL threshold is changed. Full package results for the combined
candidate are recorded separately from the earlier wire-progress-only build.

The combined scoped candidate passed **all 7,631 packaged tests**
(`build/hierarchical-floorplan/openroad-region-build-r5.log`), plus the paired
regional-accounting and legalizer controls in `region-controls-r5` and
`dpl-controls-r5`. The matched P&R runs use the exact tested build executable,
SHA-256 `20abaf17173bc8be06b658179920f739103279e54105b3c165dceab4c8ba00a1`.
The installed package is `/nix/store/6hr4lrhg5bc173mfbrxm2plv5pjgg847-openroad-26Q2`;
its installation relink is distinct from the retained tested binary.

## Wire-repair progress backport

The pinned February 2026 OpenROAD resizer repeatedly inserts buffers at one
location on the MCU's placed graph. A live stack trace locates the loop in
`RepairDesign::repairNetWire`. The retained level-3 trace repeats a 117.6 um
remaining wire, zero split distance and 0.021 pF load against a derived 0.003 pF
limit. This is ordinary AOI222-to-OAI22 logic, not a protected native tree.

`repair-progress.patch` backports only the upstream progress check from
[191a654f](https://github.com/The-OpenROAD-Project/OpenROAD/commit/191a654f8a1a80abb91fa437d3a849f4649460c4)
to 26Q2. It incorporates the preceding
[two-iteration check](https://github.com/The-OpenROAD-Project/OpenROAD/commit/d9b131d64ee6899b81eb2dce7e4991d732d5f5ef)
and its post-writeback placement. The diagnostic's newer
`resizer_->slew_shape_factor_` name is translated to the older
`(*slew_rc_factor_)`; the progress logic is unchanged. One insertion may reduce
load even without advancing along the wire. Two consecutive non-improving
insertions stop that segment, including sub-DBU advances. `RSZ-0170` reports the
unrepaired segment. No electrical limit or timing constraint is relaxed.

The code is derived from OpenROAD, Copyright the OpenROAD Authors, under its
BSD 3-Clause license: https://github.com/The-OpenROAD-Project/OpenROAD/blob/26Q2/LICENSE.

Build the candidate with `nix-build physical/gf180/openroad --no-out-link --cores 8`.
The recipe pins nixpkgs and retains its build/test settings and dependency
patches. It produces 26Q2 plus this narrowly scoped backport; it is not a claim
that all newer OpenROAD fixes are included. The unmodified 26Q2 tag also lacks
the progress check.

Use the resulting `bin/openroad` through `gf180_pnr.py --openroad ...` to change
P&R only. Keep the mapper's existing tool configuration and repair receipts.
P&R hashes both launcher and wrapped executable, the tool configuration, and
this recipe/patch. Changed runtime bytes invalidate checkpoint reuse. The
default configured executable is not silently replaced.

The wire-progress-only candidate passed all 7,631 packaged tests. The upstream no-progress fixture
times out after 30 seconds on unmodified 26Q2; this candidate completes it while
retaining its electrical violations. The ordinary `repair_slew10` control
completes without residual violations. A separate two-buffer control reduces a
26.87 fF input load below its unchanged 3 fF limit through two useful zero-distance
insertions, proving the progress check does not reject that case. See the
[hashed evidence](../../../docs/reviews/openroad-progress-evidence.json).

The actual MCU repair now terminates. Its first completed attempt exposed an
output-port buffering change at one protected native pin, rejected by the
unchanged connectivity audit. Full checkpoint results are tracked in the
[wire-repair review](../../../docs/reviews/wire-electrical-repair.md).
`RSZ-0170` plus a completed run is safe termination, not electrical closure.
Native cell and graph proofs, all five-corner reports and original violation
evidence remain mandatory.

Upstream follow-through (2026-10-17): the progress fix was already merged in
[OpenROAD #10514](https://github.com/The-OpenROAD-Project/OpenROAD/pull/10514),
with the sub-DBU correction in
[#11106](https://github.com/The-OpenROAD-Project/OpenROAD/pull/11106).
We sent [downstream validation evidence](https://github.com/The-OpenROAD-Project/OpenROAD/pull/10514#issuecomment-6235806466)
to the original PR, including the preserved timeout, useful-buffer controls and
packaged test results. This is an upstream backport and integration report,
not a new MCU-authored fix. Our controls do not independently isolate the
fractional-DBU case covered by the later upstream correction.
