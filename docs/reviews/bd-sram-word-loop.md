# BD SRAM word-loop review

Scope: batch 1 of the [area action plan](../native-area-action-plan.md), against
plan commit `30dc3f2`. Reviewer: independent agent `bd_sram_rewrite_review`.
Click RTL is unchanged. Functional and local timing evidence is described below;
this is not routed physical qualification.

The rewrite keeps one native word request, byte lane and read assembly per
memory, and reuses one real clocked macro boundary. It preserves the separate
Return payload and native eligibility; those still separate effect drainage from
application presentation. No periodic clock enters the word loop.

Review findings fixed before adoption:

- Advance waits for the **actual guarded response ACK** to return low, not only
  the state that intends to lower it. Otherwise the next byte can reuse a live
  response channel.
- Full-width capacity and high-bit checks precede native address truncation.
  Non-power-of-two capacity and out-of-range admission tests remain meaningful.
- Passive timing endpoints start at the original operands, including state and
  feedback. Starting at a transformed mux output would omit its decode cone.
- The new guard uses the canonical `output_guard` identity so randomized digital
  tests preserve its declared guard interval rather than treating it as a short
  routing cell.
- Single-lane integration fixtures select stalls by the actual byte address.
  The stopped-clock fixture now settles its backpressure input before restarting
  the clock, avoiding a same-edge testbench race. No deadline or oracle changed.

## Verification

`build/bd-word-loop-ci-r1/receipt.json` passes: 387 Python tests, 206 fast Scala
cases, 12 generic boot cases and six physical export/policy cases. A fresh Python
run after guard-catalog updates also passes (`bd-word-loop-python-r2`).

The extended run `build/bd-word-loop-extended-r2.log` passes all **60 cases** in
SramSpec, AsyncSramSpec, RamSourceSpec, ProgramSourceSpec, FirmwareSpec,
DeepSleepSpec and PhysicalEstimateSpec. It covers both variants, including byte
masks, reset drainage, stopped clocks, firmware and the unchanged wake bounds.
Both current exports pass generation, passive-allowance and RDC audits.

The separate full-capacity boot selector passes both changed BD cases: primary
**364.828 ms**, golden fallback **1,042.319 ms**, each with all 2,048 bytes and
the expected application result. Click primary also passes (**398.812 ms**).
The redundant unchanged Click golden rerun was deliberately stopped after these
three passing simulations to free the single sbt process. It is **not reported
as passed**, and that selector has no passing aggregate suite verdict. Its
unchanged functional assertions remain in GenericBootSpec. The individual
passing logs are retained under `build/soc-tests/generic-ab-full-*`.

Failed compile, fixture, mapping and timing attempts remain in `build/bd-word-loop*`.
In particular the old stopped-clock failure and its same-RTL race reproduction
are retained. An accidental Yosys 0.33 map was stopped and excluded; the accepted
matched map uses the original Yosys 0.62/ABC configuration.

## Local physical checks

The independent campaign uses the repaired whole-chip `map-r4` netlist, five
PVT corners, two input slews, actual protected leaf pins and reviewed primitive
keeper cuts. It composes the sequencing FIFO/stage, closed bank transforms,
external held-data bridge, publication/ACK and complete return. New guards keep
conservative counts; no shorter policy from another owner is reused.

Minimum margins after the relevant Liberty aperture, 20% two-sided engineering
derate and 2 ns ordering residual:

| Obligation | Minimum margin, ns |
| --- | ---: |
| Exclusive merge to owner FIFO setup | 14.882 |
| State decode to closed-bank capture | 26.581 |
| Guarded successor to step setup | 48.156 |
| External held word/byte data setup | 108.085 |
| Latest bank capture to external ACK/release | 38.904 |
| Composed loop source-release hold | 41.045 |
| Bank trigger high / low pulse | 40.657 / 35.863 |

The separate same-event feedback hold screen has **+0.995 ns** minimum against
actual Liberty hold, under its sampled loaded-slew envelope. This is a different
check; it does not claim the 2 ns ordering residual above. Routed min-RC hold
repair remains required if extracted paths fail.

An OpenSTA crash was traced to four analysis-clock roots with no combinational
fan-in to the queried bank inputs. An independent graph walk established the
actual source inventory; removing those irrelevant roots resolved all required
queries. Failed logs remain, and no functional path was waived. The generic
adopted-policy stage selector also excluded the new conservative guards; a direct
inventory check covers the actual new FIFO/stage guards instead.

All eight primitive-local bank capture trees pass the unchanged 2.5 ns limit
at both edges, five corners and two slews: worst propagation **1.7263 ns**,
spread **0.06330 ns**. The complete shared publication path, including parent
repair buffers, reaches **3.0671 ns** with **0.3951 ns** spread. That full path
is included in the composed margins; the primitive-local budget is applied at
its actual declared boundary, not moved to an earlier shared root.

Evidence is under `build/bd-word-loop/review-timing`. Full-chip electrical closure, extracted
min/max RC, coupling, mismatch characterization, reset distribution and macro
pin timing remain tape-out obligations. Zero-wire-RC margins do not close them.

## Area and activity

The [area ledger](../area-ledger.md#bd-sram-word-loop-rewrite) records the matched
flat reduction **1.893700 → 1.718196 mm²** and hierarchical repaired reduction
**2.196947 → 1.988072 mm²**. The owners meet their storage/recipe budgets.
Native storage drops by 1,979 bits; periodic sinks drop by 171 flat or 148 with
hierarchy. The latter comparison leaves Services with 64 service and 912 work
sinks.

The tradeoff is explicit: firmware work edges rise **3,242 → 4,166** because the
single byte channel returns fully before reuse. Maintenance/acquisition activity
is unchanged and original deadlines pass. This is an area result with a measured
latency cost, not an energy improvement or a claim that the MCU is optimized.
