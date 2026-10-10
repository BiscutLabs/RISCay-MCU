# RISCay-MCU contributor instructions

- Implement the MCU here; chisel-async and Chiselator remain separate projects.
- Deliver a reusable SoC with on-chip boot ROM, executable RAM and working RAM.
  Keep common CPU/host services independent of board names, pins and policy.
  Board/application bindings belong in `profiles/`; follow `docs/reusable-interface.md`.
  Groundlark's permanent bootstrap must qualify power and start its Pi without
  an application image. Other profiles must define their own boot dependency.
- Maintain both `designs/four-phase-bd/` and `designs/two-phase-click/` as active
  targets. Keep ISA, firmware, memory/MMIO, board I/O and functional tests equal.
- Native Click core routing must not silently use four-phase wrappers. Identify
  every external boundary conversion and include it in comparison costs.
- Each `designs/` target owns its separate SoC implementation. `soc/` retains
  schemas, parameters, fixed macro models and wrapper utilities, not a shared
  service implementation. Keep Click native and endpoint bridges explicit.
  Follow `docs/async-soc-migration.md`: finish and verify one checklist item,
  obtain a fresh independent agent review, address its findings, rerun affected
  checks, update its evidence/contracts, commit and push. Repeat this review loop
  for every item. Continue to the next item when the user has authorized it;
  otherwise ask. Items 1-9 are digitally verified.
  Obtain the user's next choice before physical requalification.
  Follow `docs/soc-contract.md` for ABI/reset scope. Run AsyncFabricSpec,
  AsyncControlSpec, ControlResetSpec, AsyncTelemetrySpec, TelemetrySpec and both
  service implementations' FabricSpec/ScalingSpec plus affected regressions;
  keep strict SoC exports valid. Run AsyncScalingSpec and ScalingSleepSpec after
  arithmetic changes; preserve exhaustive sample and independent CRC oracles.
  ConsumedGray advances on service publication, never internal native completion.
  Keep stale single-tick replies from granting supervisor observation credit;
  scaling work and bridge drainage inhibit sleep. Keep the seven-edge ordinary
  drain guard and full synchronized gate demand; grace may overlap tracked native
  maintenance. Run guard handoff and ADC discard/offset/calibration checks.
  A copied clocked module is not migrated to async.
  Native Control state and its command/reply bridges are POR-only. Keep accepted
  MMIO commits and SRAM accounting across watchdog reset; cancel unaccepted work.
  Preserve queued host reset/busy context, including simultaneous admission.
  Clocked ingress/arbitration, status projection and peripheral effects remain
  explicit boundaries until their checklist items are implemented and verified.
  Native Telemetry and its bridges are POR-only. Preserve acquisition ingress
  across application reset; immediately reset application GPIO/event projections
  and suppress stale replies. Never drop dispatched events from host visibility.
  Native Supervisor state, input history, output projection and both bridges are
  POR-only. Keep its acquisition stream independent of Control/Telemetry stalls.
  Include coincident ticks in publication freshness gaps; qualify dwell times and
  current-boot ACK after applied output publication. Run AsyncSupervisorSpec and
  SupervisorSpec, including repeated 32-edge watchdog resets and stalled crossings.
  Include queued elapsed time in host freshness.
- I2C migration uses separate native protocol loops and POR-only publication.
  Keep sampled wire slots immutable until the synchronized published head frees
  them; keep Click phase feedback in the complete projection timing aperture.
  Retain completed-frame reset history across whole watchdog episodes. Run
  AsyncI2cSpec, I2cSpec and the real serial loader/sleep/firmware cases; preserve
  maximum-delay wire checks and earliest on-wire completion observations.
  Clocked sampling, timeout, coherent bank capture and source wake remain explicit.
  Keep Chisel verification bodies inline in ClockedSimulation: Icarus does not
  execute uninstantiated extracted assertion modules. Run overflow negative controls
  and tools/check_i2c_wiring_controls.py against both standalone publication exports.
- SPI ADC uses separate native conversion/priming/assembly/scaling loops and a
  fixed-rate clocked waveform player. Preserve the immutable native pin recipe,
  all 32 observations, exact half-phases, first-complete-frame discard and busy
  through every crossing's return. All state/crossings are POR-only. Carry elapsed
  conversion age into both telemetry and supervisor histories; a buffered old
  frame must not acquire age zero on publication. Run AsyncSpiAdcSpec, SpiAdcSpec,
  AdcScalingSpec and cadence/sleep/firmware regressions. Keep strict program-port
  constants, player bindings and all dynamic endpoint activity checks intact.
  Run tools/check_spi_wiring_controls.py against both wire and strict SoC exports;
  preserve the original oracles when mutating actual loads, capture and constants.
  Low-power cadence now belongs to each native Housekeeping loop. Preserve the
  independent clocked LF/watchdog, Gray/ACK synchronization and safe source gating.
- Native Housekeeping and both crossings are POR-only. Preserve ordered timer,
  lease, wake-mask and period commits through stalled publication. Join deadline
  completion with Telemetry exactly once; allow CPU progress during continuous
  legacy ticks. Only final Housekeeping publication advances consumedGray.
  Keep observation/freshness ingress and permanent supervision independent of
  Housekeeping stalls. Include retained elapsed time in board-time projection.
  Recognize oversized/wrapping elapsed batches without reviving old application
  state after watchdog reset. Keep heartbeat phase/ACK coalescing in its explicit
  LF crossing; pending ACK delivery must not create timer work or hold the gate.
  Run AsyncHousekeepingSpec, HousekeepingSpec, both Fabric/Supervisor/ScalingSleep
  implementations and full sleep/firmware regressions. Drive testbench stall
  controls away from active clock edges; preserve every reset/effect assertion.
