# Desynchronized MCU — phase 0

The implementation target is a copy of `designs/clocked`, using the same
flip-flops, SRAMs, ABI, reset semantics and state machines. Old BD and Click are
frozen behavioral oracles. No generator RTL has been added yet.

## Regions and state

Phase 1 has one self-timed fast region. A matched-delay loop supplies the service
clock and the existing falling-edge work gate. The independent LF watchdog and
timebase remain periodic. The generator must arbitrate asynchronous wake against
stopping with a metastability-filtered mutex. A stop completes the active pulse;
resetting a mutex during a grant is not a valid operational stop.

No payload copy, receipt, bridge, reset change, latch-pair conversion or new
architectural storage is authorized. Controller/mutex state is counted in the
storage and overhead ratios. Partitions beyond this first region require a
measured benefit and at most 0.01 mm² overhead each; four regions is the limit.

| Remaining clock/input boundary | Obligation |
|---|---|
| LF watchdog/timebase | Independent elapsed time and recovery when fast logic stops |
| Generated service/work clock | Ordinary synchronous timing within the region; existing gated-work semantics |
| SDA event frontier | Existing START-event capture must wake a stopped generator |
| GPIO, LF and I²C synchronizers | Existing first/second stages sample on generated edges; bus activity must keep edges running |
| SPI MISO | The clocked reference samples directly in its SPI player; constrain the external source-synchronous input rather than invent a synchronizer |
| SRAM CLK | Generated tree; falling-edge pin launch, rising-edge access/capture, absolute pin apertures and pulse widths |

## Delays and timing

The one region delay is **relative**: its measured minimum period at each PVT
must exceed 1.2 times the same-corner critical requirement, including clock-tree
skew and setup. Include full- and half-cycle paths. The 1.2 factor is the user's
engineering allowance, not measured process mismatch. Use a measured mixed-cell
chain; no physical count comes from an RTL simulation delay.

**Absolute** obligations are SRAM setup/hold and high/low pulse widths,
controller pulse width, and POR hold. The current physical shell holds POR for
100,000 service cycles and relies on a period of at least 50 ns to guarantee
5 ms. Faster operation cannot silently invalidate that guarantee.

**Simulation-only** period bounds must come from the eventual measured chain.
No bounds are populated now. `desync-delays.json` is deliberately empty and
the mapper-facing loader rejects a missing entry. Sizing a candidate from unit
measurements does not replace final loaded-chain measurements.

Within the fast region use ordinary STA/CTS. No native-owner path checkers,
per-bit delays, ordinary protected data, or broad path waivers. Repair precedes
accepted timing. Routed min/max RC, reset, SRAM, pulse and mutex qualification
remain required. Flag zero-wire margins below 100 ps.

## Throughput and equivalence

For every stream require `events/window × worst cycles/event × slowest period
< window`. Existing I²C earliest-status tests use 400 kHz SCL at 3.2 MHz and
20 MHz service clocks. The user confirmed **400 kHz SCL**; 3.2 MHz is a service
clock test point, not the bus requirement. ADC and LF cycle counts, actual
generator period bounds and numerical throughput margins await Phase 1/3.

With the generator replaced by an external ideal clock, all existing state and
outputs must be sequentially equivalent. Generator/wake modules are the only
intended differences; their pulse/start/stop/POR tests are additional obligations.
`clk2fflogic` preserves asynchronous reset and edge detection in the formal
timestep model. Fixed SRAMs remain the identical blackboxes; this does not prove
their analog behavior. No test oracle or functional deadline may change.

## Acceptance and open physical dependency

`desync-budget.json` limits flat mapped ratio to 1.15, repaired-plus-tree ratio
to 1.20, storage ratio to 1.05, and delay/controller/mutex share to 5%. Budgets
may only tighten without approval. Compare identical configurations and flows;
retain one receipt per run. Phase 1 stops above 1.30 rather than trimming blindly.

The available GF180 mutex is a schematic candidate, without layout, LEF or
Liberty. Its registry entry has **no physical recipe**. No zero-area blackbox or
standard-cell substitute may satisfy the ratio or timing gates. Physical-cell
development is outside this batch: the user requested **finish Phase 0, then
stop**. No desync RTL, generator count or physical mutex qualification is claimed.

The clocked reference is 0.5318332992 mm² mapped and 0.5915383488 mm² after
repair, placement and CTS, with 2,977 storage bits. All 2,980 clock pins are
reached and all five PVT electrical reports are clean. The measured fast-region
zero-wire period requirement ranges from 30.995 to 112.803 ns before the 1.2
factor. This is an input to future sizing, not a working generator or routed
timing result. The ledger records evidence and limits.
