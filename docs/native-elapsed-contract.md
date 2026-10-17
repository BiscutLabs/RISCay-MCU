# Native elapsed-time arithmetic

A1b replaces the unrolled elapsed transform with a bounded native feedback loop
in each design's `ConstantScaling.scala`. Functional and strict export checks
pass, with matched area/activity evidence and independent review recorded in
the [area checklist](native-area-reduction.md#a1b-bounded-native-elapsed-loop).
Physical timing remains unqualified. The public millisecond ABI and ADC scaler
are unchanged.

## Arithmetic and ownership

The seeded owner and one four-bit transform retain the active target, unsigned
32-bit tick delta, fractional state, quotient/remainder accumulators, nibble
index and independent external handshake histories. The first turn subtracts
the previous target modulo 2^32 and selects the highest nonzero nibble. Zero
still takes one turn. Every delta, including `0xffffffff`, takes one through
eight arithmetic turns; work never scales with the number of elapsed ticks.

For lane coefficient `us`, the independent specification is
`total = delta * us + oldFraction`, `elapsed = floor(total / 1000) mod 2^32`,
and `fraction = total mod 1000`. The four radix-2 steps reuse constant quotient
and remainder coefficients computed at elaboration. Adding the old fraction
only on the final turn preserves exact rounding over successive publications.
Positive integer, duplicate and large coefficients remain supported.

The owner publishes its completed quotient, fraction and target fields directly;
no separate result payload bank is added. These fields remain held through reply
acceptance. Internal turns do not advance the service-domain consumed count or
`consumedGray`. The unchanged POR-only boundary publishes elapsed values and
its consumed target on actual receipt acceptance. Final Housekeeping publication
still owns the architectural time/lease effects and `consumedGray`. A stale
single-tick reply cannot grant fresh supervisor observation credit. Outstanding
work and crossing return drainage continue to inhibit sleep.

## Independent protocols

The four-phase implementation uses Idle, Run, Reply and Return modes. Reply
waits for reply ACK high. Return withdraws reply REQ, retaining every result
field, and waits for command REQ low, actual external reply REQ low and reply
ACK low before withdrawing command ACK. Source data obeys the library's full
REQ/ACK return hold rule. The idle input bus can change before the next offer.

Click uses Ready and Run modes with a native phase-decoupled seeded owner and
Click stage. Ready admits a new command only when its phase differs from the
accepted command history and the previous reply phase is acknowledged. Run
advances independently. Completion toggles the external reply history once.
Variable internal iteration parity never substitutes for external command or
reply phase. The source may reuse its bus immediately after phase ACK; later
turns use retained fields and mask the unused live command bus.

Two history bits are captured on native owner publication. Four-phase uses
the published owner request, not its transparent latch output. Click uses a
public XOR primitive comparing the owner's request and acknowledgement, so both
phase polarities produce a publication pulse. Existing owner output guards
qualify the retained history data. Neither implementation adds a periodic
clock, a four-phase Click adapter or an extra long delay chain.

## Reset and timing requirements

The owner, transform, history capture and external phase histories are POR-only.
POR aborts arithmetic and any held reply or incomplete return, then reinstalls
zero target/fractions/history. Application watchdog cancellation continues
through the existing service reset coordinator; it does not reset this loop.

The custom history register's digital model requires checks at its actual D,
trigger and Q pins: 100 ps setup/hold, high/low pulse widths and trigger
distribution skew, with every owner publication captured, including Click phase zero.
Standard library stage tests alone do not prove this custom capture aperture.
Tests must include opposing owner/step/publication delay choices, legal pin
distribution, reset overlap and exact-fatal negative controls. The transform's
complete combinational path also needs five-corner measurement against its
unchanged data budget. The physical register must meet its characterized GF180
cell setup/hold, pulse and reset recovery/removal limits across five corners;
100 ps is not a physical cell qualification. Owner-to-history and owner-to-receipt
paths, earliest payload release after ACK, interconnect, actual guard delays and
reset distribution remain separate qualification obligations.

The A1b pre-layout measurements retain a failed whole-transform check in both
variants: the step reaches **141.627808 ns for BD** and **127.252151 ns for Click**
against the unchanged **10 ns** data budget. The prior unrolled implementation
also failed that budget. BD's conservative merge-path check reaches 90.335281 ns
and also fails. A separate proof establishes that all 228 BD initial seed data bits
are literal zero; this explains the absent dynamic seed-data path without
qualifying reset or admission timing. Local adapter propagation/distribution
checks pass within their measured load/slew envelope, which does not qualify the
complete capture path. The retained tables and logs are bound by
`build/async-elapsed-loop/physical-diagnostics-r2.json`, whose status remains
`PHYSICAL_TIMING_OPEN`. No timing budget was increased to obtain a pass.

## Acceptance evidence

The electrical-first correction makes owner and arithmetic-step timing separate
constructor parameters. Its default step request guard is 100 ns in each native
implementation; owner, data, storage, output and acknowledgment models retain
their previous values. Arithmetic and iteration counts are unchanged. The first
200 ns and 120 ns candidates starved BD's existing accelerated maintenance sleep
test; their failure logs are retained. The 100 ns target passes that unchanged
oracle and is still substantially longer than the original 11 ns request model.
It is an implementation target, not a qualified physical envelope.
See [the correction record](reviews/electrical-first-correction.md).

`AsyncScalingSpec` retains independent wide-integer arithmetic, sample, stall
and POR oracles. `AsyncElapsedLoopSpec` adds exact iteration/index counts,
nibble boundaries, full-width wrap, fractional carries, early source reuse,
held replies, independent four-phase returns and POR at every nibble/return.
The composed scaling, sleep, supervisor, firmware, reset and core-reference
checks pass without changing their behavioral expectations.

The acceptance cohort contains 206 distinct ScalaTest cases, 500 Python tests,
367 actual-pin capture cases and 14 arithmetic-control cases. All four strict
exports retain every mandatory generic campaign. The exact-parent mapped
area/leakage/guard costs and all 27 matched wake windows per variant are recorded
in the checklist. Area and work-clock counts are separate observations; neither
is a measured wake-energy or reachable standby-power result. Earlier failed
binding and illegal-stimulus runs remain with their diagnoses. Hash-bound review
and acceptance receipts retain the explicit `PHYSICAL_TIMING_OPEN` limitation.
