# Asynchronous SoC migration checklist

This checklist is the migration boundary, not a claim that all peripheral RTL is
asynchronous. Complete, verify, document, commit and push one item, then ask the
user which item to take next. Both implementations remain active throughout.

## Ownership and invariants

- Four-phase bundled-data implementation: `designs/four-phase-bd/src/main/scala/riscay/bd/`.
- Native two-phase Click implementation: `designs/two-phase-click/src/main/scala/riscay/click/`.
- Each owns its Fabric, Services, Platform, ClockedPeripherals, ConstantScaling,
  I2cTarget, SleepTiming and SramBank code. Copying the former service island into
  these directories establishes ownership; it does not migrate its state machines.
- Share port schemas, parameter/ISA definitions, fixed macro models and verification
  utilities. Keep protocol controllers separate; Click must not use hidden RTZ adapters.
- Preserve the host/firmware ABI, programming lock, validated image, accepted SRAM
  effects and retention, retained sleep, application-reset isolation, and permanent
  Groundlark power supervision. Keep an independent timebase/watchdog even as
  service-clock work is removed. Never relax tests to accept implementation bugs.

## Items

- [x] **1. SocFabric routing - digitally verified, 2026-10-08.** Native request/response routing,
  clockless ROM/static faults, endpoint backpressure/return sequencing, coordinated
  reset and retained payloads. Keep stateful MMIO/SRAM behind explicit endpoint
  bridges. Expand focused and independent-service tests for both implementations;
  rerun affected SoC/sleep/firmware/SRAM, core/reference and Python controls and
  strict exports. Update contracts and evidence, then commit and push.
- [ ] **2. MMIO and loader state.** Move state/serialization and validated-image
  accounting into each protocol; preserve full-width validation, atomic acceptance,
  upload arbitration, reset isolation and the POR-only programming lock.
- [ ] **3. GPIO, events and telemetry.** Preserve board ownership, coherent snapshots,
  set-wins event arbitration, deadline replacement and WAIT/lease semantics.
- [ ] **4. Scaling and CRC.** Independent native sequencing with unchanged arithmetic,
  fractional time, wrap/catch-up and image-integrity oracles.
- [ ] **5. Permanent supervisor.** Independent protocol implementations of continuous
  power supervision; never make Pi bootstrap depend on uploaded firmware or reset
  it with the application watchdog. Preserve disabled-by-default production policy.
- [ ] **6. SRAM access sequencing.** Native request ownership/arbitration around the
  fixed synchronous GF180 macros; qualify any local clock generation explicitly.
  Preserve byte effects, accepted-store completion and uninitialized retention.
- [ ] **7. I2C.** Native controller implementation with the existing wire protocol,
  address-only wake probe, startup wait and stuck/foreign-bus release behavior.
- [ ] **8. SPI ADC.** Preserve conversion timing, invalid-first sample, cadence,
  reconfiguration boundaries, freshness and supervision independent of CPU progress.
- [ ] **9. Slow-domain housekeeping.** Native coordination where appropriate while
  retaining the independent LF reference/watchdog, Gray CDC and safe source gating.
- [ ] **10. Physical requalification.** New-controller timing contracts, mapped
  decode/data paths, pulse/fork/return timing, reset and CDC bounds, then new P&R
  and extracted validation. Digital passes alone cannot check this item.

The numbered candidates after SocFabric are proposals; the user chooses the next
item. Each requires both implementations and invariant-focused tests before it
can be checked off. Do not start the next item automatically.

## SocFabric handshake and timing contract

ROM read/fetch and statically invalid addresses/permissions/widths terminate in
the native fabric without a service clock. Valid program reads/fetches, working
RAM accesses, full-word MMIO and HALT route to the clocked endpoint. Dynamic image
length/validity, writable MMIO permissions, WAIT, loader arbitration and SRAM
side effects remain endpoint responsibilities. HALT commits once and parks
without a response until coordinated reset, as in the existing core contract.

Four-phase holds the source payload through request acknowledgement return.
The reply uses long-hold storage. Endpoint response acknowledgement must stay
asserted until its request falls; source acknowledgement return waits for the
reply input and both endpoint channels to drain. A stalled downstream response
retains its payload independently of the next source request.

Click keeps separate source/reply, endpoint-request and endpoint-response phases.
Local transactions do not toggle endpoint phases. Dispatch fires once per pending
endpoint transaction; reply capture waits for endpoint acceptance and a fresh
response phase. Source and output guards must cover the actual composed control
network, including the three-cell De Morgan ANDs. Standard single-AND ClickStage
bounds alone do not cover that network. The release guard is at least
`inputPhase.max + 7*fire.max + skew + max(pulseLow, hold) + 1 fs` (80.200001 ns
for the 1..10 ns simulation envelope), as well as the supplied standard guard.
The seven cells are one comparator and two serial AND networks. The bound is
checked at source acknowledgement. Endpoint response parity samples its request
on the common capture pulse; local transactions keep that phase unchanged.
There is no separately gated capture pulse that can be filtered by unequal delays.
Source payload reuse must follow capture
pulse drainage. Exported data-path budgets include
the complete ROM/decode/response mux, not an extra physical data buffer.

Both endpoint bridges synchronize control and allow payload settling. Reset all
connected CPU/fabric/bridge phases together on application reset; permanent
service state stays POR-only except its explicitly application-owned registers.
Independent LF/watchdog logic remains live when the service source stops.

These controllers are digital models with ideal combinational glue/forks.
New decode, return paths, endpoint crossings, local pulse widths/distribution,
setup/hold and reset recovery need physical characterization. Historical P&R
under `build/pnr-first/bd-v5` and `click-v2` is for baseline `8637099`, has open
violations, and does not qualify this migration.

## Evidence

The inherited `build/async-fabric-migration/regression.log` records 48 tests,
41 passes and seven four-phase failures. Preserve it and the original lock error
in `native-first.log`. The first focused run (`focused-initial.log`) failed to
bind endpoint port names; `focused-ports-fixed.log` then exposed handshake errors.
`focused-return-ack.log` retains the Click maximum-cell-delay failure after the
first BD return fix. Later strict path/scope and unsized-alias elaboration failures
are also retained rather than overwritten.

Final results: 89 distinct verification cases and two core physical-policy cases
pass; 64 working-tree Python controls pass (six belong to the preserved earlier
P&R work), and all 11 SRAM assets verify. Both production-capacity SoCs pass strict
`--soc --vector-coverage --sleep-clock` exports with three macros each and native
Click throughout. Exact logs, hashes, counts and qualification limits are in
[build and test](build-and-test.md#asynchronous-socfabric-migration).

SocFabric is the only checked migration item. MMIO/loader, GPIO/events/telemetry,
scaling/CRC, permanent supervisor, SRAM sequencing, I2C, SPI ADC and slow-domain
housekeeping remain future choices. Ask the user which item to take next after
committing and pushing this item.
