# Passive whole-transform allowances

The MCU opts into chisel-async's public `PassiveDataAllowance` model for native
payload paths. The simulation view retains the declared inertial propagation
allowance, including unknown values. The physical view is `q = a`: no reset gate,
per-bit buffer, clock or storage. Handshake control and capture storage retain
their existing resets and protocol. BD remains latch-based; Click remains native
two-phase event-register logic.

The allowance is an annotation for the complete upstream transform. Its digital
nanoseconds are not a physical delay target. Setup measures the actual transform
against the earliest capture leaf, and hold uses the latest capture and the real
source release. Any failing minimum path needs local hold repair. Unqualified
routed RC, variation and reset distribution remain item 17 obligations.

## Complete invalid-data inventory

The matched parent `2f5aa54` contains **110 BD allowances / 12,307 lanes** and
**124 Click allowances / 10,834 lanes**. The earlier number 104 was historical;
it is not an adoption limit. The exact `data_delay` ID accounts for 96 instances
in each variant. BD also has three suffixed data paths and eleven initial-token
literal muxes; Click has 28 suffixed phase/data paths. The two SRAM prepare
stage removals are recorded separately, rather than counted as passive adoption.

`tools/native_allowance_audit.py` traverses every actual parent-mask output in
the mapped graph. Every path terminates at native `ClosingLatch.d` or
`EventRegister.d`, possibly through ordinary combinational muxes or another
allowance. There are no periodic D, capture-enable, handshake-control, reset,
SRAM-pin or functional top-output consumers. Every row records width, fanout,
actual protected storage leaf pins and their capture/reset owners.

The initial-token muxes are explicitly included. Their literals may be nonzero
while POR is asserted; they feed only the initialized FIFO's merge data path.
The merge admits the literal token with its native request, and reset remains
on the actual payload storage. No new mask is required on these intermediate D
paths. The separate source-start/request state continues to own validity.

The candidate is checked independently before mapping by
`audit_elaborated(database, manifest)`, integrated with the actual emitted RDC
graph. Native primitives remain black boxes at this point, so the new allowance
`a` and `q` remain distinct. This avoids confusing the source's pre-existing
control fanout with a new invalid-data escape after physical aliasing merges the
nets. Exact typed native cells are retained before cleanup, matching the physical
mapper's protected inventory; otherwise zero-information credit payload chains
would disappear from this audit graph while surviving in silicon. Metadata-only
markers are excluded from that retention. All ordinary combinational cells are traversed; only declared native
storage D pins discharge the check. The full candidate inventory is reconciled
against the parent, with explicit removed-stage IDs.

The emitted audit also binds each capture lane to its original allowance lanes.
When physical aliasing folds a literal path to a tie, the binding requires an
unconditional constant proof for that exact capture lane and polarity. The
proof follows only passive aliases and supported combinational truth functions;
all runtime inputs, reset/valid controls and storage outputs remain unconstrained.
Unknown or unsupported cones cannot justify a tie. Equal global zero/one nets
are never followed to unrelated storage, and a dynamic lane tied to a constant
fails the binding check.

## Verification gates

- Library tests cover the unmasked primitive, typed payloads, seeded storage,
  protocol stalls/reset and both native stage families. Legacy resettable policy
  remains available in the library; the MCU's digital owner policies opt in.
- The MCU checker keeps exact data-source, width, model and packed-layout checks.
  Only independently named data paths admit the new primitive. No control gate
  is normalized into an allowance; no periodic sink or CDC path is exempted.
- `tools/test_native_allowance_audit.py` exercises capture-only paths and rejects
  control, reset, periodic storage, unknown cells and functional-output escapes.
- `tools/check_native_allowance_controls.py` applies three structural negative
  controls to each complete emitted SoC graph: an actual native capture pin,
  native reset pin and periodic D pin driven from an invalid allowance output.
  These are structural controls, not simulated timing faults.
- Affected native owner, seeded-loop, frame/reset, sleep/firmware and core tests,
  all four strict SoC exports, matched mapping/repair and local max/min timing
  establish the adoption evidence. The area ledger owns the final measured
  costs. Passing the fanout audit alone is not setup/hold or physical signoff.

Current parent fanout receipts are under
`build/passive-adoption/{bd,click}-parent-fanout.json`. Candidate evidence and
acceptance status belong in the migration checklist and area ledger; this
contract does not turn a pending run into a pass.

## Custom feedback hold screen

The emitted source inventory separately identifies custom captures whose data
can change from the same native event that captures it. These paths cannot rely
on a retained-source argument alone. The current graphs contain four such BD
banks and 24 Click banks; the larger set of different-event, retained-source
paths keeps its explicit ownership and eventual physical release obligations.

`passive_source_inventory.py` re-runs the emitted fanout audit and binds its
source files, graph and contract. `passive_feedback_hold.py` binds every eligible
source Q and destination D to the preserved physical flip-flop and actual native
trigger root on the accepted repaired graph. Reset-to-one lanes use their real
settable flip-flop Liberty model. The query is a genuine minimum Liberty hold
check, including CLK-to-Q and both propagated capture trees, for every queried
D lane and both data polarities. It does not replace hold with a datapath-only
constraint, omit a capture branch, or borrow delay from a removed allowance.

The screen samples the actual loaded root driver's transition-table knots at
each corner, plus a split early-launch/late-capture context. It reports the exact
finite sample set; it does not infer continuous mismatch closure between samples.
The complete eligible combinational cone, including alternate paths, must remain
inside its Liberty load/slew tables. Structural reachability follows every actual
combinational input; a missing timing arc fails rather than proving isolation.
Unreachable lanes require an explicit graph proof. A maximum-hold-table diagnostic
on the selected path is not an all-path bound and cannot replace the genuine
minimum hold result.

This is a local, zero-wire-RC adoption screen. Different-event source release,
reset distribution, correlated variation and extracted min/max RC remain named
item-17 obligations. The independent unit controls include omitted endpoints,
wrong clocks, missing alternate arcs, table extrapolation and reset-cell polarity.

To reproduce the screen, use a fresh output directory and the physical-tool
configuration recorded by the accepted mapping receipt:

```text
python tools/passive_feedback_hold.py --mapping build/area-adoption/map-bd-r3 --export build/area-adoption/physical-r2/bd --output build/feedback-bd-recheck --campaign
```

Repeat with the Click mapping/export. Omitting `--campaign` runs only one
corner; selecting `--group` is a partial diagnostic, not a complete receipt.
The command revalidates the emitted source inventory and physical bindings
before querying. `python -m unittest discover -s tools -p test_passive_feedback_hold.py`
runs the parser, reachability and coverage controls without a physical campaign.
