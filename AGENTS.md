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
  otherwise ask. Items 1-9, 10a, 10b1, 10b2a, 10b2b, 10b2c1, 10b2c2a, 10b2c2b, 10b2d1, 10b2d2, 11a1 and 11a2a are digitally verified within their scopes.
  The user has authorized deeper migration under expanded items 10-16: native
  service coordination, observation reduction, publication, direct interconnect
  and physically justified boundary minimization. Audit every remaining clocked
  state owner; a boundary label alone is not a reason to retain synchronous logic.
  Keep independent watchdog/time and physical I/O obligations. Physical
  requalification is now item 17 and follows the residual-state audit.
  Audit generated chip reset-hold state separately and cover supported parameter/
  profile configurations; the Groundlark low-power emitter is not a whole-chip
  or configuration-complete inventory. Preserve continuous-good reset hold.
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
  Native completion presentation follows coordinated application reset. Its
  CPU-facing crossings retain POR ownership and rebase only while acknowledged
  closed; persistent accepted effects retain their existing POR ownership. Preserve the
  BD rendezvous return barrier and Click aggregate payload/phase aperture. Keep
  fixed guard IDs recognized by AsyncTest, test immediate source reuse and
  unselected pending tokens, and assert source readiness at completion capture.
  Qualify selection before native phase admission; a delayed readiness vector
  alone does not prevent old-selector/new-request hazards. Keep absent-selected-
  source tests and directed minimum/maximum gate skew, with unchanged oracles.
  Admission retirement is retained by each native credit owner; idle never creates
  credit. Consume the single seeded grant at request commit, preserve HALT until
  application reset, and keep offered MMIO requests visible during credit stalls.
  BD recycling waits for full response RTZ. Click input/output parity and startup
  belong to the application lifetime. Run AsyncAdmissionSpec/AdmissionSpec and
  actual admission-gate, credit-consumption and return-barrier mutation controls.
  Native RAM source ownership reserves before CPU acceptance. Commit/grant/word
  capture must agree; cancel old queued grants without issuing memory effects.
  Eligibility alone is not a response-valid signal. Release reset debt only
  after owner/receipt/word/byte drainage. wordDrained excludes source reservation,
  grant, decision and publication receipts; it includes the independent capture
  receipt idle condition.
  Keep source phases/effects POR-only and run AsyncRamSourceSpec/RamSourceSpec.
  Working-RAM return now connects native SRAM directly to retained RamReturn,
  RAM-source publication and a separate Completion input. Follow
  `docs/ram-return-contract.md`; substep 10b2d1 is digitally verified.
  Preserve captured permission, independent POR/application phases, actual issue
  history, full BD returns and payload retention through every branch. Temporary
  capture ACK means RamAccess.active cleared on that clock edge. Its acceptance
  must not depend on publication, debt or return-owner idle. wordDrained joins
  effectsDrained and presentationSettled; full busy additionally includes return
  occupancy. Run AsyncRamReturnSpec, capture-stall/work-clock-stop RamSourceSpec,
  exact macro-effect checks and four-source AsyncCompletionSpec. Validate actual
  receipt/access RTL and the complete literal-error alias cone before masking
  impossible polarity; preserve all dynamic activity and mutation oracles.
  Bind production wiring controls to the actual executed strict probe and
  compiled binary. Reject stale evidence and require each mutant's exact fatal
  assertion location; unrelated failures and matching display text do not count.
  Program/loader return substep 10b2d2 is digitally verified. Follow
  `docs/program-return-contract.md`; preserve its native role/capture contracts
  and qualification gates. Capture ProgramSource.cpuPresentationPermit with the
  word; raw eligible alone admits loader words to CPU. Preserve Stored progress while
  capture receipt/full access busy is held, and monitor native response offers.
  Run composed program role/capture controls on both variants' integrated
  fixtures. Use independent committed CPU/loader identity, actual capture pins,
  per-register reset exemptions and opposing source/return delays. Preserve
  fixed guards, data budgets and all original assertions. Exercise actual
  production program/RAM alias faults before accepting their constant masks.
  Native program ownership tags each slot CPU-read or loader-write. Late Control
  work may cancel an unaccepted CPU slot; revalidate image permissions after
  BEGIN and fault invalid reads without a word effect. Loader reserve, grant,
  commit, publication and Stored delivery all bypass CPU reset debt. Stored
  acknowledgment means its Control command fired; retain admission-time busy
  history until the Stored reply publishes. Click Stored history is independent
  of CPU/cancel parity. BD Stored return gates reserve ACK falling, not rising.
  Run AsyncProgramSourceSpec/ProgramSourceSpec, held grant/decision/byte/publication
  and Stored command/reply-edge cases, plus actual RTL mutation controls.
  Run tools/check_program_capture_controls.py for all six custom Click registers;
  require every seed/skew fixture, actual-pin setup/hold/pulse/distribution checks
  and their negative controls. Preserve the original functional oracles.
  The specialized Stored receipt crossing retains two request synchronizers and
  POR phase/ACK ownership; ACK means Control acceptance. Its payload is held by
  the native Stored buffer through acknowledgment. Run StoredReceiptSpec and
  earliest on-wire I2C status tests; qualify the complete bundled-data CDC path.
  Native Telemetry/Housekeeping publication owners reserve every required source
  before CPU acceptance. Keep grant/decision/CPU commit atomic and leave parked
  WAIT unreserved. Reservation occupancy must not block its own commit. Actual
  publication feeds a POR receipt even after CPU cancellation; live eligibility
  alone cannot issue completion. Every committed decision retains a drain offer,
  including reset-cancelled staged Telemetry; accepted Housekeeping work persists.
  Keep publication ACK independent of retirement and exclude queued observations
  and recovery flags from the old-client quiet proof. Click publication/drain
  phase histories are independent; BD waits for complete grant/receipt/drain
  return. Run AsyncPublicationSourceSpec/PublicationSourceSpec, independent stalls
  for both sources, repeated raw resets and actual RTL mutation controls. Run
  tools/check_publication_capture_controls.py against every seed/skew fixture;
  require actual-pin capture, pulse, distribution and reset-overlap evidence.
  Recovery reservations carry an immutable role through grant, command, reply
  and drain. Housekeeping resetApplication alone is not recovery identity.
  Native recovery debt clears only after fresh attributed publication and full
  original/final return. Substep 10b2c2b is digitally verified. Retain proof
  identity independently of the next payload, and exclude early native admission.
  The temporary final receipt checks raw original crossings/client quiet; never
  include owner idle, gated reserve readiness, debt or itself in its quiet proof.
  Qualified reset immediately masks the application; POR proof transport drains
  independently. Keep the 200 ns cleanup guard and recognized fixed guard IDs.
  A slot armed during application reset stays ineligible after deassertion.
  Run AsyncRecoveryReturnSpec/RecoveryReturnSpec, all custom capture-pin controls
  and actual proof/admission/receipt mutations, preserving the original oracles.
  Count the net six temporary clocked bits per variant and remove these receipts
  with their clocked clients in item 14; this is not minimum synchronous state.
  Run AsyncRecoveryOwnershipSpec/RecoveryOwnershipSpec, actual debt-pin capture
  controls and isolated owner mutations after recovery changes. Include
  pre-recovery quiet with reserve ingress stalled, stale recovery replies,
  offered CPU work, final-return reset and prolonged-reset housekeeping progress.
  Follow the digitally verified R1 contract in `docs/application-reset-boundary.md`: immediate
  watchdog isolation/debt must not destroy a native producer while its clocked
  receiver can capture. Require actual closure, rebase and withdrawal edges;
  payload stays retained. Keep POR application projections with synchronous
  cancellation and immutable publication reservation roles. Run QuiescingBridgeSpec,
  ResetBoundarySpec and ResetBoundarySocSpec plus structural RDC mutation controls.
  Application reset qualification still uses eight ungated service edges
  (>=350 ns at the 20 MHz ceiling), restarting on every raw pulse. The inherited
  250 ns digital settlement assumption is insufficient for measured physical
  guard propagation: R2 must resolve this before physical qualification.
  Inject reset-test pulses before this qualifier; never lengthen failing pulses.
  Run AsyncCompletionSpec/CompletionSpec and real completion wiring mutation
  controls; preserve the full emitted port ABI even for constant error fields.
  Strict completion stimulus may force only catalogued source registers or
  exactly validated native storage outputs. Joint RAM-drain scenarios use BD's
  retained C-element state and Click's retained phase registers; release and
  settle Click's derived ownership cone instead of forcing its result. Preserve
  every dynamic bit's polarity activity; the three literal bridge input leaves
  require exact emitted bindings, schemas and per-check value assertions. Reject
  dynamic expressions before granting a constant mask. Keep actual-RTL mutation
  controls and first-pass probe/output evidence before checker fallback.
  Credit-return payloads are literal zero: validate the exact single elaborated
  scalar driver and assert its value at every check before masking impossible
  polarity. Limit this to Completion's output and its two connected ingress
  aliases; stored grant payloads and all other dynamic bits retain activity checks.
  Require native Admission and the variant-specific grant bridge in SoC exports.
  Native Control state and its command/reply bridges are POR-only. Keep accepted
  MMIO commits and SRAM accounting across watchdog reset; cancel unaccepted work.
  Preserve queued host reset/busy context, including simultaneous admission.
  Clocked ingress/arbitration, status projection and peripheral effects remain
  explicit boundaries until their checklist items are implemented and verified.
  Native Telemetry and its bridges are POR-only. Preserve acquisition ingress
  across application reset; immediately isolate application GPIO and clear
  clocked event/word projections through coherent cancellation. Suppress stale
  replies. Never drop dispatched events from host visibility before cancellation.
  Native Supervisor state, input history, output projection and both bridges are
  POR-only. Keep its acquisition stream independent of Control/Telemetry stalls.
  Include coincident ticks in publication freshness gaps; qualify dwell times and
  current-boot ACK after applied output publication. Run AsyncSupervisorSpec and
  SupervisorSpec, including repeated 32-edge watchdog resets and stalled crossings.
  Include queued elapsed time in host freshness.
