# RISCay-MCU contributor instructions

- Work in this repository, not Chiselator. chisel-async is a separate library.
  Use `.agents/skills/async-circuit-design/SKILL.md` for native architecture,
  timing, area and physical-flow work. Its examples are guidance, not measured
  margins for this design.
- RISCay is a generic MCU. Neither RTL nor mask ROM contains application policy.
  ROM implements generic external SPI image boot and I2C-loader fallback.
  Profiles supply pin names, measurement metadata and capacities, never behavior.
  Groundlark firmware and external board repositories are outside this workstream.
  Follow `docs/generic-boot-contract.md` and `docs/reusable-interface.md`.
- Keep BD and Click as independent implementations under their `designs/`
  directories. Share schemas, ISA, fixed macro models and verification utilities.
  Keep native Click signaling; do not insert hidden four-phase conversions.
- No periodic clock may be added to work around native timing. Keep clocks only
  at documented boundaries: independent LF time/watchdog, physical wire sampling,
  bounded serial pin timing and reset qualification. Experimental self-timed SRAM
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
- Use the source-pinned library in `project/chisel-async-source.json`. Library
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
- Every current export uses `tools/check_export.py` to consume that audit without
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
  requested. Do not mark incomplete checks as passed or simulate approval.

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