- Retained sleep and programmable sampling are in scope. Follow
  `docs/sleep-and-clock.md`; run SleepSpec, DeepSleepSpec and oscillator-model tests as well.
  Preserve the cold-boot policy, programming lock and watchdog fault coverage.
  An oscillator model or synthesis black box is not implemented analog IP.
- LF analog work lives in `analog/gf180-lf-osc/`; fast clock and supply reset in
  `analog/gf180-clock-reset/`. Preserve upstream
  attribution and pinned model hashes. Run its independent measurement controls
  and SPICE campaigns after circuit changes; document any model transformation.
  Never bind a slower analog candidate to the 4 kHz timer without updating its
  time units, Gray CDC contract, watchdog and board timing policy together.
  Source-stopping builds require the documented address-only I2C wake probe;
  preserve its startup/hold bounds and do not claim the fast-source model is
  implemented analog IP. LF reset is POR-only, never watchdog-generated reset.
  The fast source must run during reset qualification, independently of the
  held SoC/LF reset. Keep the >=5 ms continuous-good hold and asynchronous assertion.
  Test real hold counts separately from accelerated full-SoC regressions.
- Both writable memories use pinned GF180 1 KiB SRAM macros: two for the 2 KiB
  program bank, one for 1 KiB working RAM. Share the fixed macro model; each
  variant owns its SRAM controller. Follow `docs/sram-integration.md`; run
  SramSpec, FirmwareSpec, SocSpec/FabricSpec and sleep regressions after memory/controller changes.
  Run AsyncSramSpec and actual-lane SRAM reset/stall checks. Native execution
  credit serializes words until response acceptance; all SRAM crossings are
  POR-only. The clocked macro boundary performs one byte access/capture only.
  Keep CLK on the service clock, falling-edge input launch, full-cycle Q capture
  and busy through every crossing's return. Do not call old cycle-offset tests
  exhaustive native phase coverage.
  Offer the full RAM payload independently of valid; admission checks alone
  authorize capture. Strict mapping stimuli may force catalogued source registers,
  never derived endpoints, and must retain generic campaigns and negative controls.
  Keep macro contents uninitialized in simulation; SYNTHESIS must retain physical
  macro instances. Verify upstream asset hashes with tools/sram_assets.py.
  Validate full-width addresses and loader fields before narrowing to internal
  word indices/counts. Include full-capacity counts and small/non-power-of-two banks.
- Groundlark's permanent controller owns its power GPIOs. Keep its default policy
  disabled until qualified board/battery values are deliberately supplied.
- Optional features are on hold. Follow `docs/features-and-ip.md` and
  `docs/groundlark-io.md`; do not add heartbeat, RTC wake or diagnostics. Pi-assisted
  firmware reload after power loss is now in scope; persistent field updates are not.
- Loader status, validated-image reporting and a hardware programming lock are
  required in both variants. Follow `docs/loader-status-and-lock.md`; only full
  MCU reset or MCU power loss clears the lock. Pi resets and bus resets do not.
  Application watchdog reset must preserve permanent power supervision, GPIO
  ownership, sensing/timekeeping, validated image and programming lock. Test
  Groundlark with the production 32-edge watchdog ratio, including trapped firmware.
  Stuck/abandoned I2C transactions must release the service source; held-low
  lines and foreign-address payloads must not sustain an oscillator wake.
- Generic measurement channels and an application register area are required.
  Groundlark binds these to battery/supervisor telemetry. Include validity,
  freshness and calibration status; lock must not block reads or sample updates.
- Use explicit reset and async contracts. A digital delay model is not a mapped
  delay cell, and passing simulation is not physical timing or power evidence.
  Keep raw watchdog reset on reset pins/source wake only; persistent service
  logic uses its two-flop synchronized copy, and gate demand is synchronized.
  Preserve the writeback-before-forwarding guard and include register-read muxes
  in the execute timing budget; run the fastest-memory and guard-bypass controls.
  Deadline replacement consumes only the old deadline event, including a
  coincident expiry, while preserving other events and arming the new deadline.
  Validate MMIO width before blocking or consuming a WAIT; rejected reads must
  neither authorize sleep nor cancel a lease.
- Run the relevant ScalaTest/Icarus suites after changes. For architectural or
  interface changes, run both core variants against independent references.
  Missing tools, no activity, skipped tests and failed controls are not passes.
- Keep shared production logic separate from independently written test oracles.
  Test reset, stalls and exactly-once effects, not only instruction arithmetic.
- Physical integration lives in `physical/`; follow `docs/gf180-implementation.md`.
  Preserve exact async cells and connections, native delay chains and three SRAMs.
  Keep clocked STA separate from internal async path measurements. Recharacterize
  changed cells/whole transforms across all five pinned corners, and rerun
  `physical/test` plus mapping/monitor controls after changing physical budgets.
  No standalone-cell, stage or constraint-binding pass implies routed closure.
- Keep generated RTL, tools, simulator logs and test evidence under ignored
  `.tools/`, `build/` or `target/` directories. Pin dependencies and record limits.
- Firmware and memory budgets live in `firmware/`; run FirmwareSpec and the
  firmware Python controls after changing its runtime, workloads or capacities.
  Preserve real I2C uploads, both native variants and independent stack evidence.
- Update README and affected contracts when behavior or implementation status
  changes. Communicate succinctly and distinguish implemented IP from planned IP.
