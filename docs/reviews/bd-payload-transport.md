# BD resetless payload and compact command transport review

Scope: BD-only, compared with `2c1e3d2`. The separately reviewed library addition
is [chisel-async `856fc75`](https://github.com/BiscutLabs/chisel-async/commit/856fc757517e0ff0c1c8fea9f6d7e61ec32d1172).
The [contract](../resetless-payload-plan.md) defines reset lifetime, qualified
consumption and compact MMIO encoding. The [area ledger](../area-ledger.md)
separates direct savings from incidental hierarchy optimization.

## Review findings and fixes

Independent reviewers examined the compact accepted descriptor, sender prefix
reconstruction, library primitive/controllers and four frame banks. No second
architectural owner, clock or control-reset removal was introduced. The library
keeps resettable constructors as defaults and gives resetless payload a distinct
model/physical identity. Both frame retention joins remain unchanged.

The review required explicit support for the new primitive in the allowance,
RDC, mapper/repair, latch aperture, electrical, monitor and activity catalogs.
Those now use actual `latq_1` pins and owner validity. There is no fictional
payload reset pin. Resetless application-lifetime adoption fails until separately
proved. The old resettable binding still requires its absolute closure bound.
The compact descriptor preserves offset-52-only application-index semantics and
retains operation/mask/alignment before validation. Tests keep malformed stores
faulting without altering data.

The review found no adoption-specific source-retention blocker: publisher ACK
joins bank capture and receipt; bank release waits for receipt and native Control
completion/full return. Local timing gives no source-release credit. The thin
frame hold margin is explicitly named in item 17, not declared closed.

Extended testing also exposed the existing `I2C_EARLIEST_WRITE_STATUS` failure
at 3.2 MHz. The exact parent reproduces it: the single-channel SRAM rewrite had
serialized waits formerly overlapped by four lanes. The snapshot preceded WRITE
completion by five work edges. A write-only macro fast path did not close that
gap and was not adopted. Instead the byte crossings reuse the minimal Stored
receipt's three control FFs, removing two post-synchronizer FSM edges per byte.
Macro timing, source guards, receiving-edge capture ACK and full RTZ remain
unchanged. No BUSY hiding, deferred snapshot or deadline change is used.

Independent review caught an initially missed production RAM instantiation;
that binding was fixed before the final exports. The shared RDC proof now checks
the exact retained-receiver equations, both synchronizer stages and first-stage
fanout; the separate saved-byte proof checks actual qualified payload capture.
Negative controls reject early ACK and bypassed synchronization. This is a finite
local control proof, not a formal proof of the complete chip or physical CDC.

## Functional and structural evidence

Evidence root: `build/bd-payload-transport/`. The library's own evidence is in
`chisel-async/build/resetless-payload-review/`: **91 Scala tests and 118 Python
tests pass**, including unknown startup/enables, default/resetless token-oracle
comparison, occupied-controller reset, randomized stalls/delays and a hold mutant.

MCU focused runs pass: 50 command/admission/register/reset cases; 48 compact-MMIO
and shared fabric cases; then 36 frame/reset/command cases with the final pin.
The frame tests drive unknown payload during idle and POR and retain exact fresh
frame, capture, aperture and return assertions. All four production/debug
generation audits and both production RDC proofs pass. Actual GF180 functional
cell models pass **97 adapter specializations and 27,457 vectors**.

The first fast-gate run passed all 414 Python and 236 Scala cases but its receipt
correctly rejected tool files changed during independent-review fixes. It is not
the accepted gate. Final **`ci-r2/receipt.json` passes 415 Python and 252 Scala
tests** (234 fast, 12 generic boot and six physical-export/timing tests), with
the reviewed source pin and unchanged inputs. Fresh independent review approved
the bounded resetless adoption, compact transport and receipt correction after
the final production-RAM, RDC and loaded-path results passed.

`memory-r4.log` passes 45 I2C, native SRAM, macro-boundary and saved-address
cases. After correcting the production RAM binding, `extended-r5.log` reruns
all seven BD SRAM cases, then passes 53 telemetry/admission/fabric/deep-sleep/
compiled-firmware/activity cases, 12 boot-recovery cases and both explicit
write-through/POR/lock cases. Those final 74 cases use the corrected binding.
Both variants keep their original oracles. All four `audit-*-r4-*` generation
checks and both `rdc-*-r4.log` production proofs pass. The 97 actual GF180 adapter
bindings are byte-identical between `map-r1` and final `map-r2`, so the retained
27,457-vector functional-model run still covers the final primitive recipes.

Actual failed evidence is retained: a shared test initially selected the wrong
clocked fixture; strict resetless export encountered an assumed payload reset
pin; the old cell-vector harness stopped at its fixed 100 µs timeout before an
existing 6,148-vector C-element walk finished. The harness now derives duration
from inventory, keeping every original 20 ns vector assertion. Initial timing
binding runs exposed the same reset-pin assumption and an inlined Services port;
the final Control run binds the selector at the preserved I²C input. No chip
expectation, simulation deadline or physical margin is relaxed.

## Local physical evidence and limits

The default mapping/repair flow proves protected primitive graphs, the whole
repair graph and complete load inventory before measurement. Actual frame
storage is 1,348 plain latches, with their enable trees and no payload reset tree.
The remaining native/control/architectural storage retains reset.

`frame-timing-r3` covers all four banks on the final repaired map at five corners
and two input slews:
**40/40 cases have positive local margins**. Worst allowed input-data lag is
**+21.363 ns**, zero-source-reuse hold **+0.434 ns**, and ACK after latest capture
**+1.396 ns**, using the plain latch's real aperture. These numbers are zero-wire
and do not include mismatch or a composed publication-source release credit.
They are conditional local evidence, not guard shortening or routed signoff.

The Control campaign recomputes all bank inputs from actual frame latch and
clocked header/selector sources; it grants no preceding-work-cycle setup credit.
`control-timing-r3/receipt.json` passes on the final repaired map: ten
corner/slew cases and five feedback cases. Minimum residuals after the stated
20% two-sided derate, actual aperture and 2 ns ordering floor are +89.841 ns
for complete producer setup, +36.271 ns for ACK after bank capture, +39.214 ns
for ACK after kind closure and +66.234 ns for publication after all data.
Capture high/low residuals are +37.704 / +39.951 ns. The separate local feedback
hold minimum is +0.958 ns. There are no missing composed inputs or table-range
errors. Activity is recorded in the area ledger and `activity-final/receipt.json`.
Statistical mismatch, routed min/max RC, keeper retention, full reset/noise and electrical
closure remain item 17. The existing 0.05 mm² hold reserve is not consumed here.

The independently reviewed byte-crossing check on the final repaired `map-r2`
passes all 20 cases (both memories, five corners, two input slews). Minimum setup
margin is **+134.211 ns**, including the actual publication/capture tree,
CLK-to-Q, byte selection and saved-register muxes, the minimum 100 ns receiver
wait, a 20% two-sided path derate, worst Liberty setup and 2 ns residual.
All 42,280 table checks and 10,000 electrical-policy pin cases pass. The single
receipt is `byte-receipt-timing-final-r1/receipt.json`.

The unchanged macro/reply sequence gives a conditional 200 ns gross source-hold
floor at 20 MHz: saved-byte acceptance C0, macro access C1, Q capture C2, reply
acceptance C3, native response offer C4. Source reuse additionally waits for
native capture and full RTZ. This cycle bound excludes POR and requires the same
macro/sender sequencing. Routed skew/jitter, aperture, CDC and min/max wire RC
still need qualification. The digital 400 kHz earliest-status regression is
fixed; physical slow-corner I2C throughput is not established by this setup check.
