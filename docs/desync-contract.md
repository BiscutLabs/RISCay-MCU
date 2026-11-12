# Generated bundled-data MCU contract

Generate the MCU from the unchanged clocked netlist: no copied RTL, shared fast
oscillator, payload mirrors, transaction owners or ABI changes. Old BD and Click
remain behavioral oracles. The bank map and primitive registry are authoritative;
[the ledger](desync-ledger.md) records measurements and links to historical detail.

## Architecture and reset

The current ten banks are CPU, Fabric, Control, program, RAM, I2C, ADC, time,
power and falling. Rising-edge registers become M/S latch pairs; 42 falling-edge
bits use S/M pairs. The approved CPU exception keeps 591 FFs, captured on master.A;
latch enables use N. Preserve every architectural bit, reset value and lifetime,
including per-register work gating and falling capture's `previous` qualifier.
Slaves keep the original reset. Masters are plain unless reset analysis requires
a defined value; no additional architectural storage is allowed.

Each bank has two semi-decoupled controllers, witnessed predecessor joins and
one matched delay. A/B keepers enforce request-return causality, receiver closure
and same-phase qualification. B responds to actual enable N. CPU joins enforce
rearm. Protect only registered native control, not ordinary logic or storage.

Deep sleep stops power.M through one persistent stop request and a filtered
mutex; stopping never resets a live grant. Controls reset from raw
`resetHold/unsafe_supply`, while architectural POR remains qualified. The
100,000-count qualifier must guarantee at least 5 ms at the fastest recurrence.
Parallel-reset delay units still require reset flushing, distribution, assertion
and release checks. The mutex's 1 FIT/MCU target remains unqualified and its
production binding stays disabled.

| Remaining clock/input | Required obligation |
|---|---|
| LF watchdog/timebase | Independent recovery/time; preserve Gray crossing and skew limits |
| SDA event FF | START frontier and SCL aperture, followed by existing synchronization |
| SRAM CLK | Local port capture; setup/hold, access, high/low pulse limits |
| GPIO/I2C synchronizers | Existing stages as latch pairs; sampling/MTBF; bus activity keeps them live |
| SPI MISO | Source-synchronous sampling and external ADC aperture |

## Work order and digital evidence

1. Generated-chip boot, earliest I2C status, SRAM, sleep/wake, reset and register
   transfers. Reference-suite passes do not count as generated-chip passes.
2. Timed graph recurrence and external deadlines; area-only Fabric/time/power merge.
3. Per-bank STA sizing only after these gates pass. Local SPICE is paused.

The simulation backend transforms each actual ClockedSoc test fixture with the
production generator and preserves its wire-level assertions/deadlines. Registered
control recipes and delay apertures receive behavioral models; ordinary logic is
zero-delay and storage/SRAM uses the real generated implementation. Each run
records bounds, corner, selection and seed. Fixture configurations borrow the
production trial's STA ranges: this is functional stress, not fixture-specific
physical qualification. Random selection is per instance, fixed for that run.
The atomic mutex model makes no metastability claim. Raw reset clamps modeled
lines immediately; physical reset flushing/minimum POR remain open.

Transfer checks compare original D/enable/reset semantics with actual generated
captures, check defined bits even in partly unknown words, and report unexercised
state. Actual N transitions must follow the marked graph; gate qualifiers must
change while their capture root is closed. These checks complement folded
next-state/SRAM equivalence; they are not a complete sequential flow proof.
The testbench's fast-clock-failure switch freezes native progress explicitly,
without stopping LF/POR. Legacy serviceClock activity counters are wall-time
observers; `DESYNC_EVENT_ACTIVITY` counts actual native events.

The five-corner trial graph's slowest modeled recurrence is **358.900 ns** at
SS/125 C/3.0 V (no wires/data delays). Required throughput is
`events/window × cycles/event × worst cycle < window`:

| Stream | Current check and result |
|---|---|
| I2C, 400 kHz | Eight samples/bit require <=312.5 ns; trial demand 2.8712 us exceeds the 2.5 us bit window, despite sampled earliest-status cases passing |
| SPI/ADC | Default pin/scaler work is 173 cycles, about 62.1 us at the trial period, before final drainage; no complete timing bound yet. The accelerated sleep test gets 4 conversions but fails sleep residency |
| LF ticks | Independent time is preserved; finite-lease and stop/wake cases execute. The accelerated test spends 2,939 observer edges awake versus 64 asleep: `BOOT_NOT_SLEEPING` remains a failure |
| Boot | Small valid flash image executes in generated simulation; full-capacity generated boot and worst-case bound remain open |

The slow-model watchdog/loader case also fails `LOADER_COMPLETION_DEADLINE`.
Keep failures; neither assertions nor deadlines may be weakened. See
[build and test](build-and-test.md) for the explicit generated gate.

## Timing and acceptance

Every delay is relative (bank matching), absolute (SRAM/controller aperture,
POR, mutex filtering) or simulation-only. Relative sizing uses same-corner STA,
actual load/slew and 1.2 engineering allowance, not measured mismatch. No RTL
model number or fallback formula may produce a physical count. Trial counts
remain provisional; the production delay policy is empty.

Repair before accepted timing. Use bounded enable trees (<=16 loads/branch,
equal depth), exclusive SRAM drivers and independent sink enumeration. Compose
actual launch/capture, ACK/reopening, falling-latch and work-gate paths. Preserve
keeper feedback; include removed loads in conditional queries. Routed min/max RC,
coupling, reset distribution and mutex qualification remain mandatory. Zero-wire
margins below 100 ps are untrusted.

Reference: **0.5318332992 mm² mapped**, **0.5915383488 mm² repaired + CTS**,
2,977 architectural bits and 0.2041777472 mm² storage. Approved prototype ceilings:
**1.17x mapped**, **5.5% control/join/delay/mutex**, **1.20x repaired + trees**,
**1.00x architectural bits**, **1.25x storage area**. No loosening without approval.
The current trial fits mapped/storage/control limits; repaired comparison and
whole-chip timing acceptance remain open. The eight-bank merge is an area
experiment only. No production or tape-out qualification is claimed.
