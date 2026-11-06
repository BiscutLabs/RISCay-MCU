# Clocked SoC implementation review

The clocked CPU landed separately as `be27bc9`. This batch adds the independent
SoC around it and reuses current chip-test bodies instead of restoring the old
clocked Services implementation wholesale.

## Independent findings and fixes

- Added the missing RAM_TOP MMIO value used by generic ROM stack initialization.
- Restricted ENTER_LOADER kick suppression to the running application; ROM
  maintenance resumes after watchdog recovery.
- Timestamped ADC samples at actual acquisition launch, including conversion
  and suspended-service time in age.
- Replaced asynchronous CPU reset under an open POR-owned receiver with
  synchronized, same-work-edge cancellation and CPU clearing. Accepted SRAM
  writes drain and old replies disappear.
- Kept I²C sampling on the ungated service clock. Gated sampling could miss
  START when SCL rose during sleep. A front-clock assertion requires a live
  work-clock consumer for frame/snapshot acceptance.
- Kept scenario booleans independent from the implementation selector in the
  shared boot suite. Both invalid-directory and golden-fallback branches run.

The reviewer inspected both reset/I²C fixes and found no remaining RTL blocker.
The final pass checked shared test assertions/deadlines and CI registration.
Its mapper findings are fixed: fixed SRAM model and pinned TT Liberty validation,
complete measurement-tool inputs, and a separately configured sv2v executable.
The reviewer confirmed those fixes and reported no remaining findings. Physical
qualification remains explicitly open.

## Functional evidence

Retained local evidence includes `build/clocked-core-r1.log`,
`clocked-core-r2.log`, `clocked-soc-r1.log` through `clocked-soc-r4.log`, and
`clocked-boot-r1.log`. Failed adapter/elaboration and START-detection runs remain
available; their expectations were preserved when fixing the implementation.

The complete clocked generic-boot suite passes **35 cases**: valid/corrupt and
incompatible images, blank fallback, A/B selection, golden recovery, interrupted
updates, exhausted generation, factory protection, lock, persistence readback,
watchdog recovery and shared ADC/SPI ownership. Both compiled firmware workloads
pass with the shared arithmetic/stack oracles. The event suite compares all three
implementations against the same arrival-cutoff history.

Additional clocked boundary cases pass for both GPIO-retention settings,
eight reset phases during accepted SRAM stores, stale-response cancellation,
SPI recovery release, POR clearing and sample age through a stopped service clock.

At the fixture's 10 MHz service clock, the 2,048-byte primary image reaches its
first application instruction at **89.798750 ms** (897,968 work edges). Rejecting
both corrupt field slots and booting golden takes **254.909150 ms** (2,549,072
work edges). The common ROM is **4,224 bytes**. These are simulated instruction
and pin timings, not post-layout frequency guarantees.

The extended wake workload uses I²C boot (`spiBoot=false`) identically for all
variants; it must not be confused with production SPI-boot mapping or the
full-capacity boot measurements above.

## Final gates and measurements

- `build/clocked-ci-r1/receipt.json`: PASS, 387 Python tests, 206 fast Scala
  cases, 12 selected boot cases and six physical export/policy cases. The
  physical cases qualify existing native generation checks, not clocked timing.
- `build/clocked-python-final/receipt.json`: PASS, 387 tests after mapper changes.
- `build/clocked-final-regression.log`: PASS, 34 cases covering native SoC/fabric
  regressions, both native and clocked deep sleep, and clocked activity.
- `build/clocked-sleep-label-r1.log`: PASS, the GPIO/sleep race case after
  correcting its test label to identify the clocked implementation.
- `build/clocked-comparison/map-r2/receipt.json`: PASS, pinned-cell mapping,
  three SRAM macros and every storage clock pin classified. Logic is
  0.531833 mm²; periodic sinks are 539 service + 2,362 work + 78 LF.

The clocked wake workload measures 27 maintenance, 176 ADC and 501 firmware
work edges, with 43 instructions in each firmware wake. Area, matching method,
activity scope and remaining physical obligations are recorded in the
[area ledger](../area-ledger.md#clocked-comparison-implementation).
No BD/Click implementation RTL changed, no existing oracle or deadline was
relaxed, and no new P&R campaign was run.
