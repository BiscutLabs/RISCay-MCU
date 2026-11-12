# Generated bundled-data MCU contract

The clocked RTL is the sole source. Generate ten four-phase banks from its
normalized netlist; no copied RTL, shared fast oscillator, payload copies,
transaction owners or ABI changes. Old BD and Click remain behavioral oracles.
The bank map and primitive registry are authoritative; history and measurements
are in [the ledger](desync-ledger.md).

## Storage and ownership

Banks are CPU, Fabric, Control, program, RAM, I2C, ADC, time, power and falling.
Ordinary rising-edge registers become M/S latch pairs. The 42 falling-edge bits
use S/M pairs. The approved CPU exception retains 591 FFs, captured on master.A;
latch enables use N. Work gating remains per register, including mixed-lifetime
power state. Falling captures use the existing `previous` qualifier.

Preserve every architectural bit, reset value and lifetime. Slaves retain the
original reset; masters remain plain except where reset analysis requires a
defined value. Both halves retain independent application/wake resets. Nine
first-sample GPIO/SCL/SDA masters keep POR values. No extra data state is allowed.
Actual generic Q pins and SRAM inputs define ideal-cycle equivalence coverage;
ownership aliases alone are insufficient.

## Controllers, boundaries and reset

Each bank has two semi-decoupled controllers, witnessed predecessor joins and
one matched delay. Existing A/B keepers implement request-return causality,
one-sided receiver closure and same-phase qualification. B responds to the
actual enable N. The approved CPU readiness/publication joins enforce rearm.
The C-element candidate is `Q_next = ab + Q(a+b)`, with one feedback input.
Protection covers native control cells, never ordinary data or storage.

The marked graph and assembled event replay screen ordering and stop drainage.
They do not prove physical leaf timing, pulse widths or whole-chip flow
equivalence. Mixed-edge transparent paths must include both falling latches,
their data/enable arrivals and the `previous` input of the enable AND.
For the affected M banks, the joined power/program/RAM S requests supply a
common launch frontier for the existing delay; no additional controller is
needed. This causal argument still needs numerical timing closure.

Deep sleep stops the graph at power.M through one persistent stop request and
one filtered mutex. Operational stop never resets a live grant. Controls reset
from raw `resetHold/unsafe_supply`; using qualified POR would deadlock the
power bank that advances the qualifier. Architectural POR remains qualified.
The 100,000-count qualifier must provide at least **5 ms** at the fastest
measured recurrence, including initialization and reset distribution.

The experimental mixed NAND4/MUX delay resets every unit in parallel. Prove
complete flushing before controller release, distributed reset skew, minimum
assertion, and the earliest subsequent request. Its counted recipe remains
unavailable as a production binding.

| Remaining clock/input | Obligation |
|---|---|
| LF watchdog/timebase | Independent time/recovery; preserve Gray crossing and skew limits |
| SDA event FF | Preserve START frontier and SCL aperture; synchronize through existing stages |
| SRAM CLK | Local port control; preserve launch/access order, setup/hold, access and pulse limits |
| GPIO/I2C synchronizers | Original stages as latch pairs; bound sampling interval and MTBF; active bus keeps sampling live |
| SPI MISO | Preserve source-synchronous sampling and the external ADC aperture |

## Timing and verification

Size relative bank delays from same-corner STA with actual loads/slews and
**1.2**, the user-specified engineering allowance, not measured mismatch.
No RTL delay constant or fallback formula supplies a count. Absolute obligations
are SRAM and controller/latch pulse/aperture limits, POR hold and mutex filtering.
Simulation bounds must come from measured bank envelopes. Production sizing
fails closed while those envelopes are incomplete.

Repair electrical violations before accepting timing. Native outputs have
parent drivers; enable trees have at most 16 loads per branch, equal depth and
exclusive final SRAM drivers. Independently enumerate every actual sink;
excluding only LF and SDA must leave exactly the reported native inventory.
Keeper feedback stays intact. Routed min/max RC, coupling and reset distribution
remain mandatory; zero-wire margins below 100 ps are untrusted.

