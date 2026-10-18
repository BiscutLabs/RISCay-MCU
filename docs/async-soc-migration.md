# Asynchronous SoC migration: open work

RISCay is a **generic MCU**: ROM contains the bootloader; application policy lives
in external firmware. **BD is the tape-out target. Click is frozen as a native
functional reference**, retaining regressions and shared correctness/ABI fixes.
Completed work and old contracts are in the [migration log](history/migration-log.md).
The [architecture plan](architecture-followups.md) supplies boundary details.

## Architecture and implementation

- [ ] **A. Always-on/application island split.** Absorbs C1e2, the 10b remainder,
  11b, 13a and 14. Assign state, reset, cancellation and wake ownership; move each
  subsystem's producer and consumer together, with one crossing per subsystem.
  Remove duplicate queues, mirrors and grant/drain round trips while preserving
  committed SRAM/loader effects, lock, retention and close/rebase recovery.
  Start with a logical split on one supply. Measure mapped/repaired area, periodic
  clock sinks and wake activity/duration against the parent for each batch.
- [ ] **B. Register-pointer host interface.** Replace the framed loader; do not
  build a permanent second transport. Decide the versioned wire ABI and host
  transition before RTL. Absorbs 11a2/11a2b, 13c, R5 epoch work and the R6 public
  frame-route AND replacement if frame banks survive. **11a2b is paused until the
  ABI decision.** Define coherent reads, partial-write commit, busy/reset/overflow
  behavior, pointer bounds and lock enforcement; reuse the existing loader/CRC owner.
- [ ] **Boot resilience.** Specify A/B boot slots, golden-image recovery and factory
  programming/verification. Test corrupt/blank slots, interrupted updates, POR,
  watchdog recovery and lock behavior. Measure boot time at full configured image
  capacity, including validation, SRAM copy and fallback. No application policy in ROM.
- [ ] **11c. Arbitration.** Use a physically qualified native MUTEX only where
  independent asynchronous requesters meet. Clocked arbitration at a real crossing
  is acceptable; verify fairness, simultaneous arrivals and reset containment.
- [ ] **12. Observation transport.** Use one acquisition consumer. Retain 12a elapsed
  ordering/reduction and 12c GPIO/event history only where retained application services
  need them; preserve sample age/validity, set-wins events and bounded buffering.
- [ ] **13b. Output publication.** Remove redundant GPIO/cadence copies where timing
  permits. Keep generic POR inputs, optional watchdog GPIO retention and SPI release;
  there is no board-owned output or supervisor feedback path.
- [ ] **BD request guards.** After A/B, enumerate surviving canonical request guards
  and size them in one same-corner campaign, with mismatch derates, complete launch/
  capture/ACK/hold composition, pulse floors and worst-corner throughput checks.
- [ ] **16. One residual-state audit after the split and ABI integration.** Cover
  generic SPI boot and I²C fallback, ADC on/off, retained sleep on/off, supported
  time sources/capacities and both GPIO-retention settings. Reconcile native/event/
  periodic storage, generated wrappers and clock sinks; compare the frozen Click
  reference without restarting its optimization. [Configuration details](architecture-followups.md#residual-audit-configuration-matrix).

## Remains clocked and why (15)

| Boundary | Required obligation |
| --- | --- |
| Production SRAM macros and pin controllers | Qualified CLK pulse, address/data setup/hold and read capture |
| I²C/GPIO pin sampling | Metastability containment, filtering and bounded edge capture |
| SPI pin player | Bounded SCLK high/low times and MISO sampling aperture |
| LF timebase/watchdog | Time and recovery independent of CPU/service progress |
| Reset qualifier/coordinator and clock gates | Real-time reset holds, receiving-edge close/rebase, safe stop/start |

15a–c (self-timed SRAM, edge-driven pin capture and SPI sequencing) are **optional
research**, not prerequisites for tape-out. Service scheduling is addressed by A,
not exempted by this table. Keep the asynchronous SDA wake event. Qualification of
15d/e (time/watchdog, reset/wake/gating) belongs to 17.

## BD tape-out gate (17 + R2b)

- [ ] **Regenerate 17a3 after A/B** from the final ownership graph and protected leaf
  pins: ROM/fetch, RF/execute, elapsed, I/O, SRAM, feedback/return, arbitration and
  every surviving custom controller. Missing obligations fail qualification.
- [ ] Close electrical and routing violations, then composed setup/hold/ACK,
  capture-tree spread, pulse/rearm, clock skew/duty, SRAM and CDC checks across all
  required corners with extracted min/max RC and justified mismatch derates.
- [ ] **R2b:** qualify complete reset assertion/release distribution, recovery/removal,
  hold intervals and startup, including generated reset trees, wake and clock gating.
- [ ] Apply routed hold repair **only to failing composed paths**; reserve **0.05 mm²**
  separately from electrical/CTS area. Recheck setup, ACK and sibling paths after
  repair. Complete DRC/LVS, pad/analog integration and reconcile the item 16 inventory.

Each implementation batch needs affected [verification](build-and-test.md), a fresh
independent review and an [area/activity ledger](area-ledger.md) entry before commit
and push. **Groundlark firmware and board integration are external dependencies**;
this repository implements neither their power policy nor their firmware port.
