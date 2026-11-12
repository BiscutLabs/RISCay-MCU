# RISCay-MCU contributor instructions

- Work in this repository, not Chiselator. chisel-async is a separate library.
  Use `.agents/skills/async-circuit-design/SKILL.md` for native architecture,
  timing, area and physical-flow work. Its examples are guidance, not measured
  margins for this design.
- The active rebuild generates multi-bank, four-phase bundled-data logic from
  `designs/clocked`; do not copy that RTL or restore the single-oscillator
  prototype. Follow `docs/desync-contract.md`. Phase 0 tools/reference and the
  deterministic clocked export fix stay. Old BD and Click are frozen behavioral
  oracles, with no new physical campaigns. These rules override historical
  migration instructions below.
  Start with at most ten banks, each with semi-decoupled master/slave controllers,
  joins and a measured matched delay. No shared fast clock, transaction owners,
  payload copies or bridges. The user selected investigation of a CPU flop-bank
  exception to preserve the 1.25x storage-area cap; this is not yet qualified.
  Preserve falling-edge, per-register work gating and reset semantics explicitly.
  The current ten-bank candidate isolates the 42 falling-edge bits. Controller
  candidates restore request-return causality; do not replace that dependency
  with an unmeasured wait or treat sampled schematic pulses as qualification.
  One-sided closure/same-phase qualification and CPU rearm are user-approved;
  their connected experimental map still has explicit unmeasured delay apertures.
  Keep CPU capture on master.A distinct from latch enable N in inventories.
  A positive-edge projected graph is not a whole-chip liveness or timing proof.
  Registry recipes live only in `tools/primitives.py`; missing physical recipes
  and STA-sized delay entries fail. Custom GF180 mutex development is authorized,
  with a 0.001 mm² exploration allowance; do not pass estimates as qualification.
  Its stop/wake reliability target is at most 1 FIT per MCU, as selected by the
  user. Finite SPICE campaigns alone cannot establish that target.
  Ratios against the matched clocked reference govern prototype continuation:
  mapped 1.17x and control share 5.5% (user-approved after b2cac0f),
  repaired plus trees 1.20x, architectural bits exactly 1.00x, storage area 1.25x,
  with timing and production qualification still required. No budget loosening
  without approval. Explore with area maps
  first; qualify only surviving choices. I2C remains 400 kHz SCL; 3.2 MHz is the
  existing service-clock test point, not a bus-rate increase.
- RISCay is a generic MCU. Neither RTL nor mask ROM contains application policy.
  ROM implements generic external SPI image boot and I2C-loader fallback.
  Profiles supply pin names, measurement metadata and capacities, never behavior.
  Groundlark firmware and external board repositories are outside this workstream.
  Follow `docs/generic-boot-contract.md` and `docs/reusable-interface.md`.
- Keep BD and Click as independent implementations under their `designs/`
  directories. Share schemas, ISA, fixed macro models and verification utilities.
  Keep native Click signaling; do not insert hidden four-phase conversions.
- `designs/clocked/` is the independently implemented synchronous comparison
  chip, including its CPU. It shares the current generic MCU ABI and firmware,
  not the async owners or their transport. The no-periodic-clock/native-primitive
  rules below apply to BD/Click; they do not prohibit ordinary synchronous state
  in this explicitly clocked design. Keep clocked verification and timing exports
  distinct from async contracts. Do not revive historical board policy or reset bugs.
  Its raw watchdog reset isolates pads; synchronized cancellation closes the fabric
  and resets the CPU on the same work edge. Accepted SRAM effects drain. Keep
  I2C sampling on the service clock and require a live work edge at host commit.
  Reuse shared chip-test bodies/oracles for the synchronous variant.
- BD is the selected tape-out implementation, subject to physical qualification.
  Architecture conversions keep BD and Click functionally equal unless the user
  explicitly requests an exception. Implement each conversion natively and
  independently in both variants; document temporary internal divergence.
  Click receives functional verification and area/sink accounting, but no new
  physical timing or guard-sizing campaign unless explicitly requested.
- No periodic clock may be added to work around native timing. Keep clocks only
  at documented boundaries: independent LF time/watchdog, physical wire sampling,
  bounded serial pin timing, reset qualification and the event arrival/clear
  arbitration edge, plus documented command/recovery receiving-edge arbitration.
  Event pending, cutoff masking and WAIT remain together in
  Services; no native counters or MUTEX replace that ordering. Experimental self-timed SRAM
  remains isolated until macro pulse/aperture and ownership checks pass.
- Preserve the ABI, programming lock, SRAM retention, watchdog/reset isolation,
  sleep behavior and crash accounting. POR disables GPIO outputs; watchdog GPIO
  retention is a generic option. SPI recovery releases its outputs and requires
  a new bus claim. Never restore profile-owned GPIO masks or policy registers.
- Native request, capture, ACK and full return/rearm own payload lifetimes.
  Acceptance must occur on the actual consumer clock. Borrowed commands remain
  immutable until full sender return, including cancellation/recovery. Preserve
  independently reset close/rebase bridges and their receiving-clock proofs.
  Raw reset is not a synchronous data qualifier. Retain the RDC audit in
  `tools/check_reset_crossings.py` and its proof helpers until typed library
  metadata can express that integration-specific containment proof.
