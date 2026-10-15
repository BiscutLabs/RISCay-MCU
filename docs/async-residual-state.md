# Remaining clocked-state audit

## Follow-up source review, 2026-10-13

Two independent audits of `535f781` found no new periodic-clock storage inside
the native controller bodies and no hidden four-phase adapter in Click. R3b's
frame route remains native; the publisher joins the native copy and receipt
ACKs directly. This is a source review, not new physical qualification or a
claim that the clocked shell is minimal.

| Remaining candidate, per variant | Finding and required proof | Checklist |
| --- | --- | --- |
| SPI player: copied recipe/occupancy registers | Digitally verified removal: a five-bit slot and one active bit index the POR-immutable native recipe. Registered pins, all 32 samples, divider cadence and return drainage are preserved; see the [player contract](spi-player-contract.md). | C1d |
| Quiescing CPU request receiver: 70-bit payload copy | Evaluate direct retained-bus capture while preserving close/rebase, source hold, acceptance cadence and invalid-bus isolation. A POR-only receipt is not a drop-in replacement. | C1e |
| SRAM saved byte address: 32 bits in each bank | Groundlark needs 11/10 address bits. Narrow only after full-width validation; preserve small/non-power-of-two capacities and the macro launch/capture contract. Nominal 43-bit reduction may already partly optimize away. | C1f |
| I2C snapshot receipt | Runs on service clock; Services captures on gated work clock. C1g digitally verifies an explicit work-clock qualifier with no storage, actual capture and stopped-consumer controls; see the capture contract. Native coherent snapshot ownership remains a separate migration. | C1g, 13c |
| Six smaller grant/drain receivers | Ten nominal copied payload bits; constants may optimize away. Preserve POR ownership, phase/return and actual consumer capture before replacing them. | C1e |
| I2C reset history | Eight sampled-edge slots carry 512 clocked epoch bits, plus the 64-bit current epoch and native copies. A stale-history redesign must preserve every queued descriptor's reset history; truncating the epoch is insufficient. | R5, 11a2b |
| Services queues, histories and coherent snapshots | Still clocked. Removing the crossing requires moving the corresponding scheduler and acceptance/order/freshness ownership together. | C3, 11–14 |

These are candidates, not measured savings. The native frame store's private
AND binding in BD is a separate R6 maintenance issue, not a clock intrusion.
Independent time/watchdog progress, physical wire sampling, macro access,
clock-gate synchronization and coordinated reset closure remain required;
their surrounding storage and bookkeeping still need individual justification.

## Verified cleanup history

A5b's addressed native receive store removes **513 native payload bits per
variant**. Native payload totals become **11,454 BD / 11,607 Click**; periodic
storage remains **5,910 / 5,911** portable and **5,920 / 5,921** in enabled-policy
physical exports. All periodic register bindings, public ports and SRAMs are
unchanged. The [receive-byte contract](native-i2c-byte-store-contract.md) records
the digital verification, measured cost and open physical gates. Frame publication, banks,
sampled readWord and reset epochs remain separate work.

C1d's compiled and matched measurement removes another **90 periodic bits per
variant**, giving **5,910 BD / 5,911 Click** portable bits and **5,920 / 5,921**
enabled-policy physical bits. Native primitives, SRAMs and public schemas are
unchanged. Functional, actual-wiring and strict export checks pass; see the
[SPI player contract](spi-player-contract.md). These are declaration
counts, separate from mapped storage, area and clock-pin load.

C1b's cleanup is **digitally verified, 2026-10-13**. Compiled inventories prove **538
fewer periodic-clock payload bits per variant**, giving **6,000 BD / 6,001 Click**
portable totals, excluding the unchanged SDA-edge bit. Enabled-policy physical
exports contain ten additional periodic bits. Native primitive and SRAM
inventories and public ports are unchanged. Sources remain held through actual
consumer capture; see the [capture contract](held-peripheral-capture-contract.md).
The audit found no ordinary clocked storage inside the native controller
bodies. Explicit wrappers and Services still own substantial periodic state:
committed views, host snapshot, observation/dispatch histories, sampled I2C
wire slots and reset epochs, and the SPI waveform player. These are tracked
cleanup/migration candidates, not a claim of minimum synchronous state.
The full 660-test verification suite, four physical-policy tests, 468 Python
controls and all four strict exports pass. Fresh independent review closes the
digital scope; producer-to-consumer physical capture remains unqualified.
Matched logic area falls 1.78% BD / 1.41% Click, and every measured wake window
matches the baseline. C1 through C1b now remove a net **1,792 periodic bits per
variant**, including the intervening R3/R3b changes.

