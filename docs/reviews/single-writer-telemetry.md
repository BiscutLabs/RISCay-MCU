# Single-writer Telemetry review

Parent: `d0a01c5`. Evidence root: `build/single-writer-telemetry/`.
The final R7 functional, structural and local BD timing gates pass. Both independent
reviews are closed with their findings fixed. Physical tape-out qualification remains open.

## Independent review and fixes

Two read-only agents reviewed the independent BD/Click implementations and the
BD timing extension. Findings addressed during implementation:

- Omit zero-width sample-view endpoints for configurations without CPU-published
  channels; preserve empty and ADC-only configuration elaboration.
- Remove duplicate SPI result payload storage. The priming conversion still
  exposes its computed result to the original waveform oracle, while the retained
  sample bank preserves its entire old record until a publishable result.
- Preserve accepted software publication across application cancellation without
  applying revoked application/GPIO writes. Borrowed MMIO operands remain held
  until full native return; retain the selected application index with the loan.
- Exercise a host snapshot on the publication edge, full-return reader reopening,
  sequence rollover, failed attempts and application reset before dispatch.
- Correct the live register-view and sleep contracts, which still described
  sample feedback, elapsed Telemetry maintenance and removed supervisor logic.
- Include the upper-time counter and every periodic sequential launch into its
  arithmetic, including elapsed receipt-valid/active gating. These paths have a
  50 ns requirement independent of the sample bank's full-return qualification.

The first timestamp screen found real SS/hot setup failures: −24.623 ns in the
production ADC configuration and −26.860 ns in the optional software-sample
fixture. The native bank reader and return-order checks passed. Separate BD and
Click parallel-prefix arithmetic replaces the long ripple carry with no added
state, clock boundary or cycle. An independent arithmetic review found no defect;
the BigInt oracle covers 1,156 carry/borrow/wrap/random vectors per implementation.
The prefix-only map still failed by 8.964 ns because late receipt-valid masked
the operand before the arithmetic. The final RTL computes from the retained
payload and qualifies the result at the final mux. Invalid-payload tests verify
that this combinational preparation cannot change retained timestamps.
The next map exposed a remaining age-read deficit of 3.760 ns and a counter
deficit of 0.326 ns in production, at SS/hot and 2 ns slew. The final arithmetic
uses 32-bit carry selection for the counter and a direct high-word borrow check
for age saturation. Both preserve full 64-bit modular behavior, including wrap;
an independent review checked the proof and the extended BigInt oracle.

The flattened prefix was not sufficient: ABC's area mapping rebuilt a long
borrow/carry chain, leaving production/optional periodic setup deficits of
6.424/3.886 ns in the R4 maps. Four-bit carry-select helpers now preserve ordinary
combinational module boundaries, with a group prefix above them. They introduce
no clock, reset or storage. Independent review checked OR-propagate plus generate,
subtraction's initial carry and nibble ordering. The failed maps are retained;
the R5 production mapped campaigns pass. The optional software-channel load-enable
fix is checked separately in R6.

After the carry fix, production timestamp setup passed. The optional software
channel exposed a different deficit: reset/admission decoding drove the timestamp
load enable through 46 cells. Its existing timestamp now tracks upperTimeNext only
while all pending/outstanding/return flags are idle. Acceptance captures the same
edge's time, then freezes it through dispatch and full return. An assertion checks
that software acceptance occurs in that tracking state. Independent review caught
and fixed the need to freeze for non-sample Commit payloads too. No state or clock
was added. At that intermediate step, production export token streams were unchanged, so
R5 production maps remained applicable while the optional configuration was
remapped. The subsequent prefix-tree correction below regenerates every map.

That optional R6 screen then found a 0.304 ns SS/hot setup deficit from upperTime
to the sample-age snapshot. The new load-enable path passed; ABC had serialized
the group-prefix tree above the protected nibbles. An ordinary combinational
prefix-combine module now preserves each tree level in both implementations.
Independent review checked high/low composition, immutable levels, OR-propagate,
subtraction carry-in and bit order. It adds no state, clock or pipeline cycle.
Both production maps and the optional fixture are regenerated for this final
change. The conservative global CLK-to-Q bound is unchanged.

The timing reader also rejected an analysis error: a periodic ACK reference
propagated through a native bank and produced a second sequential launch.
Explicit analysis roots now delimit native sequential outputs for the periodic
query. No timing arc is disabled by that fix; native launch composition remains
a separate obligation. The source, endpoint and complete path checks stay strict.
The added elapsed-operand screen binds only the actual nominal/upper reply ports;
unrelated CPU/Control admission qualifiers cannot inherit that receipt's bounds.
It measures a conditional 100 ns setup aperture and conservatively assumes
immediate source reuse at the elapsed ACK. Source publication and loaded slew
remain explicit preconditions, independently reviewed.

