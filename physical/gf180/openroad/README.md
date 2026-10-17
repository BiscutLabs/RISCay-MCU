# OpenROAD wire-repair progress backport

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

The candidate passes all 7,631 packaged tests. The upstream no-progress fixture
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