- I2C migration uses separate native protocol loops and POR-only publication.
  The 11a1 frame receipt keeps five POR-only clocked bits and no payload copy.
  ACK must coincide with actual work-clock mailbox capture. Qualify ready with
  the falling-edge gate's running state, retaining ungated pending-frame demand.
  Follow `docs/frame-admission-contract.md`; 11a2a's native payload/epoch storage
  is digitally verified, with physical qualification still open. Four physical banks retain exactly two logical
  admission credits. Preserve original O/A/ACK, per-bank Click phases and BD's
  retained route through RTZ. At O prove complete bank availability and a new
  capture ordinal, including identical payloads; copy equality alone is not proof.
  Retain source epoch through D and compare against the coincident current epoch.
  Queued descriptors awaiting head observation retain priority over CPU MMIO.
  Keep native logical credit removal separate; narrow Q/descriptors, tail, busy
  synchronization and four head receipts remain temporary for 11a2b/11b/14.
  Run AsyncFrameStoreSpec, FrameReceiptSpec, FrameAdmissionSpec and FrameWakeSpec,
  actual 337-bit source/bank and ControlCommand capture controls, all nine Click
  trigger/pulse/distribution checks, and exact-fatal full-queue controls
  including simultaneous dequeue, and unchanged Stored-edge/context assertions.
  Keep native-bus aperture checks separate from physical synchronous-context hold.
  Strict exports must close receipt storage/reset, native publisher/data aliases,
  actual clock-enable and mailbox bindings before accepting any literal mask.
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
  Keep raw watchdog reset on the qualified isolation/debt and source-wake paths;
  service cancellation uses the coherent boundary after two-flop observation.
  Resetting native producers before their clocked receivers close is forbidden.
  Persistent service decisions use synchronized native observations or explicit
  proved held-bus contracts, and gate demand is synchronized.
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
  Bind ControlGate intent through the reviewed owner/ID catalogue and exact
  contract delay-cell references, never bus width. Reject unknown roles,
  passive active-gate views and tuple-role collisions before mapping. Preserve
  per-lane control chains and scalar data allowances. Follow
  `docs/physical-control-guard-contract.md`; local adapter measurements do not
  close complete custom transforms or controller envelopes. Feed actual guard
  maxima back into those envelopes without relaxing functional timing oracles.
  Physical exports use current supported SoC timing and an enabled evaluation
  board policy, with inline assertions and v2 contract/port hash binding. Keep
  the composed Click-policy rejection and exact source inventory. Follow
  `docs/physical-export-contract.md`; old v1 exports require regeneration.
  Standalone PhysicalTiming core tests do not authorize that policy for every
  controller. Constraint coverage and complete physical envelopes remain open.
- Keep generated RTL, tools, simulator logs and test evidence under ignored
  `.tools/`, `build/` or `target/` directories. Pin dependencies and record limits.
- Firmware and memory budgets live in `firmware/`; run FirmwareSpec and the
  firmware Python controls after changing its runtime, workloads or capacities.
  Preserve real I2C uploads, both native variants and independent stack evidence.
- Update README and affected contracts when behavior or implementation status
  changes. Communicate succinctly and distinguish implemented IP from planned IP.