R3b native frame-route ownership is **digitally verified, 2026-10-13**. It removes R3's two copy
synchronizers and two sticky offered-context bits per variant. BD reuses its
two-bit native route register; Click adds two native route bits and a retained
capture pulse. The original clocked descriptor ordinal and receipt remain.
Compiled emitted inventories show portable periodic totals of **6,538 BD /
6,539 Click**, excluding the unchanged SDA-edge bit. Enabled-policy physical
exports contain ten more periodic bits per variant. Native declared register
bits remain 14,221 for BD and grow from 14,382 to 14,384 for Click; Click's retained
C-element capture is accounted separately in mapped logic. No payload bank is
added. Evidence is `build/async-frame-native-route-repair/emitted-state-r2/receipt.json`;
all affected functional and strict-export checks pass. Matched wake counts and
durations are unchanged. Across C1, R3 and R3b, the net reduction is 1,254 periodic
bits per variant; native storage, mapped cost and physical limits remain separate.

R3's historical frame-copy completion correction at `a3f11af` is **digitally verified, 2026-10-13**. It added four
POR-owned periodic-clock bits per variant beyond C1: two copy-completion
synchronizers in I2cTarget and two retained reset/busy admission facts in
Services. No clocked or native payload bank is added. The native publisher ACK
join adds one C-element, included in the matched mapping. Final portable periodic
totals are **6,542 BD / 6,543 Click**, excluding the unchanged SDA-edge bit:
a net **1,250 fewer periodic bits per variant** across C1 and R3. The historical
inventories below retain their original scope.
This repair preserves a real clocked descriptor consumer; it does not remove
the service scheduler or establish minimum synchronous state or physical closure.

The asynchronous migration has not reached its physically feasible limit.
This ledger records native frame banks, reset containment and the current
service-reply correction. It provides removal candidates for
[steps 10–17](async-soc-migration.md), not permission to retain existing clocks.
The declaration/ABI comparison against committed 11a1 passes. Counting
emitted state does not establish physical timing or minimum synchronous state.

## Scope and complete reference totals

C1 emitted-state audit, 2026-10-13: direct capture removes exactly **1,254
periodic-clock payload bits per variant**: Control 376, Housekeeping 397,
Telemetry 173 and Supervisor 308. The four receipts retain seven control bits
each. Independent compiled inventories show unchanged native primitive models,
parameters, state and ports, unchanged SRAMs and unchanged public ABI. Portable
nonprimitive RTL totals change from 7,793/7,794 to **6,539 BD / 6,540 Click**;
subtract the unchanged SDA-edge bit for periodic totals of **6,538 / 6,539**.
Enabled-policy physical exports contain ten more bits in each variant. These
counts exclude the generated chip wrapper and are not mapped cell counts.
Evidence is `build/async-service-publication-repair/review-state/r1/` and
`r1-controls/`, including complete source hashes and actual producer/receipt
bit walks. Functional and strict verification are tracked in the
[capture contract](service-reply-capture-contract.md); physical capture timing
remains unqualified.

R2a digital-repair update, 2026-10-12: the reused reset-interval counter grows from
three to six bits in each implementation. Exact emitted declaration comparisons
against R1 find this single state change in all four portable/physical exports;
all 34 public ports remain identical. Portable periodic totals are therefore
**7,792 BD and 7,793 Click bits**, three more per variant. Evidence is
`build/async-reset-hold-migration/state-and-abi.json`. Functional, structural and strict
digital checks pass; the added counter is not physical timing or cost
qualification.

R1 digital-containment update, 2026-10-12: the fresh portable exports contain **7,789 BD
and 7,790 Click periodic-clocked bits**, a net **40-bit increase per variant**.
The comparable baseline below remains the digitally verified 11a2a inventory.
The independent audit bound its 88 recorded Scala sources to `eb8ad1c`, rebuilt
its scope inventory, and compared it with `exports-r3`. Exact register-declaration
and all 34 public-port comparisons extend that inventory to final `exports-r4`;
the strict `exports-r6` copies retain identical production source hashes.
Evidence, including `final-export-equivalence.json`, is under
`build/async-reset-domain-migration/state-audit/`.

The increase is nine coordinator bits, twenty publication-client mirror bits,
ten actual bridge close/rebase acknowledgments, and one additional completion
return observation bit. The 120 application-projection bits retain their width
but now have POR ownership and synchronous cancellation. Existing bridge POR
release chains retain 128 bits. The R1 disjoint emitted totals were top
2,765/2,766, 64 crossings 3,838 each, and five wrappers 1,187 each; subtract the
one SDA-edge bit for the periodic totals. This is containment overhead, not
asynchronous state removal or area/power evidence. The later R4 matched
comparison and C1d cost reports supersede that historical mapping baseline.

Do not compare these portable counts directly with enabled-policy physical
exports: their baseline has ten additional emitted bits from configuration and
alias retention. Supported-profile inventory remains a separate obligation.

The 2026-10-12 inventory covers the Groundlark low-power portable SoCs with ADC
and source stopping enabled. Register declarations match both emitted designs.
Counts are RTL bits, excluding async primitive model state, fixed SRAM arrays,
verification state and the generated chip wrapper. They are neither mapped-flop
counts nor physical area/power estimates. Other supported configurations and
complete per-owner clock/reset resolution remain item 16 work.

| Disjoint owner group | BD bits | Click bits |
| --- | ---: | ---: |
| Flattened SoC top | 2,735 | 2,736 |
| 64 crossing/receipt owners | 3,828 | 3,828 |
| Five clocked wrappers | 1,187 | 1,187 |
| **Total: 70 owners** | **7,750** | **7,751** |

