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

Required checks: generated-chip per-register flow equivalence; folded
next-state/SRAM-effect proof; unchanged boot, I2C earliest status, SRAM, ADC,
reset, firmware and sleep/wake suites; stop/wake races and POR in flight.
Throughput uses `events/window * worst firings/event * slowest cycle < window`.
I2C remains **400 kHz SCL**, tested against the existing 3.2/20 MHz reference
service points. No desync throughput margin is yet claimed.

## Acceptance boundary

The pinned reference is **0.5318332992 mm² mapped**, **0.5915383488 mm² after
repair/placement/CTS**, 2,977 architectural bits and 0.2041777472 mm² storage.
The user raised mapped area to **1.20x** after checkpoint `291d731`.
Limits are mapped **1.20x**, repaired plus trees **1.20x**, architectural bits
**1.00x**, storage area **1.25x**, and control/join/delay/mutex share **5%**.

Connected preparation is 0.5998603520 mm² before matched lines. A cell-exact
**area-only** ten-line trial is 0.6186512640 mm² (**1.163243x**), with **5.4549%**
control share. Mapped area now fits the approved ceiling, but the separate 5%
control-share limit still fails. Its provisional component-based counts are not
accepted bank timing, and production policy remains empty. Timing investigation
continues; neither budget approval nor diagnostic measurements qualify adoption.

Preparation with enable trees is 0.6562813824 mm², excluding matched lines and
wire RC. Storage remains 0.2512318592 mm²: 2,977 architectural bits, 5,283 physical
FF/latch bits plus 198 control keepers. Periodic sinks are LF 78; SDA adds one
event-clocked FF. The 5,207 native storage/macro pins are independently covered.
The experimental mutex footprint is 0.00098784 mm². Its **1 FIT per MCU** target
still needs a justified reliability model, arbitration rate, variation/noise and
extracted evidence; finite SPICE samples do not qualify it. No whole-chip timing,
flow, throughput or tape-out acceptance is claimed.
