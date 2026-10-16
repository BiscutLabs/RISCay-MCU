# Native Control characterization

Status: **bounded schematic investigation; complete physical timing remains
open**. This follows the merged opt-in [Control load repair](control-electrical-repair.md).
It changes analysis tools only. The separate BD and Click implementations, their
guards, reset behavior and default physical flow are unchanged.

## What is measured

`tools/characterize_gf180_control_native.py` extracts the mapped Control update
stage's native controller and all 315 physical payload storage cells, including
their complete local capture/reset trees. BD retains its three C-element feedback
loops; Click retains its phase-register feedback and native pulse generator.
There are no analysis cuts inside either controller.

The circuit comes from the mapped JSON hierarchy. The extractor independently
checks each adapter's exact cells/connections against the mapping record, pins
the model and parameter specialization for every primitive owner, and checks the
stage's protocol wiring. Empty/cyclic wrappers, changed keeper inversions,
unexplained control loads and missing storage pins reject. Every physical leaf
and all 315 E/CLK pins have source-path-to-SPICE-node witnesses. Twenty distinct
capture nets drive the 315 actual storage cells.

The explicit experiment boundary is the storage D pins, driven by ideal voltage
sources. All D inputs carry one then zero, with subsequent changes during the
occupied interval to check retention after ACK. Each Q and public ACK/offer has
a chosen 0.05 pF load. These are declared experimental loads, not extracted chip
fanout. The data transform, source launch/reuse circuit and full-chip reset
distribution are outside this boundary. Local ACK-minus-capture timing cannot
prove upstream hold safety.

Both BD return orders are exercised, including output ACK returning before the
input request returns. Output ACK only returns after the output request falls.
Click establishes both phase histories naturally from POR. The checker verifies
the boundary stimulus and legal environment ordering, exact capture/handshake
edge histories, settled control levels, every Q snapshot, and Q extrema across
each retained-data window. Click's actual phase DFF D/CLK/Q are also observed.

Delay crossings use 50% of supply; slew uses the pinned Liberty's 30–70%
thresholds. The 1.8 ns pulse floor is a **provisional diagnostic** from the existing
physical targets. It does not replace Liberty-specific high/low pulse, setup,
hold or reset recovery checks.

## Numerical acceptance

The first coarse TT pilots completed functional checks for both variants. They
were insufficient timing evidence: Click's second payload pulse appeared to be
about 1.439 ns, but its apparent 6 ps phase CLK-to-Q came from interpolation
across a roughly 660 ps sample gap. Changing the maximum integration step from
2 ns to 1 ns moved an ACK edge by 0.566 ns and a slew by 0.112 ns. Those results
remain retained as **numerically unresolved**, including BD measurements that
initially had no diagnostic violations.

The maintained checker rejects timing evidence when any observed control
30/50/70% crossing has an integration bracket exceeding 51 ps. Optional numerical
mesh instrumentation adds PWL breakpoints around external events on a node proved
disjoint from the circuit. It has no connection to a native control or storage
pin. It changes simulator sampling only.

`tools/compare_control_native_steps.py` compares matching edge identities,
polarities, slews and derived margins/pulses under timestep refinement. A 50 ps
maximum difference is the pilot comparison gate. Quantities below twice that
resolution remain explicitly unresolved at their scale. Different PVT corners,
stimuli and routed RC need their own checks; a TT agreement cannot qualify them.

## Evidence and remaining work

Pilot and negative-control evidence is retained under:

- `build/control-native-pilot-r1` through `r3`: bounded timeout evidence.
- `build/control-native-pilot-r4`: coarse TT pilots and their matching runner
  snapshot; two BD return orders and one Click phase-pair case.
- `build/control-native-convergence-r1`: the rejected 2 ns/1 ns Click comparison.
- `build/control-native-negative-r1`: actual disconnected BD capture-branch
  mutants. Each return order produces the intended payload-retention and
  retained-window-glitch diagnostics, without an unrelated protocol failure.
- `build/control-native-negative-r2`: actual disconnected Click capture-branch
  mutant. The intended payload failures are separated from the pre-existing
  unresolved sampling and provisional pulse diagnostics.
- `build/control-native-review`: current-checker reassessment of the archived
  coarse pilots; every case is numerically unresolved.
- `build/control-native-mesh-r1`: the 50 ps numerical-mesh pilot reached its
  615-second host timeout (600-second Linux limit) without returning a waveform.
  No refined timing result is accepted, and the finer/full-corner campaign was
  not launched. Its deck, plan, tool identity, runner snapshot and timeout remain.
  This exposed a logging weakness: buffered partial simulator output was lost on
  the host timeout. The runner now streams directly to disk; a focused timeout
  control verifies that partial output survives.

The final full Python suite passes **806 tests**, including **26 focused tests**
after the comparator/logging changes. They cover adapter specialization/feedback, missing
capture leaves, recursive/empty wrappers, unexplained loads, malformed evidence,
phase histories, stimulus, ordering, retention glitches, unresolved sampling,
and refinement identity/diagnostic checks. No RTL changed, so earlier Scala and
strict-export results are not presented as newly run tests.

A fresh independent reviewer found and verified fixes for the missing BD
return order, wrong-specialization/empty-wrapper acceptance, unobserved Click
phase pins, and a refinement comparison that could accept two equally
unresolved inputs. The reviewer independently confirmed the BD mutation's exact
affected lanes and focused test results. Complete physical timing remains open.

The [evidence manifest](control-native-characterization-evidence.json) binds the
maintained sources, original maps, archived runner snapshots, raw pilot and
mutation evidence, timeout, reassessments, final tests and independent review.

The timing investigation is still open. First establish resolved, converged
sampling, then characterize all five pinned corners and input transition bounds.
Bind those results to complete transform/source setup/hold, pulse/reset and
electrical obligations before proceeding to extracted minimum/maximum RC. The
previous unresolved direct STA paths, data-budget failures and remaining
electrical violations are not waived by these harnesses.

Reproduction uses fresh output directories; ngspice and source/PDK hashes are
recorded before and after. Every subprocess has both a Linux-side and host-side
timeout. The default is a bounded TT pilot. A five-corner, two-input-slew campaign
requires explicit `--campaign`; establish numerical gates first:

```powershell
python tools/characterize_gf180_control_native.py <mapped> <fresh-output> --variant click --pilot --mesh-step-ns 0.05
python tools/characterize_gf180_control_native.py <mapped> <fresh-finer-output> --variant click --pilot --mesh-step-ns 0.025
python tools/compare_control_native_steps.py <fresh-output>/results.json <fresh-finer-output>/results.json <fresh-comparison>.json
python -m unittest discover -s tools -p test_control_native_characterization.py
```

Repeat BD with both return orders. Missing evidence, failed controls or unresolved
sampling never imply physical qualification.