Conditional primitive queries retain removed feedback capacitance. The data-only
bank view cuts every storage Q/D frontier and restores all removed input loads.
Equal zero arrival and required times give pure combinational extrema at each
sampled Q slew, independent of clock-tree skew and analysis period. The ordinary
graph and every frontier/load are audited. These finite samples are not a
continuous slew envelope. Compose closing-edge/setup corrections explicitly and
propagate transparent D-to-Q slew through downstream logic. The original
worst-slack bank samples remain diagnostic; neither view alone closes setup/hold.

Direct latch handoff hold starts at the receiver's actual A rise. Propagate that
same event through its closing tree and the sender's ACK/reopening tree, comparing
each physical Q-to-D pair with its loaded E-to-Q and hold arcs. Source B required
ACK low before publication, so this rising ACK belongs to the current cycle.
I2C M-to-S passes this sampled conditional STA check with a 1.2 late derate.
Fixed keeper-feedback inputs do not establish a minimum reopening bound:
real feedback can reinforce the transition. Physical hold qualification needs
a full-feedback minimum-transition envelope. The direct-handoff schematic check
retains the actual controller, enable/ACK trees and every paired latch; source D
is the timing frontier, with its removed load restored. Both data polarities must
reuse the source while every receiver retains the old value. All enable and
A/B/N return edges are checked across the complete retention window. External
omitted sinks remain lumped pin capacitances. Finite PVT/slew samples and injected
capture-skew failures do not establish continuous, mismatch or routed bounds.
Initialization, minimum pulses, reverse handoffs and routed RC remain separate.
Lengthening a primary request delay does not repair this immediate return path.

Work-gate return checks start at the actual target A transition, preserving the
qualifier owner's complete ACK join and closed-input paths, feedback, latch and
trees. Normal S gates and falling.M close from A rising; CPU capture closes from
master.A falling, including the real A-to-N inverter in its closure dependency.
Gate clock must fall before its retained qualifier changes, without a new output
pulse. Independently enumerate every storage clock; only traced LF/SDA roots are
excluded. This return check does not establish qualifier setup before opening,
clock pulse widths, reset behavior or a continuous/mismatch/routed timing bound.
Conditional opening checks retain the target's feedback and use the qualifier
owner's actual A transition as the common frontier. D arrives near the Liberty
setup aperture; final D/E waveforms must satisfy it before checking qualifier
settling against gate opening. Vary D and frontier slew independently. This
measures a tested arrival requirement, not the latest safe arrival. The upstream
`enabled`/`previous` latch links, demand logic and data retention still need
composition; an unrelated whole-bank maximum cannot replace those exact paths.

Required checks: generated-chip per-register flow equivalence; folded
next-state/SRAM-effect proof; unchanged boot, I2C earliest status, SRAM, ADC,
reset, firmware and sleep/wake suites; stop/wake races and POR in flight.
Throughput uses `events/window * worst firings/event * slowest cycle < window`.
I2C remains **400 kHz SCL**, tested against the existing 3.2/20 MHz reference
service points. No desync throughput margin is yet claimed.

## Acceptance boundary

The pinned reference is **0.5318332992 mm² mapped**, **0.5915383488 mm² after
repair/placement/CTS**, 2,977 architectural bits and 0.2041777472 mm² storage.
After `b2cac0f`, the user approved prototype ceilings of **1.17x mapped** and
**5.5% control/join/delay/mutex share**, superseding 1.20x and 5% respectively.
Unchanged limits are repaired plus trees **1.20x**, architectural bits **1.00x**
and storage area **1.25x**. This approval does not qualify production adoption.

Current inventories and area-only trials are in the ledger. The trial fits
the mapped/storage/control budgets; the repaired-plus-trees comparison remains
unavailable. Provisional counts are not
accepted timing; production delay policy remains empty. Neither budget approval
nor diagnostic measurements qualify adoption.

The experimental mutex footprint is 0.00098784 mm². Its **1 FIT per MCU** target
still needs a justified reliability model, arbitration rate, variation/noise and
extracted evidence; finite SPICE samples do not qualify it. No whole-chip timing,
flow, throughput or tape-out acceptance is claimed.