Each total includes one already-asynchronous SDA-edge capture bit. Periodic
clocked subsets are therefore 7,749 and 7,750 bits. The wrappers contain I2C
945, SPI 175, elapsed transport 37, RAM access 15 and program access 15 bits.

## Removal ledger

The following groups partition the flattened top. Crossing and wrapper counts
above are separate storage; replacing their clients enables further removals.
These are the 2026-10-12 baseline counts, not guaranteed net savings: native owners still
need retained storage and can temporarily require new receipt/synchronizer bits.

| Top-level state | Bits BD / Click | Checklist |
| --- | ---: | --- |
| Host descriptors and logical count | 10 / 10 | 11a2b, 11b |
| Committed service views and output copies | 751 / 751 | 13a–b |
| Host read snapshot | 296 / 296 | 13c |
| Ordered/queued elapsed work | 382 / 382 | 12a, 11b |
| Supervisor observation history | 425 / 425 | 12b–c |
| Telemetry and event history | 249 / 249 | 12b–c |
| Dispatch, commits and status control | 135 / 135 | 11b, 13a |
| SRAM byte boundary | 149 / 149 | 15a |
| GPIO input synchronization | 64 / 64 | 15b |
| Independent time and watchdog | 79 / 79 | 15d |
| Reset, wake and clock gating | 173 / 173 | 15e |
| Native-client drainage/start/debt copies | 17 / 18 | 10b, 14 |
| Heartbeat/kick delivery | 4 / 4 | 15d |
| ADC launch pending | 1 / 1 | 13b, 15c |

Program/loader native return removes the word reply, publication and Completion
memory ingress (39 + 8 + 40 bits). Its independent capture receipt and owner-idle
observation add five plus two clocked bits, a net reduction of 80 per variant.
Preserve the separate five-bit Stored receipt's Control-acceptance meaning.
The frame-receipt step removes another 339 clocked bits: its old 344-bit bridge
is replaced by five control bits. The independent 15-bit snapshot crossing
remains. Native frame payload/epoch ownership (11a2a) removes another 540 bits
from the top: the old 550-bit mailbox/count/debt becomes ten descriptor/count bits.
Four five-bit head receipts, two tail bits and two busy synchronizers add 24 bits,
for a verified net reduction of 516 periodic-clocked bits per variant. The four
native banks add 1,348 payload bits plus native route/phase state; no total area
or power saving is inferred. I2C delivery crossings now total 40 bits.
Next migrate narrow logical credits and dispatch ownership, observation histories,
and coherent publication.
Remove their intermediate crossings as each pair of adjacent owners becomes
native; preserve reset lifetimes and complete previous-token return.

Before C1, the eight clocked service command/reply owners accounted for 2,518 crossing bits;
I2C delivery 40, elapsed delivery 205, SPI delivery 97, SRAM access crossings
674, CPU/completion/admission crossings 145, and source/final receipts 149.
Together they sum to 3,828. A bridge's current existence is not a physical reason
to keep its service-clock client.
C1 reduces the eight service owners to 1,264 bits without adding native storage.
Their command payloads and control remain candidates for removal with the
clocked admission/dispatch and publication clients.

## Timed boundaries still need individual justification

I2C's 945-bit wrapper includes eight immutable 104-bit slots, totaling 832 bits,
plus 65 reset-history bits. Native transport and snapshot references are
candidates, but must retain full watchdog-episode identity, immutable bytes,
overflow proof and maximum-rate capture. Sampling/filtering and abandoned-bus
timeout need a separately verified replacement.

The pre-C1d SPI inventory's 175 bits includes 96 recipe/occupancy bits,
32 samples and 32 age bits. Verified C1d replaces the 96-bit copy with six
playback bits, leaving 85 bits in this boundary's declared inventory.
Admission, age and return bookkeeping can be investigated independently of timed
pin playback. Preserve both half-phases, MISO capture and first-frame discard.

Pinned SRAM CLK, falling-edge input launch and full-cycle Q capture are interface
obligations. They do not automatically justify saved word requests, duplicated
payloads, active flags or round-trip crossings. Independent time/watchdog progress,
safe wake/gating and metastability-safe input capture also remain obligations;
current counter widths and surrounding policy still require an owner-level audit.
The chip wrapper's default 20-bit reset-hold implementation is outside these
totals and retains its continuous-good minimum hold requirement.

The fresh declaration scan, owner/register assignments, source hashes and exact
baseline deltas are retained in `build/async-host-admission-payload-migration/` as
`compare_state_and_abi_r2.py`, `clocked-state-comparison.json`, `state-inventory-r2/`
and `residual-register-candidates.json`. The original top-level group assignment, with the host group adjusted above,
is retained in `build/async-ram-return-migration/residual-priority-audit.json`.
Item 16 must cover other configurations and resolve
all remaining clocks/resets. Item 17 must qualify characterized cells, complete
paths and routed timing before any maximal-asynchrony claim. Older P&R does not
qualify this implementation.
