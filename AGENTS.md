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
  Keep independent watchdog/time and physical I/O obligations. Boundary
  acceptance must coincide with the actual consumer clock: snapshot receipts
  need explicit work-clock qualification or a verified wake invariant, just
  like frame/head receipts. C1g is digitally verified with actual snapshot
  capture, stopped-consumer and exact-fault controls. Track C1d–f before claiming
  minimum boundary state. C1e1 changes only the 70-bit CPU request receiver:
  preserve the actual native address-stage source, valid-zero masking, both
  request synchronizers, settling/ACK/return cadence and POR close/rebase history.
  Run QuiescingReceiptSpec, QuiescingBridgeSpec, ResetBoundarySpec and
  ResetBoundarySocSpec plus affected regressions and actual source/mask/gate/RDC
  controls. ACK must coincide with the actual gated consumer capture. Include
  background consumers, native source hold and minimum mask-removal hold in the
  physical aperture; digital cadence is not timing qualification. Force only
  the catalogued native payload in strict probes, never derived receipt outputs.
  C1e2's six smaller grant/drain receivers retain ten payload bits and stay open.
  I2C's native observation contains only headGray, active, rejected, addressByte,
  drive, ack and sent (15 bits). Preserve the complete publication input and
  source/capture aperture, independent frame/snapshot retention and Click phase
  feedback. Run AsyncI2cObservationSpec, AsyncI2cSpec and actual-pin wiring
  controls for projection changes. A5b moves received bytes into one native
  addressed 33-byte scratch bank: protocol state is 76 bits and update result
  174 bits. Follow docs/native-i2c-byte-store-contract.md; run
  AsyncI2cByteStoreSpec and AsyncI2cPublicationOrderingSpec, including full-index
  rejection, stalled state/publication ordering and immediate source reuse.
  Preserve scratch self-feedback and scratch-to-frame timing paths, the actual
  native capture pins, independent BD returns and Click phase histories.
  Frame publication, four banks, sampled readWord and reset epochs remain
  separate A5 reductions. No periodic clock belongs inside the scratch owner.
  Keep raw-reset diagnostic mirrors in verification fixtures only; production
  cancellation/debt remains POR-owned. Preserve diagnostic fault controls.
  Physical requalification is item 17; the corrective gates below take priority
  over further residual-state removal.
  Audit generated chip reset-hold state separately and cover supported parameter/
  profile configurations; the Groundlark low-power emitter is not a whole-chip
  or configuration-complete inventory. Preserve continuous-good reset hold.
  Follow `docs/soc-contract.md` for ABI/reset scope. Run AsyncFabricSpec,
  AsyncControlSpec, ControlResetSpec, AsyncTelemetrySpec, TelemetrySpec and both
  service implementations' FabricSpec/ScalingSpec plus affected regressions;
  keep strict SoC exports valid. Run AsyncScalingSpec and ScalingSleepSpec after
  arithmetic changes; preserve exhaustive sample and independent CRC oracles.
  Follow `docs/native-crc-contract.md`: Control retains the full update context
  while one native whole-word CRC stage retains only its 32-bit candidate.
  Join context/result requests and state/CRC-ingress acknowledgments with native
  C-elements; preserve BD's independent falling returns and both Click phases.
  Only Stored commits the candidate. Run AsyncCrcSpec, AsyncCrcControlSpec and
  AsyncControlSpec, including exact rendezvous mutations, actual capture/POR,
  immediate legal source reuse, queued Stored and held public replies. CRC
  transform timing remains a separate physical gate; do not replace its native
  rendezvous with periodic-clock stages. A2b retains loader length/received counts
  at the width needed for program capacity itself, and entry offsets at the width
  needed for capacity minus one. Validate full 32-bit BEGIN length/entry and WRITE
  offset before narrowing; pad entry to 32 bits before adding the program base.
  Keep full-capacity, small/non-power-of-two, every-discarded-host-bit, duplicate
  Stored, reset and lock cases in AsyncControlSpec. Strict Control layouts derive
  from independently validated SRAM capacity, never the observed bus width.
  Run the unchanged CRC rendezvous and retained-reply/graph controls after layout
  changes; preserve 337-bit frame banks and the 70-bit native CPU request source.
  ProgramAccess upper-address zero obligations require proof from the actual
  emitted combinational cone, with every storage output unconstrained and no
  reset/valid/admission assumptions. Keep per-check four-state zero assertions,
  all mapping comparisons and exact loader/CPU counterexample controls. A paired
  probe exceeding the reviewed resource bounds must fail before allocation;
  never truncate its stimulus or convert that failure into an export pass.
  ConsumedGray advances on service publication, never internal native completion.
  Keep stale single-tick replies from granting supervisor observation credit;
  scaling work and bridge drainage inhibit sleep. Preserve full-width target/
  delta, retained fractions and publication ownership through A1 elapsed
  reductions. Bounded native feedback must handle every 32-bit delta without
  work proportional to elapsed ticks, and retain external handshake histories
  independently of iteration parity. Run AsyncElapsedLoopSpec and
  tools/check_elapsed_capture_controls.py against the complete freshly generated
  fixture cohort, including phase-zero publication, independent BD returns,
  actual capture pins, opposing skew and exact-fatal controls. Follow
  docs/native-elapsed-contract.md; digital passes do not close the measured
  whole-transform data-budget or physical capture/reset obligations.
  Keep the seven-edge ordinary drain guard and full synchronized gate demand;
  grace may overlap tracked native
  maintenance. Run guard handoff and ADC discard/offset/calibration checks.
  A copied clocked module is not migrated to async.
  R4's matched 8637099/2e4169c comparison is complete and favors the smaller
  historical clocked island. The user's subsequent instruction authorizes
  correcting the synchronous shell around the native services, superseding
  the migration freeze. Follow `docs/gf180-matched-comparison.md` for the retained
  cost evidence. Remove duplicate storage and crossings through explicit native
  ownership/completion; measure total cost before accepting each change. Never
  add periodic-clock staging merely to satisfy synchronous STA assumptions.
  Adapt analysis with exact path/relative-timing contracts and retain real
  setup/hold, pulse, reset, slew and load failures. Keep both native CPUs and
  preserve R1/R2 and every later correctness fix. R3 frame-copy completion is
  digitally verified; R2b reset distribution and the complete physical frame
  capture/return envelopes remain open.
  Never infer energy savings
  from clocked-bit or work-edge counts alone. Keep historical failures visible.
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
  R2a is digitally verified: pulse qualification retains eight ungated service
  edges (>=350 ns at 20 MHz), restarting on every raw pulse. Native reset hold
  and post-release isolation each count 64 service edges, with actual rebase
  and withdrawal acknowledgments still required. Each interval is conservatively
  at least 3.15 us at the clock ceiling; this covers the known local guard bound,
  not a complete physical reset-tree/core-startup envelope. The 250 ns supported
  digital timing-policy limit is separate from physical reset propagation.
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
  Service reply receipts capture Control, Telemetry, Housekeeping and Supervisor
  payloads directly from their retained native owner. Follow
  `docs/service-reply-capture-contract.md`; preserve the existing seven control
  bits, synchronizers and ACK cadence, with no duplicate payload bank. ACK means
  actual consumer acceptance. Run ServiceReplyReceiptSpec and composed service,
  reset, sleep and firmware checks; strict probes must resolve actual native
  storage and independent field packing, not force a derived bus. Keep complete
  producer-to-consumer setup/hold and earliest ACK release physically unqualified
  until measured. C1 removes payload copies, not the clocked service scheduler.
  C1b extends direct held-bus capture to elapsed/ADC replies, waveform/snapshot
  notifications and eight native SRAM byte requests. Follow
  `docs/held-peripheral-capture-contract.md`. Keep the macro controller's actual
  saved request, tag and falling-edge launch. Prove all saved-data D inputs,
  exact source aliases, common clock, priority/ready and POR-qualified capture
  before granting RDC exemptions; never exempt the complete bank. Run actual
  SRAM capture monitors, ServiceReplyReceiptSpec and the structural/compiled
  wiring controls in `check_held_receipt_controls.py` and
  `check_held_receipt_wiring_controls.py`. Native waveform tokens come from
  each Join's input buffer, not the retired clocked command sender. Strict
  exports reject ordinary storage beneath native owners using
  `check_native_clock_inventory.py`; primitive exceptions require known models
  and exact compiled bindings. Retain full generic mapping campaigns and exact
  fatal sites; a structural negative control is not a simulated wire fault.
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
  Receipt ACK must coincide with actual work-clock mailbox capture. Qualify ready with
  the falling-edge gate's running state, retaining ungated pending-frame demand.
  Follow `docs/frame-admission-contract.md`; 11a2a's native payload/epoch storage
  is digitally verified, with physical qualification still open. Four physical banks retain exactly two logical
  admission credits. R3b native route ownership is digitally verified after
  R3's original completion repair. Each store owns its modulo-four
  route independently of the clocked descriptor ordinal. Receipt ACK changes
  at original acceptance A; publisher ACK joins native copy and receipt only.
  Never gate A or native return on a synchronized copy ACK. Keep full-mailbox
  overflow at A even with same-edge dispatch and capture reset/busy context at A.
  Click's capture C-element retains its pulse until pending falls: changing the
  native route must not retrigger capture through selected-bank availability. Keep
  per-bank Click phases and BD's retained route through RTZ. At O prove complete
  bank availability and a new capture ordinal, including identical payloads;
  copy equality alone is not proof. A may precede native copy; require completed
  head identity at D. Exercise copies longer than two front-clock periods,
  copy-first and A-first orders, stopped front/work clocks and delayed context
  changes. Both ordinals are POR-only, with no instantaneous equality assumed
  at A. Retain original receipt clock dependence and full BD RTZ. Rerun affected
  checks and obtain fresh independent review after changing this contract.
  Retain source epoch through D and compare against the coincident current epoch.
  Queued descriptors awaiting head observation retain priority over CPU MMIO.
  Keep native logical credit removal separate; narrow Q/descriptors, tail, busy
  synchronization and four head receipts remain temporary for 11a2b/11b/14.
  Run AsyncFrameStoreSpec, FrameReceiptSpec, FrameAdmissionSpec and FrameWakeSpec,
  actual 337-bit source/bank and ControlCommand capture controls, all ten Click
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
  indexed playback and registered pins; follow `docs/spi-player-contract.md`.
  Keep highest-occupied-slot behavior, including empty/holey recipes, and all
  source constant/connection checks. Run SpiRecipeReplaySpec at half-periods
  2/3/5 alongside the unchanged wall-clock SpiAdcSpec oracles. Artificial clock
  pauses prove retention, not valid real-time ADC waveforms.
  Preserve all 32 observations, exact half-phases, first-complete-frame discard and busy
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
  The current implementation keeps CLK on the service clock, falling-edge input
  launch, full-cycle Q capture and busy through every crossing's return. The
  user authorizes self-timed macro clocks under A4 in
  `docs/native-area-reduction.md`: qualify all macro pulse/setup/hold/access and
  POR-abort constraints before replacing this boundary. Never substitute a
  guessed request pulse. Isolated experimental byte owners live under each
  design's `experimental/` directory. Run AsyncMacroByteOwnerSpec and
  tools/test_macro_byte_source_binding.py after changes; preserve all 76 cases,
  actual pin/result oracles, exact-fatal controls and source/runtime/graph binding.
  Follow docs/experimental-native-sram-byte.md. Their finite Mutex model and
  schematic candidate do not authorize production use or physical timing claims.
  Preserve the full-width millisecond/scaled-value ABI;
  narrow LF state only with bounded observation/scaler progress, safe retained
  accumulation and wake ownership, or independent retained overflow logic. A3
  retains 32 bits; follow `docs/lf-counter-width-decision.md`. Waking on each tick
  alone is not that bound, and a post-wrap assertion cannot recover a missed wrap.
  Do not call old cycle-offset tests
  exhaustive native phase coverage.
  Offer the full RAM payload independently of valid; admission checks alone
  authorize capture. Strict mapping stimuli may force catalogued source registers,
  never derived endpoints, and must retain generic campaigns and negative controls.
  Keep macro contents uninitialized in simulation; SYNTHESIS must retain physical
  macro instances. Verify upstream asset hashes with tools/sram_assets.py.
  Validate full-width addresses and loader fields before narrowing to internal
  word indices/counts. Include full-capacity counts and small/non-power-of-two banks.
  SRAM saved addresses use log2Ceil(bytes).max(1), with explicit padding before
  macro address and bank selection. Check every actual firing lane at full
  32-bit width, including disabled and read/write requests. Preserve the saved
  owner/tag, falling launch, full-cycle result capture, source reuse, stalls and
  POR. Run SramSavedAddressSpec, SramSpec, CoreSpec, standing affected suites,
  and exact saved-address controls for
  4/12/1024/1028/2048/3072-byte banks in both protocols. Bind all four production
  firing-lane range assertions, held-bus/RDC aliases, strict generic campaigns and actual
  held wiring controls; keep the C1f timing failures and missing coverage open.
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
  The opt-in Control load repair in `tools/repair_gf180_control.py` is bound to
  exact ordinary sink sets. Preserve its whole-graph contraction, unused-net
  alias controls, Verilog round-trip and source custody checks. Follow
  `docs/reviews/control-electrical-repair.md`: numerical data/guard comparisons
  do not replace the unresolved actual capture/ACK, hold or routed envelopes.
  The user authorizes global graph-preserving repair in the default mapper.
  `repair_gf180_design.py` protects native leaves, verifies unchanged native
  pin/port partitions and proves the complete graph after noninverting buffer
  contraction, equivalent ordinary-cell resizing and validated constant ties.
  P&R requires its complete receipt before launch. Keep the old opt-in Control
  experiment as historical evidence. Residual electrical violations still block
  qualification; successful repair execution is not electrical closure.
  The native Control SPICE harness preserves uncut controller feedback and all
  315 payload cells. Follow docs/reviews/control-native-characterization.md:
  reject changed adapter specializations and unexplained cut loads, verify both
  BD returns and Click phases, and require resolved crossing brackets plus
  timestep convergence. Numerical mesh nodes must be electrically disjoint.
  Local ACK/capture observations do not qualify upstream source hold or reset.
  Follow docs/reviews/control-relative-timing.md for conditional Control STA.
  Keep actual request paths, same-instance D/capture pairing, native phase
  CLK-to-Q and common-event hold accounting. Analysis-clock periods must not
  affect results; report actual propagated event slew and verify cross-context
  coverage. Preserve positive-baseline, actual-arc negative controls and source
  custody. Local boundary skew is not measured Join launch alignment. BD pending
  admission/returns, Click pulse/self-hold and electrical/routed envelopes stay
  open. Never shorten guards from this pilot alone or relax digital tests.
  Follow docs/reviews/native-stage-timing.md for canonical-stage reuse. Resolve
  logical metadata through the actual deduplicated hierarchy; validate endpoint
  references, adapter tuples and Verilog/JSON connectivity before STA. Pair D/Q
  and E/CLK by physical storage. Literal lanes keep capture/ACK obligations;
  aliases are not constants. Share controller templates, never load-dependent
  timing numbers. Custom I2cPublication is not covered by I2C update. Require
  actual-arc/period controls for changed widths/guards and static branches;
  pre-existing negative margins cannot count as detected mutation failures.
  Freeze runtime configuration/executables, and use the same runtime for fault
  controls. Configured native/WSL invocation currently covers the stage runner
  and Control relative pilot/controls; legacy physical tools remain separate.
  For Control Join setup composition, follow docs/reviews/control-join-timing.md.
  Resolve the actual parent/children, prove source identity and dynamic-lane
  coverage, and preserve the original loaded cells in the analysis wrapper.
  BD E-falling retains Q; it is not a CLK-to-Q launch. Require already-open
  source latches, per-lane D setup and Q-before-close, loaded D-to-Q slew custody,
  and a measured ACK-after-direct-close ordering check. Condition only physical
  ACK receivers; leave the actual returning driver observable. Click must retain
  actual payload/phase CLK-to-Q and both min/max rising launch slews in both
  phases. Reject missing/reversed bounds and verify exact-arc/period controls.
  This conditional setup envelope does not close reuse, pending/return, pulse,
  simultaneous rendezvous, mismatch, electrical or routed obligations.
  The same Join template supports execute; follow docs/reviews/execute-join-timing.md.
  Validate both source-input provenance and destination reachability. All 480 RF
  bits bypassing the Join remain symbolic and explicitly uncomposed until actual
  bank launch/hold is measured. A destination reached from a Join operand may
  also depend on RF data; union coverage cannot discharge that obligation.
  Preserve the original Control caller's queries and results, and exercise
  graph rejection controls through the actual deduplicated parent. Prioritize
  global electrical repair, then rerun existing campaigns, then RF launch and
  elapsed seeded-owner/admission composition. Safe-direction guard lengthening
  and timing parameterization may proceed concurrently; shortening waits for
  the measured complete envelope. Keep elapsed step and owner policies separate.
  Default elapsed requests are 100 ns, execute requests 80 ns and the BD Control
  source ACK guard 32 ns on both edges. Keep that guard's recognized
  `acknowledge_guard` ID so AsyncTest does not randomize away its fixed delay.
  Run actual-edge/bypass controls plus the unchanged accelerated sleep oracle.
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
  board policy, with inline assertions and v3 contract/port/reset-policy binding. Keep
  the composed Click-policy rejection and exact source inventory. Follow
  `docs/physical-export-contract.md`; old v1/v2 exports require regeneration.
  Standalone PhysicalTiming core tests do not authorize that policy for every
  controller. Constraint coverage and complete physical envelopes remain open.
  The first P&R flow and its open violations are in `docs/gf180-first-pnr.md`.
  Verify supplies even on protected cells; keep SPEF and the extracted ODB names
  consistent. A zero router-violation count is not full DRC/LVS or async signoff.
- Keep generated RTL, tools, simulator logs and test evidence under ignored
  `.tools/`, `build/` or `target/` directories. Pin dependencies and record limits.
- Firmware and memory budgets live in `firmware/`; run FirmwareSpec and the
  firmware Python controls after changing its runtime, workloads or capacities.
  Preserve real I2C uploads, both native variants and independent stack evidence.
- Update README and affected contracts when behavior or implementation status
  changes. Communicate succinctly and distinguish implemented IP from planned IP.
