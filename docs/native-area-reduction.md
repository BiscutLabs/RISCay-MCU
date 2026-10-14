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
- [ ] **A2: reduce CRC token storage and arithmetic (proposal 6 / C2).** Compare
  one whole-word linear XOR transform with narrow CRC/word feedback. Retain
  command context once, independent CRC32 oracles, exact Stored publication,
  loader/reset/lock semantics and physical transform timing. Validate full-width
  host length/entry/count before narrowing retained state. Derive widths from
  configured capacity, including the representable full-capacity count.
- [ ] **A3: prove LF narrowing, or retain width (proposal 8).** Wake on each tick
  does not bound final Housekeeping publication latency. An 8/10-bit count can
  wrap in 256/1024 ms in 1 kHz fixtures, or 21.3/85.3 s at production's fastest
  12 Hz. A post-wrap assertion in the stalled service domain cannot detect a
  full missed wrap. Require a proved maximum gap or independent retained
  overflow/fault handling before reducing the current tolerance. This gate is
  unresolved; do not block other safe area reductions waiting for an assumption.
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
- [ ] **A5: addressed native I2C byte storage (proposal 4).** Move frame bytes
  out of the per-edge state/observation token, publish completed bank identity
  and keep immutable ownership through both copy and admission/dispatch. Reduce
  readWord transport only after proving per-edge byte selection across word
  boundaries. Replace accepted-descriptor epochs with sticky stale history only
  after checking every reset ordering; pre-acceptance epoch narrowing requires
  an actual worst-case latency bound, including stopped consumers and POR-only
  work. Preserve two logical credits, native bank rotation, overflow and reset/
  busy context at their original linearization points.
- [ ] **A6: widths and duplicate ownership (proposal 7 / C1d–f).** Evaluate the
  fixed SPI player, quiescing request receipt, saved SRAM address, profile-sized
  GPIO/wake fields and bounded statistics. Remove queued/ordered/bridge copies
  together with their ownership, preserving ordering and independent stalls.
  Audit verification-only payload and dontTouch retention. Any trace-disabled
  physical export must be an explicit configuration compared on both sides,
  retain verification builds and keep architectural/debug interface obligations
  explicit; do not silently prune a live output to improve area figures.
- [ ] **A7: replace guards with proved completion (proposal 3 / R5).** Record each
  guard's ordering/hold/reset obligation. Replace it only with completion that
  proves that obligation under skew, backpressure, phase return and reset. Keep
  guard-removal fault controls; account for the cells and energy of retained
  delays. Synchronous STA complaints alone are not grounds to add registers or
  waive real timing.
- [ ] **A8: qualify transform data allowances (proposal 5).** First count mapped
  leaf cells under each data_delay, separately from actual control delays. A
  library change may make an allowance a passive timing annotation only when
  exact upstream/capture endpoints, reset semantics and bundling checks replace
  the current active mapping. Do not remove reset gates or per-bit buffers on
  the assumption that every source/storage path already supplies their behavior.
  Keep mandatory export coverage and digital model obligations intact. Present
  the concrete library contract change for review before upstreaming it.

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