A 0.532 ps min/max inversion exposed nonmonotonic NLDM delay in the optional
software bank: a NAND2 became slightly faster with a slower propagated slew.
The checker now runs both min and max at each fixed source-slew scenario and
encloses both sampled mode graphs at every combinational arc before searching
all paths. It snapshots all arcs first, checks exact cone/profile coverage, and
retains the inversion evidence. No endpoint tolerance, signed-delay clamp or
setup/hold relaxation is used. This encloses the sampled graphs; it does not
prove continuous slew coverage or routed timing.

## Evidence and limits

- `extended-r1.log`: 130 tests across 14 suites passed, including full generic
  boot/persistence, firmware, deep sleep, ADC, admission and sample semantics.
  This run precedes the arithmetic-only timing correction.
- `nibble-export-r5.log`: 30 focused tests passed on the nibble arithmetic, covering
  timestamp carry/borrow/wrap, invalid raw operands, Telemetry, Housekeeping and
  native-model wake activity. All five exports were regenerated.
- `software-enable-r6.log`: 38 Telemetry, command-borrow and Housekeeping tests
  passed after the optional timestamp enable fix; all five exports regenerated.
- `group-prefix-r7.log`: all five exports regenerated and 42 tests passed after
  preserving the group-prefix tree, including the wide-integer arithmetic oracle,
  Telemetry, command borrowing, Housekeeping and wake activity. `activity-r7.json`
  records unchanged activity versus the previous arithmetic implementation.
- `ci-r7/receipt.json`: 303 Python properties and 197 Scala/export-policy tests
  passed after the final prefix-tree change, with no changed inputs.
- `check-{bd,click}-r7`, `check-regular-{bd,click}-r7`, and `check-software-r7`:
  generation structure passed. `rdc-{bd,click}-r7.log`: both RDC proofs passed
  with no violations.
- `reset-activity-r3.log`: 75 reset, recovery and activity tests passed after the
  retained-operand change and before the final arithmetic-only shortening.

Final timing uses `map-bd-r7` and `map-software-r7`. Each bank campaign covers
five PVT corners and two source slews, with the existing 20% two-sided engineering
derate. All three campaigns pass with unchanged inputs. Results below are minimum
margins in ns across each ten-case campaign:

| Obligation / evidence | Setup | Hold | Bank completion before feedback |
| --- | ---: | ---: | ---: |
| Application bank, 224 reader pins (`timing-app-r7`) | 27.734424 | 1.238261 | 12.626948 |
| ADC bank, 101 reader pins (`timing-adc-r7`) | 205.793982 | 1.200236 | 10.980031 |
| Production periodic timestamp arithmetic, 162 target pins | 11.319417 | 0.414392 | — |
| Production conditional elapsed ingress, 128 target pins | 80.434832 | 0.847914 | — |
| Optional software bank, 101 reader pins (`timing-software-r7`) | 202.401194 | 1.040438 | 12.550908 |
| Optional periodic timestamp arithmetic, 226 target pins | 7.898520 | 0.414392 | — |
| Optional conditional elapsed ingress, 192 target pins | 80.315956 | 0.869015 | — |

Bank completion before feedback must exceed 2 ns. The ADC bank reader aperture is
250 ns (A+5); periodic timestamp arithmetic remains 50 ns. The elapsed-ingress
100 ns bound is conditional on the source settling by synchronized detection, at
the sampled 0.02/2 ns source slews; it does not close continuous source/internal
slew coverage or the upstream native launch.
`timing-stages-r7` also passes all 20 local cases: Telemetry/update and SPI/finish
each have positive data-versus-request, hold and capture-before-ACK margins. The
smallest zero-reuse hold is 1.097177 ns and capture-before-ACK is 1.291177 ns.

The original failed runs remain alongside the corrected runs. Early fixture
failures included obsolete accumulator injection, a zero-width endpoint,
insufficient four-phase return in the sequence-seeding test and a new test that
attempted two serial host transactions inside an unchanged deadline. The fixes
use real publication paths, complete the handshake, and use CPU readback for the
second observation. Existing behavioral expectations and deadlines are unchanged.

Use the final run receipts and [area ledger](../area-ledger.md), not an earlier
successful compilation, to identify accepted outputs. The optional software
sample map is coverage for a supported configuration; it is not the production
area configuration. Click receives functional tests and matched area/sink reports,
without a new physical sizing campaign.

The BD checks are local, electrically repaired, zero-wire-RC measurements.
Native elapsed-payload launch composition, extracted min/max RC and skew,
electrical acceptance, reset distribution and statistical mismatch qualification
remain item 17 obligations. No tape-out timing or physical energy claim is made.

Next architecture priority is external A/B boot slots, a golden recovery image,
factory provisioning and full-capacity boot timing, before further area tuning.
