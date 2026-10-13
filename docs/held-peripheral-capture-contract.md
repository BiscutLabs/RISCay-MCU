# Retained peripheral and SRAM capture (C1b)

Status: digitally verified with fresh independent review, 2026-10-13. This change removes
duplicate payload banks at existing receivers; the service scheduler remains
clocked. Physical producer-to-consumer setup/hold is unqualified.

Both designs use their own native-protocol `ServiceReplyReceipt` at the
following boundaries. Each receiver retains its existing seven control bits,
two request synchronizers, settling cycle, POR ownership and ACK cadence.
The actual downstream consumer captures the held source bus at `out.fire`.

| Production receiver | Removed payload bits per variant | Retaining source |
| --- | ---: | --- |
| Elapsed result, three Groundlark lanes | 159 | Native final arithmetic stage |
| ADC result | 34 | Native conversion final stage |
| ADC waveform token | 1 | Native Join command-input buffer in each protocol |
| I2C read snapshot notification | 8 | Native publication snapshot register |
| Four working-RAM and four program byte requests | 336 | Native per-lane issue stages |
| Total | 538 | No replacement payload bank or guard |

The waveform and snapshot token payloads are unused by their consumers; their
acceptance events retain the original behavior. Elapsed publication fields are
valid with `valid`; ADC fields with `result.valid`. The standalone `SampleScaler`
also removes its 32-bit reply copy: capture `value` on `done`. Standalone
`SramAccess` removes its 32-bit word reply and four 42-bit byte request copies.
These standalone changes are excluded from the production total.

The SRAM macro controller still captures `saved` and `tag` at byte acceptance,
launches macro inputs on the falling edge and captures Q after a full cycle.
Those registers are necessary for the physical synchronous macro interface.
`saved` and `tag` are unreset storage: POR resets the control state and suppresses
acceptance; it does not erase SRAM. No raw application reset may destroy a
producer while this consumer can capture it. All byte ownership remains POR-only.

The RDC check must prove every source/receipt alias, common service clock,
priority selection and ready signal. It enumerates all four bank states, all
16 valid masks and both POR levels. Every saved data bit must select the exact
accepted lane/field, otherwise itself; tag must capture the same lane. Only
these proved saved-register D inputs receive held-bus exemptions. No clock,
reset, tag, control, entire bank or arbitrary downstream register is exempted.

## Matched cost

The comparison uses baseline `2676845`, the same GF180 mapper and all five
pinned Liberty corners. Native primitive inventories, delay chains, three SRAM
macros and public ports are unchanged. No periodic control bits are added.

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Portable periodic RTL bits | 6,538 → 6,000 | 6,539 → 6,001 |
| Mapped logic area, excluding SRAM (mm²) | 3.351460 → 3.291909 | 4.207351 → 4.147977 |
| Logic area change | −1.78% | −1.41% |
| TT listed-state leakage, including SRAM (µW) | 8.760285–11.451153 → 8.603006–11.223379 | 10.452129–14.179303 → 10.293397–13.952939 |
| Work-clock storage input load (pF) | 16.579085 → 14.805705 | 16.750511 → 14.977131 |

Periodic RTL counts exclude the unchanged SDA-edge bit and the chip wrapper;
enabled-policy physical SoC exports contain ten additional periodic bits each.
The 530 removed work-clock bits and eight removed front-clock bits account for
the complete 538-bit reduction. Mapped state-cell counts are separate from RTL
bit counts. Leakage sums are library listed-state estimates, not reachable
standby measurements. Area excludes placement whitespace, clock/reset trees,
routing, analog circuits and pads. No new P&R or timing closure is claimed.

Evidence: `build/async-held-boundary-cleanup/emitted-state-r2/receipt.json`,
`mapped-cost-r2/receipt.json` and `mapping-source-exports-r1.json`. The latter
binds the production sources and actual mapping inputs.

Fresh native-model activity matches the baseline in all 27 windows per variant:
counts, ordering and durations are unchanged. Firmware wakes retire 43
instructions using 3,256 BD / 3,161 Click work-clock edges. The activity audit
binds all 12 receivers in the executed binaries and compares the five changed
wrapper modules with final exports; the workload and observers are byte-identical
to the baseline. See `activity-r1-receipt.json`. No native switching campaign was
recollected, and clock-pin load/activity alone is not a wake-energy measurement.

## Verification obligations

Verification requires both protocol phases/returns, independent bit walks,
stalls, stopped clocks, reset and exactly-once macro effects. Strict exports
bind each direct receiver to actual source storage and reject extra payload
registers or altered control equations. The compiled native-owner inventory
rejects ordinary registers, memories or clock ports beneath native controllers,
including unregistered descendants; library primitives retain their separately
validated native storage. Negative controls exercise actual compiled aliases,
capture muxes, clocks, tags and receiver RTL. Preserve original functional
oracles, coverage requirements and failed evidence.

Completed evidence under `build/async-held-boundary-cleanup/`:

- Focused scaling, SRAM, ADC, I2C and receipt regression: 68 tests pass.
- The full verification suite passes 660 tests across 53 suites, including the
  new actual-consumer SRAM capture monitors, independent core references,
  reset/sleep, firmware, loader/lock, supervision and both service implementations.
  Four physical-policy tests across two suites also pass. The focused run overlaps
  these results: there are 664 distinct passing Scala tests, not 732.
- Python controls: 468 tests pass, including native-owner inventory controls.
- Structural capture/receiver controls reject 126 faults per variant across
  90 bindings, with final r3 receipts hashing the completed strict binaries.
- Compiled receiver wiring: one positive bit-walk baseline and 12 exact-fatal
  wiring mutations per variant. The same alias validator and injected assertions
  run in the full strict probes; these focused controls do not replace them.
- All four strict portable/physical exports pass, with sleep-clock background
  activity, three SRAMs and unchanged generic packed-vector coverage. BD checks
  number 806,570,496 portable / 806,787,456 physical; Click checks number
  700,871,475 / 701,067,075. The host allowance is 3,600 seconds; simulated
  deadlines are unchanged.
- Matched emitted state, public ABI, native primitive inventory, mapped
  area/leakage and all 27 wake windows per variant pass their audits.

Fresh independent review found and closed gaps in the actual capture monitor,
common-clock proof, primitive exception inventory and activity provenance. The
final review and evidence index are `review-final-r1.json` and
`final-evidence-r1.json`; they bind the final diff, executed binaries and results.

Initial checker/evidence failures remain in the evidence directory. They exposed
a manifest-versus-compiled deduplication name mismatch, the encoder's lane-three
default when no request is valid, an inlined-away physical clock alias, and an
incorrect BD waveform-source catalogue entry. The corrected checks bind the
actual compiled module, bank state clock and native Join input buffer; full
capture/priority proof and functional assertions remain intact. Initial state
and cost collectors also rejected mismatched internal metadata and missing
provenance. Intermediate portable strict runs were interrupted to freeze the
helpers; only the complete final r4 runs are passes.

Digital checks do not qualify the longer bundled-data route to each consuming
register. Measure complete source-to-consumer setup/hold, source retention,
earliest release after ACK, reset distribution and load/slew across physical
corners before accepting silicon timing. Do not add periodic staging to evade
these obligations.