- Resetless payload storage is opt-in and uses a distinct library/model identity.
  Audit every consumer for valid qualification and reset lifetime before adoption;
  keep architectural state, seeded tokens and control state resettable. BD's four
  POR-owned frame-bank payloads are the first audited use; application-lifetime
  adoption requires a separate containment proof. See `docs/resetless-payload-plan.md`.
- Use the source-pinned library in `project/chisel-async-source.json`. Library
  source is an exact-commit sbt dependency; no `publishLocal` is required. Library
  changes need their own tests and review. Public native primitives and their
  contracts own generic structural rules; avoid new Verilog-name-based checkers.

## Verification and delivery

- The active verification entry point is `docs/build-and-test.md`. Run
  `python tools/ci.py --output build/<fresh-run>` for Python properties and fast
  Scala chip simulation. CI runs this on main pushes and pull requests. Run
  affected extended suites for reset, SRAM, I2C, loader and full firmware changes.
  Use one sbt process at a time across MCU and library repositories.
- Keep behavioral tests and their original assertions. A changed implementation
  must not be excused by weakening a deadline, event, retention or fault oracle.
  Test both implementations. Tests should compare actual inventories and
  properties, not historical counts of stages, faults, cells or comparisons.
- Generic generation rules run in chisel-async before contract publication:
  registered primitive/owner identity, driven native outputs, no ordinary
  sequential helpers hidden in a native owner, and no combinational path from
  declared periodic clock inputs to native storage. Divided clocks need explicit
  classification; this audit is not a timing or RDC proof.
- Every current native export uses `tools/check_export.py` to consume that audit without
  modifying generated probes. Physical flows additionally prove the complete
  mapped graph, protected primitives, reviewed keeper arcs and no unused added
  cells. Keep the fixed SRAM model checks. Historical baseline mapping has an
  explicit legacy reader and cannot qualify the current design.
- Keep one or two negative controls per reusable check kind (setup, hold, ACK,
  period invariance, graph preservation), not a new mutation campaign per owner.
  Preserve actual chip-level reset/backpressure/pin tests. The experimental byte
  owner campaign remains a chip test, with expected cases from its live inventory.
- Use one run receipt for inputs, tools, outputs and results. Do not add successor
  approvals, class-file custody inventories or attestations over attestations.
  Keep failed logs. Generated tools, exports, PDKs, binaries and evidence stay out
  of Git. `docs/test-suite-cleanup.md` records retired checks and coverage losses;
  older review documents describe historical evidence, not current gates.
- Obtain a fresh independent agent review for each batch, fix findings, rerun
  affected tests and update the relevant contracts and area ledger. The current
  user workflow is commit and push directly to `main`; do not open a PR unless
  requested. Include the reason, material assumptions and validation in the
  commit body. Do not mark incomplete checks as passed or simulate approval.

## Physical work

- Follow `docs/gf180-guard-sizing.md`, `docs/passive-allowance-contract.md` and
  the skill's timing/physical references. Separate relative ordering, absolute
  pulse/aperture requirements and digital model delays. Engineering mismatch
  derates are not measured process variation.
- Repair electrical violations before timing. Protect native cells and prove the
  full graph after repair. Anchor queries on protected leaf pins, account for
  capture-tree spread, actual loaded slew, source release, ACK and Click rearm.
  Only reviewed primitive-internal keeper arcs may be cut; analysis clocks are
  timing references, not new silicon clocks. No functional path waiver.
- Keep keeper feedback gates and their first isolation buffer compact. Every
  live native output needs an exclusive repairable parent driver; passive aliases
  and truly unused outputs add no cell. Placement clusters alone are insufficient:
  enforce measured geometry and feeder isolation after legalization/repair, then
  check actual extracted loading and noise. Pre-fix routed timing is void as
  recorded in `docs/gf180-routability.md`.
- For hierarchical floorplan comparisons, follow `docs/hierarchical-floorplan.md`:
  separate synthesis hierarchy cost from placement effects, match pins/macros
  and tool inputs. Soft seeds are not fences; bounded regions must retain every
  original cell and verify grouped repair/CTS helpers after legalization.
  Guided placement releases module fences only after a legal checkpoint;
  report later spill/displacement, retaining all native compaction gates.
- Measure same-corner setup/hold/order bounds with complete inventories; missing
  paths and nonfinite values fail. Do not shorten delays on simulation evidence.
  Adopt locally measured reversible counts after affected digital/timing checks
  and review; routed min/max-RC qualification remains migration item 17.
- Keep fixed macro identity, reset distribution, all clock sinks and SRAM clock
  pulse/setup/hold obligations explicit. Do not call zero-wire-RC or digital
  results physical signoff.
- Record mapped/repaired logic, guard/allowance/DLYD area by purpose, clock sinks
  and wake activity in `docs/area-ledger.md`. Compare the immediate parent and
  original baseline. Keep pre-existing P&R work and historical failure evidence.
- Finish A/B external boot slots, external golden recovery, factory provisioning
  and full-capacity boot timing before further area tuning.
- Apply the architecture-first order in `docs/architecture-followups.md` before
  the next BD request-guard campaign. Reserve routed hold-repair area separately;
  insert hold cells only on failing composed min-RC paths and rerun setup/order.
