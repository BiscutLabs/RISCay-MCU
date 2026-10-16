# Conditional Control relative-timing pilot

Status: **local state-conditioned paths measured; complete physical timing open**.
This changes analysis tools only. The native BD/Click RTL, delay chains,
simulation timing policies, default mapper and P&R flow are unchanged.

The previous unconditioned screen could not resolve capture/ACK paths through
native feedback. This pilot resolves each of the 315 actual payload capture pins
under explicit legal initial-state assumptions. It measures data and control at
the same Liberty corner, using physical cell setup/hold requirements rather than
interpreting the 10 ns simulation data allowance as a silicon requirement.

## Measurement contract

The experiment uses the reviewed opt-in repaired Control netlists from
`build/control-electrical-repair-r5/{bd,click}`, five pinned GF180 corners, and
0.02/2 ns stage-input slews. It retains all physical storage/capture loads and
uses the existing chosen 0.05 pF stage-output load. There is no wire RC.

Every analysis context has a fresh linked design. The exact native adapters,
specializations and protocol wiring are checked against the mapper record.
Data D and capture E/CLK must belong to the same physical storage instance;
every endpoint transition and min/max row is mandatory. Request paths must
contain the actual request-delay output and each intervening controller owner.
Missing, duplicate, nonfinite or reversed evidence and tool warnings reject.

- **BD request capture:** request rises into an empty slot with B=0, downstream
  ACK=0, and A/ACK keeper prestate zero. Only the reviewed AOI21 A1-to-ZN keeper
  arcs are disabled. Those initial-state cases break the larger controller
  cycle for this event; they are not whole-transaction invariants.
- **Click request capture:** both phase values are analyzed. Only phase inputs
  of the two comparators are conditioned; the phase-register Q/ACK path remains
  live. There is no four-phase conversion.
- **Click pending release:** for each phase, a pending request is held while
  downstream ACK returns to that phase. These release-to-capture rows establish
  path coverage, not a setup margin that incorrectly launches data at ACK.
- **Common capture event:** BD uses actual `long_hold` rising; Click uses actual
  `fire` rising. An analysis clock at that existing driver describes one event.
  All acceptance arithmetic uses propagation delays, never periodic slack.
  A 1,000-to-2,000 ns period control must leave the entire result unchanged.
- **Click ACK:** its path includes fire-to-phase-CLK distribution, actual
  CLK-to-Q, phase output padding and the ACK guard. Exact CLK/Q adjacency and an
  independent delay-sum check prevent accidentally omitting the sequential arc.

The event driver remains electrically connected. OpenSTA ignores
`set_clock_transition` for this propagated internal event; the pilot therefore
does not use it. It records actual rising event-slew bounds in every context
and requires the common-event bounds to cover request, release and ACK bounds.
The 2 fs comparison tolerance covers six-decimal-ns property printing only;
it is not a mismatch allowance. Existing cell/load violations remain visible.

For each lane, the reported quantities are:

```
maximum permitted input-data lag = earliest request-to-capture
                                  - latest input-to-D - cell setup
zero-reuse hold margin = earliest event-to-ACK + earliest input-to-D
                        - latest event-to-capture - cell hold
ACK ordering margin = earliest event-to-ACK - latest event-to-capture
```

Setup/hold use conservative maxima across both data-polarity tables of that
corner's actual storage cell. The input-data lag is an allowed boundary skew;
it is **not measured source-to-capture setup slack**. The hold expression assumes
the retained source cannot change the stage input before ACK and assigns zero
additional source-reuse delay. It does not measure the upstream release circuit.
Backpressure cannot create artificial hold credit because both hold branches
start at the same actual capture event.

## Results and controls

The five-corner, two-slew campaign measures 69,380 local rows: 25,220 BD and
44,160 Click, including Click's two release-triggered capture cases. All required
rows resolve. The smallest conditional values across the cohort are:

| Quantity | BD | Click |
| --- | ---: | ---: |
| Permitted input-data lag | 10.314 ns | 12.881 ns |
| Zero-reuse hold margin | 1.871 ns | 53.551 ns |
| ACK after actual capture | 1.663 ns | 53.398 ns |

These are diagnostic values under the stated assumptions, without mismatch
derating. They do not authorize shorter guards. The earlier 10 ns absolute
data-budget failures and electrical failures remain in their original evidence.

Negative controls annotate actual mapped arcs with SDF, leaving circuit
connections intact: shorten the request DLYD chain, remove ACK-path delay, or
delay one actual 16-pin capture branch. Each requires a positive baseline and
measured movement in the intended lane/phase margins. A tool error or an
already-failing baseline cannot count. The late-capture control must identify
exactly that branch's 16 BD lanes / 32 Click lane-phase pairs. Independent
Python controls reject missing paths, wrong phases/endpoints, skipped request
guards, missing CLK-to-Q, missing slew evidence and mismatched reference slews.

The final Python suite passes **829 tests**, including 23 focused relative-timing
tests. The final mapped controls detect negative request/data allowance in 312
BD lanes / 623 Click lane-phase pairs, early ACK in all 315 / 630 pairs, and late
capture in exactly 16 / 32 pairs. Both period-invariance checks are identical.
No Scala/Icarus regression is relabeled as newly run: this item changes no RTL
or simulation timing policy.

## What remains open

1. Compose the actual Join operand-storage launch/Q and offer/rendezvous paths
   with the local request/data paths. The current 655 input ports are a boundary,
   not 655 measured simultaneous upstream launches.
2. Complete BD pending admission and both independent return orders, including
   the long-hold fork. A B-falling pilot still returned 630 missing paths; that
   failed attempt is retained and grants no coverage.
3. Establish Click feedback pulse widths and phase self-feedback hold; the
   previous uncut SPICE harness still lacks accepted refined timing evidence.
4. Repair remaining electrical violations, establish local variation/derating,
   and include actual loads, min/max extracted RC and complete reset envelopes.
5. Parameterize Control's physical timing policy separately from simulation,
   then size its matched guard using the completed source/capture envelope.
   Classify genuine fixed-time waits separately before changing guard mapping.

No silicon timing, total power, area reduction or guard-shortening claim follows
from this pilot. It adds analysis clocks only; it adds no clocked hardware.

Reproduction:

```powershell
python tools/control_relative_timing.py <original-map> <reviewed-repair> <fresh-output> --variant bd --campaign
python tools/check_control_relative_controls.py <fresh-output> <reviewed-repair>/netlist.v <fresh-controls>
python -m unittest discover -s tools -p test_control_relative_timing.py
```

Repeat for `click`. Omitting `--campaign` runs one nominal-corner pilot first.
The [evidence manifest](control-relative-timing-evidence.json) binds final tools, plans, raw logs, results, tests and
independent review. Earlier parser, SDF and unresolved BD experiments remain
under `build/control-relative-*`; none is relabeled as a successful final run.
Final campaigns are `build/control-relative-corners-r3/{bd,click}` and final
fault controls are `build/control-relative-controls-r3/{bd,click}`.
