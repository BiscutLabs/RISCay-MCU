# Native capture and SRAM clock distribution

The GF180 binding gives each SRAM macro an exclusive parent-side clock buffer.
It also expands native storage capture/reset trees with **at most 16 loads per
branch**, including intermediate branches. This changes physical buffer recipes,
not the native protocol, storage ownership or RTL clocks. Native leaves remain
protected during synthesis repair. The full graph proof rejects changed storage,
polarity, connectivity, constants or logical behavior.

The three macro buffers initially use `buf_16`; ordinary electrical repair selects
`buf_12` for each in the accepted maps. The final graph validator requires three
distinct immediate noninverting drivers, each driving exactly one macro CLK.
All address, data, CEN and write controls retain their original graph. This is
still a service-clocked SRAM boundary, not the experimental self-timed macro clock.

## Native primitive contract

Event/phase-register capture trees are noninverting; ClosingLatch closure trees
are inverting. Reset trees are inverting. Every leaf has equal buffer depth,
and the checker rejects excess fanout, cycles, wrong polarity, shared or missing
drivers, and unexpected nonbuffer cells. Existing small-tree recipes remain
unchanged; wide trees gain balanced intermediate branches. A topology proof does
not establish a delay or slew bound.

The unchanged physical recipe budgets are **2.5 ns for Event/PhaseRegister** and
**4 ns for ClosingLatch**. Both root-to-latest-leaf propagation and conservative
earliest-to-latest spread must fit the applicable budget. Full timing must also
include the upstream root driver, pulse width, storage setup/hold, reset, ACK
ordering, mismatch and wire RC. A native request remains the capture event;
analysis clocks add no hardware clock or periodic storage.

## Historical PR9 measurements: loaded, zero-wire

`measure_capture_distribution.py` measures the complete accepted repaired netlist,
with actual loads and retained native leaf pins. It covers all 15 RV32E register
banks, all four frame banks, I2C publication stores and every other storage object
of at least 256 bits: **33 trees per variant**. Both transition polarities, every
leaf, min/max arrivals, five pinned PVT corners and 0.02/2 ns root slews are
required. All four root slew annotations are read back. Missing paths, diagnostics,
unexpected path cells, reversed bounds or incomplete coverage reject the run.

| Maximum over the measured cases, ns | BD propagation | BD spread | Click propagation | Click spread |
|---|---:|---:|---:|---:|
| Register-file banks | 1.692668 | 0.000000 | 1.692668 | 0.000000 |
| Frame banks | 3.734330 | 0.696061 | 2.500529 | 0.328016 |
| I2C publication stores | 2.500529 | 0.328016 | 2.500529 | 0.328016 |

**The PR9 baseline did not pass every budget.** One BD row (I2C frame publication) and five
Click rows (the same publication and four frame banks) reach 2.5005290768 ns
against the 2.5 ns limit. Three further Click rows reach 2.5248165384 ns
(Control Join right), 2.5491042221 ns (Housekeeping update) and 2.5733916837 ns
(Supervisor Join right). All nine failures occur on the falling transition at
SS / 125°C / 3.0 V with 2 ns input slew. Even the 0.529 ps excess is retained,
not rounded away. Zero register-file spread reflects identical loaded branches with
zero wire RC; it is not a routed skew claim. The table is conditional on the
specified root slew and excludes upstream driver delay. It neither closes the
capture contract nor authorizes shortening guards.

Evidence: `build/bounded-distribution-{bd,click}-r2` and
`build/bounded-capture-{bd,click}-r2`. Each capture campaign contains 660 tree/edge
rows and retains all leaf paths. The actual-arc controls change one final frame
branch to 100 ns: exactly 16 leaves / 64 edge-and-bound rows change, while all
other paths remain unchanged and the selected tree fails its budget. Doubling
the analysis period changes no measured row. The Click controls are in
`build/bounded-capture-click-controls-r3`; earlier SDF-escaping and numerical
precision failures remain retained. No parser tolerance or budget was relaxed. Controls require the exact baseline
mapping and tool configuration by resolved path and hash. The four focused
checker tests and independent review pass; see the
[compact evidence manifest](reviews/bounded-distribution-evidence.json).

Reproduce with the configured physical tools:

```text
python tools/measure_capture_distribution.py <accepted-mapping> <new-output>
python tools/check_capture_distribution_controls.py <accepted-mapping> <baseline> <new-output>
```

The mapping changes increase repaired logic area by 0.006757 mm² BD and
0.006357 mm² Click relative to the previous electrical-first maps. Complete
before/after totals, including three SRAM drivers and all writer-workaround
buffers, are in [the area report](gf180-estimates.md#electrical-repair-area).
Slew limits, post-placement/routing repair, reset distribution and the complete
capture/ACK envelopes remain acceptance gates.

## Capture-driver correction after PR9

The revised binding changes only the capture root and intermediate trunks of
EventRegisters wider than 256 bits from `buf_8` to `buf_12`. Final `buf_4` leaves,
16-load branching, storage, cell names/order and every reset connection stay
unchanged. ClosingLatch, PhaseRegister and data-allowance recipes are unchanged.
Frozen complete-recipe hashes and explicit capture-branch checks reject changes
outside that scope or a partially upgraded wide tree.

Fresh repaired maps measure all 33 trees and every leaf at both input slews,
both edges and all five corners: **660 cases per variant, zero budget failures**.
The previous nine failing rows remain in the historical evidence above.

| New maximum propagation, ns | BD | Click |
| --- | ---: | ---: |
| EventRegister trees (2.5 ns budget) | 2.416549 | 2.474408 |
| ClosingLatch trees (4 ns budget) | 3.840845 | none |

The smallest local budget margin is 83.45 ps BD and 25.59 ps Click. This is a
loaded, zero-wire result at the specified root slews, **not routed capture closure**.
No budget or parser tolerance changed. Actual wire load, mismatch, reset,
upstream root slew, pulse width and complete capture/ACK ordering still need
qualification. In particular, stronger root drivers increase upstream input
capacitance; passing the local tree cannot waive that path.

The selected standard-stage and Control Join reruns do not compose every
resized owner's handshake. Both changed BD owners are custom I2C publication
stores (`receive_all` and `frame_payload`). In Click, the selected campaigns
directly cover four changed stage payloads and both Control Join operands;
custom publication/frame banks, three state FIFOs and the Housekeeping and
Supervisor Join operands retain separate launch/capture/ACK obligations.
Using the whole loaded graph preserves their loads, not proof of those
unmeasured sequences.

Repaired standard-cell area increases by 0.0001580544 mm² BD and
0.0014224896 mm² Click against the prior bounded-distribution maps. Every added
cell and resize remains in the report; SRAM area is unchanged. Evidence is
`build/capture-drive-{bd,click}-r1`, `build/capture-drive-{bd,click}-timing-r1`
and `build/capture-drive-{bd,click}-area-r1.json`. The existing physical test
suite passes five tests. The fresh repaired maps pass all 160 selected
standard-stage cases (70 per variant plus 20 additional wide Click stage cases)
and all 20 Control Join cases with positive conditional margins. These reruns
retain the complete loaded graph, including the increased driver input
capacitance, with the custom-owner scope gaps listed above.

Both actual-arc control campaigns pass: period changes move zero paths; a
100 ns final-branch mutation moves exactly 16 leaves / 64 min/max-edge rows
and fails the unchanged budget. Four distribution controls and fourteen
mapping/monitor tests pass. The [compact evidence](reviews/capture-drive-evidence.json)
binds the maps, measurements, controls, upstream reruns and area reports.
