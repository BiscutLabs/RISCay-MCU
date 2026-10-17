# Native area reduction plan

The proposal against `c71b234` is authorized for implementation, subject to
the existing ABI, reset, retention and independent-review requirements. Its
area estimates and target of roughly halving logic area are hypotheses, not
mapped results. Keep native BD and Click; do not replace native work with
periodic-clock staging. Measure each accepted step against its exact parent.

## Order and acceptance gates

- [x] **C1g: snapshot consumer-clock acceptance, digitally verified.** Qualify the service
  receipt using the actual work-clock running state. Keep acceptance independent
  of frame-only stalls, retain native request/data until capture and prove ACK
  on the actual capture edge. Include real read-from-sleep and deliberately
  stopped-consumer tests. This hardens an implicit invariant; the source review
  did not demonstrate a reachable production loss. The completed tests, strict
  exports and matched cost are recorded in
  [the capture contract](held-peripheral-capture-contract.md#snapshot-consumer-clock-c1g).
- [x] **A1: shrink elapsed arithmetic without changing the time ABI (proposal 2), digitally verified.**
  A1a's unused old-consumed context removal is digitally verified below: three
  native work stores narrow from 252 to 220 bits. A1b replaces the unrolled
  arithmetic with a bounded native nibble loop and leading-zero skip. Its digital
  checks and matched measurement pass; physical timing remains open. See
  [its contract](native-elapsed-contract.md).
  It reuses one four-bit transform for one through eight arithmetic turns.
  Preserve exact full-width deltas, fractional accumulation,
  wrap, stalled publication, `single` freshness and consumedGray ownership.
  Current code already computes coefficients at elaboration and contains no
  hardware division operator: its cost is unrolled quotient/remainder logic.
  Never catch up by repeating once per delta tick: valid deltas include
  `0xffffffff`. Native Click feedback must not use phase-adapting library
  TwoPhaseMux/Merge. Preserve nominal milliseconds and published scaled ADC
  values; internal raw/tick policy requires equivalence of boundary conversion
  and conservative rounding. Specialize integer/duplicate coefficients only
  while preserving all generic positive parameter configurations.
- [x] **A2a: reduce CRC token storage and arithmetic (proposal 6 / C2), digitally verified.**
  Matched comparison selects one narrow whole-word XOR stage over a wide stage
  or byte loop. The existing update owner retains command context through native
  request/return rendezvous. Independent CRC32 oracles, Stored-only accounting
  and loader/reset/lock semantics pass; physical timing remains open. That
  change preserved retained metadata widths; see [the contract](native-crc-contract.md).
- [x] **A2b: capacity-sized retained loader metadata — digitally verified; matched cost recorded; physical timing open.**
  Separate review covers the capacity-derived state/token/reply layouts, complete
  host validation and matched measurement. At 2 KiB, length/received/entry retain
  12/12/11 bits. Full-capacity counts remain representable and external host fields
  remain 32 bits. See [the evidence below](#a2b-capacity-sized-loader-metadata).
- [x] **A3: prove LF narrowing, or retain width (proposal 8): retain 32 bits.** Wake on each tick
  does not prove a maximum observation/progress gap. An 8/10-bit count can
  wrap in 256/1024 ms in 1 kHz fixtures, or 21.3/85.3 s at production's fastest
  12 Hz. A post-wrap assertion in the stalled service domain cannot detect a
  full missed wrap. Require bounded observation/scaler progress with safe elapsed
  accumulation and wake ownership, or independent retained overflow/fault handling,
  before reducing the current tolerance. A bound through final Housekeeping
  publication is sufficient but stronger than necessary. The reviewed decision
  changes no hardware and claims no area or power saving; see the
  [LF width decision](lf-counter-width-decision.md). Narrowing can be reopened
  with the missing proof without blocking independent reductions.
- [ ] **A4: self-timed SRAM macro access (proposal 1).** The user authorizes
  reversing the service-clock-only rule after a concrete timing proof. First
  characterize the pinned macro across every available PVT corner: CLK high/low,
  all A/D/CEN/GWEN/WEN setup and hold, CLK-to-Q, load/slew and reset/abort behavior.
  Design separate native BD/Click word owners and byte loops with one retained
  request and assembled result, rather than four full-width lane tokens. An
  internally generated macro pulse is still a real timed clock at the macro.
  Prove no runt/double pulse or idle CEN glitch and POR-safe quiescence, including
  POR during the pulse. Keep SRAM contents and accepted effects retained through
  application reset. Do not change the production macro clock until these
  physical constraints and all lane/mask/back-to-back/loader tests are covered.
  The reviewed [macro preflight](native-sram-clock-contract.md) is complete;
  an isolated digital byte-owner experiment can use the public Mutex model now.
  The approved [library work](mutex-physical-binding-proposal.md) merged in
  [chisel-async PR #4](https://github.com/BiscutLabs/chisel-async/pull/4), reaching
  library main `1e74a5c` after Windows and Linux qualification passed. It adds
  ownership/reset contracts, digital tests and an experimental GF180 schematic
  cell. Layout, extraction, Liberty and reliability qualification remain open.
  The MCU retains its RC1 dependency and unchanged generic mapper.
  Neither this schematic experiment nor the byte-owner tests qualify SRAM pins.
- [ ] **A5: addressed native I2C byte storage (proposal 4).** Move frame bytes
  out of the per-edge state/observation token, publish completed bank identity
  and keep immutable ownership through both copy and admission/dispatch. Reduce
  readWord transport only after proving per-edge byte selection across word
  boundaries. Replace accepted-descriptor epochs with sticky stale history only
  after checking every reset ordering; pre-acceptance epoch narrowing requires
  an actual worst-case latency bound, including stopped consumers and POR-only
  work. Preserve two logical credits, native bank rotation, overflow and reset/
  busy context at their original linearization points.
  A5a is digitally verified: it narrows only the redundant observation from 340
  to 15 native bits; its measured cost and evidence are recorded below. It does not move
  the per-edge byte buffer or remove frame publication storage. A5b's addressed
  receive store is digitally verified and measured, removing 513 native bits
  per variant. See the [receive-byte contract](native-i2c-byte-store-contract.md).
  Publication/bank, sampled readWord and reset-epoch reductions remain open.
- [ ] **A6: widths and duplicate ownership (proposal 7 / C1d–f).** Evaluate the
  fixed SPI player, quiescing request receipt, saved SRAM address, profile-sized
  GPIO/wake fields and bounded statistics. Remove queued/ordered/bridge copies
  together with their ownership, preserving ordering and independent stalls.
  Audit verification-only payload and dontTouch retention. Any trace-disabled
  physical export must be an explicit configuration compared on both sides,
  retain verification builds and keep architectural/debug interface obligations
  explicit; do not silently prune a live output to improve area figures.
  C1d's compact SPI player is digitally verified and measured: 90 fewer periodic
  bits per variant, with unchanged wake activity. See the [player contract](spi-player-contract.md).
  See its [matched cost and timing evidence](spi-player-contract.md).
  C1f saves 43 periodic RTL bits per variant in the SRAM controllers under
  upstream full-width admission validation and retained firing-lane assertions. Matched logic area changes -0.1878% BD /
  -0.0782% Click; complete state, whole cost, 27-window activity and
  five-corner controller timing results are in the
  [SRAM contract](sram-integration.md#c1f-saved-address-narrowing). Preserve every
  physical violation and missing check; Click FF125 high listed-state leakage
  increases 0.231845076 µW despite lower area. C1e1 removes the 70-bit CPU
  request copy with a masked retained-bus receipt. Compiled inventories confirm
  70 fewer periodic bits per variant; matched logic area falls 0.2404% BD /
  0.2999% Click and every wake window is unchanged. Digital verification and
  independent review are recorded in the
  [request contract](application-reset-boundary.md#c1e1-retained-cpu-request-receipt).
  A2b separately narrows retained loader metadata under the capacity and
  full-host-validation contract above; see its [measured scope](#a2b-capacity-sized-loader-metadata).
  C1e2 keeps the six smaller receivers and their ten mapped payload bits open.
  Native source, mask-removal hold and physical clock/reset/RC qualification
  remain separate gates; C1e and the other A6 candidates are not complete.
- [ ] **A7: replace guards with proved completion (proposal 3 / R5).** Record each
  guard's ordering/hold/reset obligation. Replace it only with completion that
  proves that obligation under skew, backpressure, phase return and reset. Keep
  guard-removal fault controls; account for the cells and energy of retained
  delays. Synchronous STA complaints alone are not grounds to add registers or
  waive real timing.
  - [x] **A7a: refresh component costs and triage every mapped control adapter.**
    The 11b1 inventory below distinguishes functional cells, ordering guards and
    combined ordering/pulse/reset obligations. This is a purpose inventory, not
    permission to shorten any chain.
  - [ ] **A7b: size ordering guards against the same-corner requirement.** Use
    complete launch/data/capture/ACK/return paths, loaded rise/fall slews, wire RC
    and a justified mismatch derate. Keep physical minimum pulses and external
    time requirements as separate constraints. Begin with an already composed
    standard owner; retain the old recipe as the matched comparison.
  - [ ] **A7c: compare mixed-cell tracking with the existing DLYD recipe.**
    Characterize the actual chain at every corner, including interstage loading
    and slew. A paper's average tracking error is not a GF180 mismatch bound.
- [ ] **A8: qualify transform data allowances (proposal 5).** First count mapped
  leaf cells under each data_delay, separately from actual control delays. A
  library change may make an allowance a passive timing annotation only when
  exact upstream/capture endpoints, reset semantics and bundling checks replace
  the current active mapping. Do not remove reset gates or per-bit buffers on
  the assumption that every source/storage path already supplies their behavior.
  Keep mandatory export coverage and digital model obligations intact. Present
  the concrete library contract change for review before upstreaming it.
  - [x] **A8a: refresh the actual leaf inventory.** The current counts below
    supersede the C1g counts for this configuration; named `data_delay` is a
    subset of all transform allowances, not an additional saving.
  - [ ] **A8b: present a passive-allowance contract and one-owner experiment.**
    Specify invalid-data use, reset observability, resolved transform endpoints,
    actual capture/ACK pins and mandatory max/min checks. Preserve explicit
    masks where reset isolation requires them. Run unknown-payload/reset and
    immediate-source-reuse controls, then remap with any required hold repair.
    This needs matching library/model semantics, not a mapper-only bypass.
- [ ] **A9: reset-free payload storage, by owner.** Separate seeded state,
  phase/control, architectural reset values and payload whose consumers are
  valid-qualified. Prove read-before-write exclusion and both reset lifetimes
  before removing payload reset. BD already mostly uses latches; see the counts
  below. Event-triggered storage cannot be replaced by a transparent latch
  without redesigning its controller and proving transparency/closure/hold.
  Keep native Click. A MOUSETRAP implementation would be a separately reviewed
  library primitive/target, not a silent replacement of Click.
- [ ] **A10: fuse pass-through owners.** Inventory unchanged payload copies with
  producer, consumer, lifetime, independent stall, reset and arbitration reasons.
  Remove a copy and its controller/guards/crossings together where ownership
  allows it; do not assume all FIFOs are redundant. Continue 11b–14, including
  Housekeeping's existing-bank reuse, alongside A7/A8's measured experiments.
- [ ] **A11: bulk SRAM and serial datapaths.** Evaluate frame/RF placement only
  with an explicit capacity/port/concurrency budget and A4's qualified native
  access. Do not consume advertised application SRAM silently or change loader
  lock, retention or ABI. Charge extra macro accesses and wake duration against
  the removed logic. Firmware may perform optional formatting, but permanent
  time/age/power supervision must progress with the application CPU stalled,
  asleep or reset; immutable boot ROM alone does not establish independence.

## Current area priorities (11b1, 2026-10-17)

The review correctly identifies implementation overhead as the target. With
11b1 digitally verified and independently reviewed, use A7a/A8a to select a bounded
guard or passive-allowance experiment with the largest supported saving. Keep ownership removal
in 11b–14 active; further broad repair sweeps are lower priority. Every change
still needs its own matched map, activity and leakage comparison. The proposed
40–50% reduction is a hypothesis, not a measured result or a tape-out target.

This inventory uses the **current repaired pre-placement graphs**, pinned GF180
LEF sizes and exact preserved adapter leaves. It is neither routed area nor die
area. `build/control-frame-borrow/current_native_cost.py` records its procedure;
`current-native-cost.json` binds mapping, audit, netlist, LEF and helper hashes.
Independent review reconstructed every row and all 56,128 BD / 61,309 Click
preserved leaves without overlap.

| Component | BD | Click |
| --- | ---: | ---: |
| Repaired logic excluding SRAM, mm² | 3.014986 | 3.795762 |
| All matched-control-role adapters, mm² | 0.584674 | 1.115429 |
| Of which 1 ns functional adapters, mm² | 0.042521 | 0.053598 |
| All transform-allowance adapters, mm² | 0.413624 | 0.366484 |
| Named `data_delay` subset, mm² | 0.353484 | 0.354077 |
| Named `data_delay` lanes | 10,517 | 10,538 |
| ClosingLatch storage cells | 10,091 | 0 |
| EventRegister storage cells | 1,180 | 11,323 |
| PhaseRegister storage cells | 0 | 101 |
| Periodic clock sinks (including three SRAM macros) | 5,072 | 5,127 |

Control plus transform adapters occupy 33.1% / 39.0% of repaired logic. These
are component costs, not proven removable area. Control-role adapters include
functional Boolean gates; DLYD leaves alone occupy 0.536041 / 1.052901 mm².
Storage-class counts exclude C-element/keeper state. Adapter costs exclude
parent-side repair and CTS, and latch counts do not imply reset-free mapping.
The separate SDA event sink is not included in periodic clock counts.
The older 13,733-lane and 0.457 mm² allowance figures predate several reductions.
Elapsed/CRC and I2C reductions already implemented cannot be counted again.

`classify_guards.py` and `guard-purpose.{csv,json}` record a first purpose pass
for all **1,161** control adapters (498 BD / 663 Click), retaining every instance,
owner/ID, width, model delay and area. None is marked qualified for shortening:

| Purpose group | BD instances | Click instances | Required proof |
| --- | ---: | ---: | --- |
| Functional/feedback adapters at the 1 ns model | 268 | 346 | Preserve Boolean/reset behavior and feedback ordering; not a removable wait |
| Ordering | 199 | 3 | Same-corner launch, transform, capture, hold and return composition |
| Combined ordering with pulse/reset obligations | 31 | 314 | Ordering plus minimum capture pulse, phase drainage and reset containment |

The owner/ID families are classified as follows. Numeric suffixes identify
instances, not different physical qualifications.

| Owner / IDs | Ordering purpose and additional obligations |
| --- | --- |
| BD Stage/LongHoldBuffer `request_delay`, `output_delay` | Data before closure; captured data before publication; source release and long-hold return remain composed obligations |
| Click Stage/Buffer/PhaseDecoupledBuffer `request_delay`, `output_guard`, `acknowledge_guard` | Data before event; payload/phase settled and pulse drained before publication or source reuse |
| InitialTokens `request_delay` | Seed valid before admission, including reset release |
| Core `request_guard`; BD Control `acknowledge_guard` | RF writeback before next launch; source release after latest capture/hold |
| FrameStore `request_delay`, BD `request_guard`/`return_guard`, Click output/ACK guards | Native route before selected capture; bank capture before publication; internal feedback returned before reuse; Click pulse width |
| I2cPublication request/output/return/ACK guards | Capture before frame/snapshot publication and source reuse, including feedback pulse and reset |
| Fabric/Completion request/output/return/ACK guards | Selection and data before capture; latest capture and complete phase drainage before source/output reuse |
| RAM/Program/Publication Source request/output/return/ACK guards, `stored_request_delay` | Arm before grant, decision before retirement, publication/Stored identity, capture and cleanup; persistent roles across application reset |
| RAM/Program Return request/output/return/ACK guards | Input/permission capture, arm before use, source hold, completion capture and cleanup; application/POR isolation |
| RecoveryReturn request/return/ACK guards | Admit/issue/complete proof once, clear debt before reuse, preserve phase/reset history |

These are largely relative-ordering problems, but a binary “ordering or fixed
time” label would hide mixed obligations. POR hold counters, watchdog/LF time,
I/O waveforms and SRAM pin minima are outside this ControlGate inventory and
retain independent physical time constraints. All adapters also have reset
propagation obligations. A 645 ns slow-corner result for a 100 ns model does
not itself establish 6.45× removable delay: the corresponding data/control cone
also changes at that corner. Require each corner's complete inequality before
shortening, including rising and falling transitions and min/max wire RC.

For a repeated-cell chain, taking the maximum required count across same-corner
requirement/delay ratios is a starting estimate. Final acceptance uses actual
loaded chain STA because stage delay changes with slew, load and wiring. Mixed
cells are worth evaluating: the [ASYNC 2017 delay-line study](https://www.cs.upc.edu/~jordicf/gavina/BIB/files/Async2017_DelayLines.pdf)
reports about 1% average tracking error in its experiments, using a commercial
65 nm library and 22 PVT/interconnect corners. That is not a worst-case GF180
on-chip-variation allowance. [Desynchronization](https://courses.e-ce.uth.gr/CE664/papers/De-Synchronisation/DESYNC-TCAD.pdf)
supports low-overhead asynchronous pipelines, not a universal area ratio for
this MCU. [MOUSETRAP](https://courses.e-ce.uth.gr/CE664/papers/Template-Based/mousetrap.pdf)
uses a different latch controller with explicit data-overrun/closure timing;
it does not make an EventRegister-to-latch substitution behavior-preserving.

## Evidence required per completed step

Record native and periodic-clocked state separately, mapped logic and guard
area, the same TT leakage method with its state assumptions, all matched wake
window durations and work-clock edges, and source/export/tool hashes. Include
both variants, the real workload and retained old failures. Bit counts alone
are not area or energy measurements. Fresh review, fixes, affected regressions,
strict exports, documentation, commit and push complete each item. Physical
timing, reset distribution and reachable standby energy remain separate gates.

The LF source/watchdog, bounded wire sampling, timed SPI pins and safe reset
coordination retain their independent progress obligations. The service
oscillator cannot be declared unnecessary until every remaining client is
removed or independently clocked. Services scheduling remains a later native
ownership change; optimizing SRAM alone does not remove it.

## Initial mapped allowance inventory

The C1g mapped netlists provide A8's preliminary component count. The audit
resolves each preserved adapter to actual mapped leaves and uses pinned TT
Liberty cell areas, separately from matched control-delay chains.

| Component | BD | Click |
| --- | ---: | ---: |
| Instances with primitive ID `data_delay` | 104 | 104 |
| Data lanes in those instances | 13,733 | 13,756 |
| Actual cells beneath those instances | 28,595 | 28,643 |
| Their cell area (mm²) | 0.457207 | 0.457976 |
| All whole-transform allowance area, including other IDs (mm²) | 0.513383 | 0.461567 |

Each named lane has an AND reset gate and buffer; the totals also include
shared reset inversion/distribution. This is existing component cost, not a
claim that all these cells can be removed. Reset behavior, endpoint resolution
and complete physical bundling still gate passive mapping. Evidence:
`build/async-snapshot-clock-qualification/transform-cells-r1.json` and its
hashed `count_transform_cells.py` audit.

## A1a: unused elapsed context removed

Digitally verified against parent `368b342`. Both implementations use the old
consumed count only when preparing the tick delta. The three intermediate
native work stores now retain the fractional state without that unused 32-bit
field: 252→220 bits each for the production three-lane configuration. This
removes 96 native payload bits and 96 data-allowance lanes per variant. Surviving
transform cones, output schema, fractional arithmetic, public ABI, handshake,
reset ownership and timing parameters are unchanged. No periodic state is
added or removed. The bounded arithmetic replacement is recorded separately as A1b.

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Logic area excluding SRAM (mm²) | 3.292872 → 3.284733 | 4.149929 → 4.139201 |
| Logic area reduction | 0.2472% | 0.2585% |
| TT listed-state leakage including SRAM (µW) | 8.606112–11.228103 → 8.585811–11.201928 | 10.300147–13.960620 → 10.272885–13.919129 |
| Matched guard area (mm²) | 0.594065 → 0.594065 | 1.146281 → 1.146281 |
| Portable periodic RTL bits | 6,000 → 6,000 | 6,001 → 6,001 |
| Firmware work-clock edges per 43-instruction wake | 3,256 → 3,256 | 3,161 → 3,161 |

Physical exports retain 6,010/6,011 periodic bits. The same mapper, binaries,
physical policy and pinned five-corner Liberty accounting are used on both
sides. All periodic storage clock-pin loads remain unchanged. The mapped
reduction is 306 cells for BD and 289 for Click; both remove 306 preserved native
cells, with 17 extra ordinary cells in Click's remapped combinational logic.
All 27 matched wake windows per variant retain their ordering, counts and
duration. Firmware windows remain 271,691.173 ns BD / 263,774.443 ns Click.
Leakage is a listed-state envelope, not measured reachable standby power;
unchanged clock activity is not an energy measurement. Physical capture/reset
distribution and complete routed timing remain unqualified.

Completed evidence is under `build/async-elapsed-context-reduction/`. The
focused arithmetic/physical and composed regression runs pass 195 distinct
ScalaTest cases, including both core references, retained sleep, permanent
supervision, loader/firmware and actual snapshot-clock capture; 468 Python
tests pass. All four strict SoC exports pass with sleep-clock background and
three SRAMs: BD 802,700,736 portable / 802,917,776 physical mapping checks;
Click 697,401,074 / 697,596,754. Independent exact-delta review verifies every
surviving transform cone and all four mandatory generic campaigns. Reduced
coverage counts follow only the 96 removed payload bits and 96 data-allowance
lanes, not exemptions.

The hash-bound receipts are `export-delta-r1.json`,
`mapped-cost-review-r1/receipt.json`, `review-cost-summary-r1.json`, `activity-r1-receipt.json`,
`review-final-r1.json` and `final-evidence-r1.json`. The prepared export-auditor
controls reject the old exports as lacking the claimed reduction; incomplete
preflight evidence and all earlier failure records remain retained. The first
two activity-auditor attempts rejected the fixed SRAM's conditional declarations
and the exact firtool resource wrapper. Their logs remain; the corrected audit
resolves every compiled elapsed model uniquely and matches primitive bytes to
the manifest's pinned resource hashes, allowing only that exact exporter wrapper.

## A1b: bounded native elapsed loop

Digitally verified against parent `0f6e26f`. A1b replaces four unrolled eight-bit transforms with a seeded native
owner and one four-bit transform. Leading-zero skip bounds every unsigned
32-bit delta to one through eight arithmetic turns. Full-width targets, exact
fractional accumulation, the millisecond ABI, publication ownership and separate
BD/Click handshake histories are preserved. See the
[elapsed contract](native-elapsed-contract.md). Functional verification, strict
exports and matched cost/activity audits pass; physical qualification remains open.

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Logic area excluding SRAM (mm²) | 3.284733 → 3.102377 | 4.139201 → 3.915477 |
| Logic area reduction | 5.5516% | 5.4050% |
| Mapped leaf cells, including three SRAMs | 120,770 → 112,677 | 122,775 → 113,495 |
| TT listed-state leakage including SRAM (µW) | 8.585811–11.201928 → 8.176051–10.596532 | 10.272885–13.919129 → 9.763012–13.152871 |
| Elapsed matched-guard area (mm²) | 0.022062 → 0.006889 | 0.035325 → 0.010010 |
| Elapsed native payload + custom history bits | 975 → 458 | 975 → 456 |
| Portable periodic RTL bits | 6,000 → 6,000 | 6,001 → 6,001 |
| Firmware work-clock edges per 43-instruction wake | 3,256 → 3,255 | 3,161 → 3,160 |

The matched mapper uses exact parent `0f6e26f`, the same binaries, physical
policy and five pinned Liberty corners. Unrelated native cells and guards,
three SRAMs, periodic storage and its clock-pin capacitance are unchanged.
Physical exports retain 6,010/6,011 periodic bits. Both variants retain all
27 wake windows in the same order, with the same classes and effects; each
window loses one fast/work edge and 83.334 ns. Firmware wake durations become
271,607.839 ns BD / 263,691.109 ns Click. This is native-model activity, not
measured wake energy. Listed-state leakage is not reachable standby power.

The native-bit row counts payload storage and A1b's two custom history bits,
excluding C-elements, other control memory and delay-model variables. Click's
separate primitive phase-history bits fall from eight to three. Total matched
guard area falls from 0.594065 to 0.578892 mm² BD and from 1.146281 to
1.120966 mm² Click; only the elapsed subtree changes.

Whole-transform physical timing remains **open and failing**: the new step
measures 141.627808 ns BD / 127.252151 ns Click against the unchanged 10 ns
data allowance; BD's conservative merge path measures 90.335281 ns. The prior
unrolled arithmetic also failed its allowance. Local adapter checks do not
close complete capture, earliest release, reset distribution or routed timing.
No periodic-clock stage or timing exemption was added to obtain a digital pass.

Evidence is retained under `build/async-elapsed-loop/`. Functional runs cover
206 distinct ScalaTest cases, including 11 new elapsed-loop cases, and 500
Python tests. Actual-pin capture checks pass 367 cases: 159 original seed
replays, 162 opposing-delay cases, 27 legal-distribution cases and 19 exact-fatal
controls. Arithmetic controls retain four passing baselines and ten exact-fatal
mutants. Each portable export also passes 126 structural negative controls and
12 compiled wiring mutants for its held-payload receivers. These supplementary
campaigns do not replace the four mandatory generic export campaigns.

All four strict SoC exports pass with sleep-clock background and three SRAMs:
BD 764,607,360 portable / 764,819,280 physical mapping checks; Click
659,440,575 / 659,631,375. Each retains all four mandatory generic campaigns.
The export audit binds their actual executed probes, binaries, source files,
reset-crossing checks and logs. Reduced check totals follow the changed native
topology and widths; no mandatory campaign or dynamic-polarity requirement was
removed. Independent review and acceptance records are `review-final-r1.json`
and `final-evidence-r1.json`; the constituent receipts are `mapped-cost-r2/receipt.json`,
`state-r2.json`, `activity-r2-receipt.json`, `exports-r2.json`,
`capture-r7/seal.json`, `arithmetic-controls/r7/seal.json` and
`physical-diagnostics-r2.json`.

Earlier failures remain in the evidence directory: an unsized history wire,
an unsupported dynamic packed index, invalid metadata references, an outdated
held-receipt source catalogue, and new BD stimulus that reused data before full
return-to-zero. Implementation or new-fixture fixes preserve the original
functional oracles. The broad regression predates only the local metadata-alias
repair; `rtl-alias-equivalence-r2.json` proves every emitted HDL file is identical
apart from comments/formatting. The final focused/activity runs use the repaired
source. The older r6 capture receipt is not final source attestation: its source
inventory was written after a test edit. The final r7 cohort is freshly generated
and rejects sources newer than generation.

## A2a: narrow whole-word CRC feedback

Digitally verified against parent `7bb7b71`. Separate native
BD and Click stages compute the fixed reflected CRC32 transform and retain one
32-bit candidate. The existing update owner holds the full context through
native request/return rendezvous. Only Stored commits the candidate. Four
337-bit CRC stores become one 32-bit result store, removing 1,316 native payload
bits per variant. See the [CRC contract](native-crc-contract.md).

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Logic area excluding SRAM (mm²) | 3.102377 → 2.975227 | 3.915477 → 3.748168 |
| Logic area reduction | 4.0985% | 4.2730% |
| Mapped leaf cells, including three SRAMs | 112,677 → 107,992 | 113,495 → 108,714 |
| TT listed-state leakage including SRAM (µW) | 8.176051–10.596532 → 7.864666–10.202253 | 9.763012–13.152871 → 9.346913–12.543369 |
| Control native payload storage (bits) | 2,777 → 1,461 | 2,777 → 1,461 |
| Portable periodic RTL bits | 6,000 → 6,000 | 6,001 → 6,001 |
| Firmware work-clock edges per 43-instruction wake | 3,255 → 3,255 | 3,160 → 3,160 |

The same mapper and five-corner accounting bind both sides. Physical exports
retain 6,010/6,011 periodic bits and three SRAMs. Control alone saves
0.126165/0.167983 mm²; unrelated ordinary mapper variation contributes
−0.000986/+0.000674 mm². Unrelated native cells and guards stay unchanged.
Control's matched guards lose 0.008930/0.015015 mm². Mapped periodic storage
and clock-pin loads remain unchanged. All 27 matched wake windows per variant
retain identical classes, effects, edge counts and durations. Firmware windows
remain 271,607.839 ns BD / 263,691.109 ns Click. These are native-model activity
and listed-state leakage measurements, not reachable standby power or wake energy.

The selected narrow candidate is smaller than both the wide whole-word stage
and narrow byte-loop candidates. Production RTL and mapped cell connections
match that selected candidate exactly. Its measured CRC transform remains
**open and failing**: 16.025093 ns BD / 16.021669 ns Click against the unchanged
10 ns data allowance. The prior CRC path also failed. Complete context/candidate
capture, both rendezvous returns, earliest release, reset distribution and routed
timing remain unqualified. No periodic pipeline or timing exemption is added.

Static, export and activity evidence is retained under
`build/async-crc-reduction/`: `mapped-cost-r1/receipt.json`, `state-r1.json`,
`exports-r1.json`, `activity-r1-receipt.json`, `timing-bound-r1.json` and
`measurement-seal-r1.json`. All four strict SoC exports pass with sleep-clock
background and three SRAMs: BD 701,002,176 portable / 701,211,856 physical
mapping checks; Click 602,477,320 / 602,666,120. Every export retains all four
mandatory generic campaigns. The removed CRC stores and changed topology
explain reduced check totals; no dynamic-polarity exemption is introduced.
Functional/physical runs pass 230 distinct ScalaTest cases and 500 Python tests.
The directed context campaign covers 15 fixtures and 45 seed runs, including
both Click phases and independent BD return. Actual rendezvous controls pass
27 original replays and reject 27 isolated input faults at their exact first
fatal sites, with unchanged testbenches. Fresh independent review and the final
source/evidence inventory are recorded in `review-final-r1.json` and
`final-evidence-r1.json`; controls are sealed in `gate-controls/r1/seal.json`.
The failed focused r2 compilation remains in its original log: a new test
constant shadowed ScalaTest's `pending` member. Renaming the constant preserved
the implementation and expected values; focused r3 passes. Retained loader
length/entry/count narrowing is A2b under A6.

## A2b: capacity-sized loader metadata

Acceptance: **digitally verified; matched cost recorded; physical timing open**. The matched baseline is accepted C1e1
`64e6211`; RTL and compiled classes at paused checkpoint `3183a54` are
unchanged during resumption. The export checker has a separately reviewed
successor described in the completion report. Separate BD/Click Control implementations validate full
32-bit host fields before retaining capacity-sized metadata. At 2 KiB,
state/token/reply widths change 305/337/376 → 244/276/315. CRC arithmetic,
native handshake topology, public ABI and reset ownership are unchanged.

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Logic area excluding SRAM (mm²) | 2.862584704 → 2.8309672384 | 3.629653440 → 3.5965234816 |
| Logic area change | -1.1045% | -0.9128% |
| Mapped leaves including SRAM | 103,349 → 102,006 | 105,247 → 104,089 |
| Native payload bits removed | 183 | 183 |
| Periodic bits removed | 40 | 40 |
| TT listed-state leakage including SRAM (µW) | 7.577419–9.818140 → 7.496075–9.710117 | 9.043886–12.090826 → 8.961381–11.964312 |
| Firmware work edges per 43-instruction wake | 3,255 → 3255 | 3,160 → 3160 |

The mapped work-clock inventory falls from 4,068 to 4,009 storage-cell inputs in BD and from 4,119 to 4,060 in Click. Pin-only clock capacitance falls from 14.378128 to 14.183811 pF and from 14.549554 to 14.355237 pF, respectively. The complete fanout inventory reports 43 to 43 BD and 46 to 42 Click nets exceeding a listed pin-capacitance limit; wire RC, slew and the full capture/hold aperture remain unqualified.

All 27 ordinal wake windows per variant remain unchanged; the 43-instruction firmware wakes still use 3,255 BD / 3,160 Click work-clock edges. All 27 ordinal windows per variant retain their
independent effect and duration checks; any change belongs in the activity
receipt. Five-corner listed-state leakage is recorded in
[the estimates](gf180-estimates.md). This is unplaced mapped cost and
native-model activity, not measured deep-sleep power or wake energy.

The retained generation passes 536 Scala tests across 36 suites. The
checker successor passes 751 Python controls; the original 709-test
receipt remains historical evidence. The twelve capacity cases cover both variants at
4/12/1024/1028/2048/3072 bytes. CRC controls pass 27 originals and reject
27 mutants at their intended first fatal with unchanged oracles.
All four portable/physical BD/Click strict exports pass, each retaining all four mandatory sweep campaigns. Held-payload controls pass 520 structural negative cases, four actual-wiring baselines and 48 exact wiring faults.

All four actual export graphs pass their baseline audits and reject all 304 exact negative controls. The process replay uses the identical reviewed worker and complete cohort.

The bounded screen records all 100 selected input-to-payload-D queries across 20 baseline/candidate, BD/Click and five-corner cases. All queries resolve; 28 exceed the unchanged 10 ns budget: every Control update case and both slow-corner CRC cases for each side/variant. The largest reported update propagation changes from 58.590066 to 51.492380 ns in BD and from 33.859032 to 37.777405 ns in Click. Click's selected update path worsens at all five corners; that regression remains explicitly open. CRC results are unchanged, reaching 16.852150 ns BD / 16.849191 ns Click. These are selected worst-slack paths with source arrival subtracted, not a proof of maximum propagation over all paths. No clocks, false paths, case analysis, loop cuts or timing waivers were added. Existing CRC and other transform data-budget
failures remain failures. Native payload reuse/hold, request alignment,
capture/reset pulse widths, reset distribution, electrical limits and
routed min/max RC remain unqualified. No periodic staging, timing waiver
or relaxed behavioral oracle is introduced. The retained user-interrupted
strict attempt remains `FAIL_OR_INCOMPLETE`; successor evidence is
separate under `build/async-loader-width-finish-r2/`. The failed r1
activity probe and paired-fallback MemoryError remain retained. See
[the completion report](reviews/loader-metadata-a2b-completion.md).

## A4 progress and physical gates

- [x] **A4a: fixed-macro preflight and ownership contract.** Preserve the eleven
  pinned assets. Five-corner checks reproduce 640 input/output timing reports
  and 45 intended violations. Full-macro SPICE produced no functional measurement;
  all failed/timed-out attempts remain evidence. The revised admission proposal
  separates bootstrap reset, retained stop, source quiescence and rearm. Independent
  review reproduces seven public-Mutex model probes and two exact wiring faults,
  with two additional witnesses for old-request replay and premature reuse.
  These checks contain no byte owner or actual SRAM-pin coverage.
- [x] **A4b: isolated BD/Click native byte owners.** Separate experimental owners
  use the unchanged public Mutex digital model, with no production instantiation.
  The maintained test freshly emits both variants and passes 76 cases: 20 positive,
  54 exact-fatal controls and two deliberate monitor-omission witnesses. Actual
  macro/receiver pins, source ownership, pulse completion, independent returns,
  held results and stop/rearm are checked. Grant low precedes contender reuse;
  old requests clear before reset release. No periodic pipeline or four-phase
  Click wrapper is added. The 47 source/runtime/graph binding tests pass.
  See the [experimental byte-owner contract](experimental-native-sram-byte.md).
  Physical qualification and production word/bank/reset integration remain A4c/d.
- [ ] **A4c: physical primitive and complete byte-cycle qualification.** The
  reusable Mutex contract/tests and experimental GF180 schematic have received
  independent review in [draft PR #4](https://github.com/BiscutLabs/chisel-async/pull/4).
  Qualify layout/extraction, electrical and reliability behavior, then the
  complete owner/macro pin paths. Unresolved arbitration has
  no finite physical deadline. Keep load/slew, setup/hold, pulse, reset and routed
  failures explicit. Do not bypass a missing primitive recipe with priority logic.
- [ ] **A4d: native word loop and production integration.** After qualification,
  replace the four lane contexts with retained word/lane/assembly ownership and
  preserve the reviewed commit/POR policy, masks, capacity checks, loader,
  watchdog, retention and sleep behavior. Measure cost and all wake windows,
  rerun affected tests/strict exports, obtain fresh review, commit and push.

## A5a: native I2C observation projection

Digitally verified against parent `5e1406b`; complete physical qualification
remains open.
Each separate native implementation retains only the seven observation fields
used by the wire front end: headGray, active, rejected, addressByte, drive, ack
and sent. The observation store narrows from 340 to 15 bits, removing 325 native
storage bits and 325 data-allowance lanes per variant. No periodic storage is
added. The 340-bit protocol state, 687-bit update result, per-edge byte buffer,
337-bit held frame and four frame banks remain unchanged. See the
[frame-admission contract](frame-admission-contract.md).

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Logic area excluding SRAM (mm²) | 2.975227 → 2.939063 | 3.748168 → 3.710656 |
| Logic area reduction | 1.2155% | 1.0008% |
| Mapped leaf cells, including three SRAMs | 107,992 → 106,954 | 108,714 → 107,676 |
| TT listed-state leakage including SRAM (µW) | 7.864666–10.202253 → 7.772042–10.062488 | 9.346913–12.543369 → 9.252447–12.399941 |
| Observation native payload storage (bits) | 340 → 15 | 340 → 15 |
| Portable periodic RTL bits | 6,000 → 6,000 | 6,001 → 6,001 |

Firmware wakes retain 43 retired instructions and 3,255 BD / 3,160 Click
work-clock edges, with durations 271,607.839 / 263,691.109 ns. Every ordinal
of all 27 matched wake windows per variant retains its class, effects, edge
counts and duration. This native-model activity does not measure wake energy.

The same mapper and five-corner accounting bind both sides. The parent uses the
same production RTL and mapping tools as the preceding A2a measurement; the
intervening A3/A4a commits changed documentation only. I2C alone saves
0.036151 mm² per variant. Unrelated ordinary mapper variation contributes
−0.000013 mm² BD / −0.001361 mm² Click. Control guard area is unchanged at
0.569962 / 1.105951 mm². Physical exports retain 6,010/6,011 periodic bits,
all three SRAMs and unchanged mapped storage clock-pin loads. Listed-state
leakage is not reachable deep-sleep power; these results do not update P&R.

The complete publication input and source/capture aperture remain intact,
including independent frame/snapshot retention and Click phase feedback.
All 15 projection lanes have actual emitted-RTL fault controls. The original
35 BD / 29 Click publication pin assertions remain present. Both strict
standalone baselines and 43 isolated wire mutations pass their expected verdicts;
each mutant must fail at its exact first assertion site with unchanged probes.
Source, compile, binary and execution evidence are hashed before and after use.
The new POR cases complete a fresh, different frame and snapshot after all
three abort scenarios, preventing an inactive post-reset design from passing.

Evidence is under `build/async-i2c-observation/`: `mapped-cost-r1/receipt.json`,
`state-r1.json`, `exports-r1.json`, `wiring-controls-r2/results.json` and
`review-runner-r2.json`. Fresh activity and the complete measurement inventory
are sealed in `activity-r1-receipt.json` and `measurement-seal-r1.json`.
Functional/physical runs pass 226 distinct ScalaTest cases across 23 suites;
509 Python tests pass. Fresh independent acceptance and the final source/
evidence inventory are recorded in `review-final-r1.json` and
`final-evidence-r1.json`. All four strict SoC exports pass with sleep-clock
background, three SRAMs and all four mandatory generic campaigns: BD
687,372,976 portable / 687,582,656 physical mapping checks; Click
590,205,320 / 590,394,120. The exact projection reduces covered native lanes;
no campaign or dynamic-polarity obligation is removed. The alias-resolution
failure from wiring r1 and the state auditor's initially missing Click history
classification remain in their original logs. The fixes use resolved public
probe references and classify the two existing one-bit publication histories
separately from payload storage. Complete publication/capture/return/reset
distribution and routed timing remain open, as do the earlier elapsed and CRC
physical data-budget failures.
