# Execute Join composition and independent source coverage

Status: **conditional Join-origin setup measurements; whole execute timing remains open**.
This reuses the Control Join template. It adds no RTL, periodic clocks, guards,
timing-policy values or changes to the default mapping/P&R flow.

## Reusable boundary

`tools/control_join_timing.py --target execute` selects the actual core Join and
execute instances through the exported hierarchy. The same binding, controller
contexts, pin pairing, loaded Liberty arcs, slew custody and margin calculations
serve Control and execute. The execute caller supplies only its parent/sink
selection, exact left→state/right→response field mapping, and explicit independent
register-file sources. Measurements remain specific to each loaded instance.

The source stores retain 171 state bits and 33 response bits. Execute captures
278 bits. The two source cones reach 278 and 276 destination lanes respectively;
the union must still cover every dynamic lane. Unknown lanes cannot be waived
or relabelled as constants to make a new caller work.

Destination coverage does **not** establish input coverage. Execute also reads
15 × 32 register-file bits outside the Join. Each bit is bound to its actual
parent register-file output and recorded individually. Every sink input must
belong to a checked Join channel or a declared side source. Constants, duplicate
RF aliases, wrong fields, changed widths and undeclared inputs reject.

All **480 RF bits remain symbolic and uncomposed**. No RF case analysis or
constant substitution removes their paths. Each bank reaches 274 of the 278
destination lanes, overlapping the Join cones. During these measurements RF
values must already be stable and remain stable throughout Join launch and the
execute aperture. Their boundary transition assumption equals the selected
0.02/2 ns input slew; this can affect propagated gate slew. The reports retain
the independent source ledger and its destination reachability, and always set
`whole_stage_setup_established: false`.

The conditional BD already-open/Q-before-close and direct-close/return-ACK
requirements, and Click's real fire/capture/phase CLK-to-Q paths, remain those
of the [Control composition](control-join-timing.md). Both operands and both
Click phases are required. No measured controller numbers are shared.

## Evidence

The original A2b maps at RTL `6aa8033f5978dfde0a00432f82952f7999d93178` are unchanged.
The campaign covers five pinned Liberty corners and 0.02/2 ns input slew in both
variants. All 20 cases resolve, with 30,400 BD and 56,640 Click path rows.

| Minimum across the campaign | BD | Click |
| --- | ---: | ---: |
| Conditional Join-origin setup margin | 47.790 ns | 51.461 ns |
| Permitted Join-input data lag behind request | 18.781 ns | 21.047 ns |

These bounds include actual source storage, output guard, rendezvous and execute
capture. The negative boundary-local allowances in the earlier survey therefore
do not, by themselves, establish a Join-origin setup violation. The original
negative evidence remains valid for its narrower input-boundary interpretation.

Electrical quality remains inadequate: the contexts report **2,510–8,001 BD**
and **2,557–7,767 Click** violation rows. Counts repeat cells across contexts.
The maximum reported path slew reaches 102.1/105.0 ns. These are extrapolated,
electrically unqualified measurements, with no routed RC or mismatch derate.
They cannot authorize either guard shortening or a numeric physical policy.

Actual-arc controls cover period invariance, a late source input, a delayed
capture branch, late offer/rendezvous and shortened offer/request guards. Faults
must move the intended physical members and create a new failure from positive
baseline values where failure is expected. Source-input controls additionally
reject RF permutation, tie-off, duplication, undeclared input and an RF-only
destination lane. All graph rejection controls run against a renamed live
parent with an empty unused unsuffixed sibling.

Fresh independent review caught a name-based lookup in those rejection controls;
the final controls resolve the actual parent for every mutation. The reviewer
found no remaining blocking implementation issue in this conditional scope.
Final test/control counts and sealed hashes are recorded in the
[evidence manifest](execute-join-timing-evidence.json).

Reproduce with configured tools (`RISCAY_PHYSICAL_TOOLS`):

```powershell
python tools/control_join_timing.py `
  build/async-loader-width-finish-r2/candidate-mapped-bd-r1 `
  build/my-execute-join-bd --variant bd --target execute --campaign
python tools/check_control_join_controls.py `
  build/my-execute-join-bd build/my-execute-join-bd-controls
```

Repeat for Click. Fresh output directories are mandatory. Control remains the
default caller; its original per-context paths, numerical results and summaries
are checked for regression. Tools/docs-only work does not claim new Scala or
firmware simulation results.

## Next gates before an RTL timing change

1. Compose the RF source: state publication → register-arrival/selected-bank
   trigger → bank CLK-to-Q → execute transform, against state publication →
   31 ns forwarding guard → Fork → Join → execute capture. Cover all 15 selected
   banks and retain obligations for unselected held banks.
2. Compose elapsed's actual seeded owner and parent admission/data muxes. Its
   modeled **output** guard is 31 ns BD / 32 ns Click; 11 ns is the request guard.
   Measure that lead. BD uses a seeded FIFO/merge/long-hold buffer; Click uses a
   seeded phase-decoupled buffer with distinct input/output phases and startup.
   Distinguish owner-last admission, command-last admission and feedback turns.
3. Repair electrical violations with graph-preservation evidence, then rerun
   these same-corner envelopes. The previous worst execute allowance was at
   FF/125°C/3.6 V with 2 ns input slew, not a slow corner; its reported data-path
   maximum slew was about 45–47 ns.
4. Select any required step/execute request-chain change from the complete
   measured envelope with explicit variation assumptions. Keep elapsed's step
   policy separate from its owner policy. The standalone experimental
   `PhysicalTiming.executeData = 180 ns` is not a supported SoC policy.

Whole execute/elapsed setup, RF/source hold, pending/return/pulse histories,
simultaneous rendezvous, reset distribution and routed qualification remain open.
