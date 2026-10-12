# Remaining clocked-state audit

The asynchronous migration has not reached its physically feasible limit.
This preliminary ledger records the digitally verified native frame banks at
checklist step 11a2a. It provides removal candidates for
[steps 10–17](async-soc-migration.md), not permission to retain existing clocks.
The declaration/ABI comparison against committed 11a1 passes. Counting
emitted state does not establish physical timing or minimum synchronous state.

## Scope and complete reference totals

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
These are present-state counts, not guaranteed net savings: native owners still
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

The eight clocked service command/reply owners account for 2,518 crossing bits;
I2C delivery 40, elapsed delivery 205, SPI delivery 97, SRAM access crossings
674, CPU/completion/admission crossings 145, and source/final receipts 149.
Together they sum to 3,828. A bridge's current existence is not a physical reason
to keep its service-clock client.

## Timed boundaries still need individual justification

I2C's 945-bit wrapper includes eight immutable 104-bit slots, totaling 832 bits,
plus 65 reset-history bits. Native transport and snapshot references are
candidates, but must retain full watchdog-episode identity, immutable bytes,
overflow proof and maximum-rate capture. Sampling/filtering and abandoned-bus
timeout need a separately verified replacement.

SPI's 175 bits include 96 recipe/occupancy bits, 32 samples and 32 age bits.
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
