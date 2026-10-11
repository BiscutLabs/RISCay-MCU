# Remaining clocked-state audit

The asynchronous migration has not reached its physically feasible limit.
This preliminary ledger records the working-RAM return implementation at
checklist step 10b2d1. It provides removal candidates for
[steps 10–17](async-soc-migration.md), not permission to retain existing clocks.

## Scope and complete reference totals

The 2026-10-11 inventory covers the Groundlark low-power portable SoCs with ADC
and source stopping enabled. Register declarations match both emitted designs.
Counts are RTL bits, excluding async primitive model state, fixed SRAM arrays,
verification state and the generated chip wrapper. They are neither mapped-flop
counts nor physical area/power estimates. Other supported configurations and
complete per-owner clock/reset resolution remain item 16 work.

| Disjoint owner group | BD bits | Click bits |
| --- | ---: | ---: |
| Flattened SoC top | 3,275 | 3,276 |
| 62 crossing/receipt owners | 4,229 | 4,229 |
| Five clocked wrappers | 1,181 | 1,181 |
| **Total: 68 owners** | **8,685** | **8,686** |

Each total includes one already-asynchronous SDA-edge capture bit. Periodic
clocked subsets are therefore 8,684 and 8,685 bits. The wrappers contain I2C
941, SPI 175, elapsed transport 37, RAM access 15 and program access 13 bits.

## Removal ledger

The following groups partition the flattened top. Crossing and wrapper counts
above are separate storage; replacing their clients enables further removals.
These are present-state counts, not guaranteed net savings: native owners still
need retained storage and can temporarily require new receipt/synchronizer bits.

| Top-level state | Bits BD / Click | Checklist |
| --- | ---: | --- |
| Host mailbox and admitted reset context | 550 / 550 | 11a |
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

First complete program/loader native return: its word reply, publication and
Completion memory ingress contain 39 + 8 + 40 candidate bits. Preserve the
five-bit Stored receipt's Control-acceptance meaning. Then migrate mailbox and
dispatch ownership, independent observation histories, and coherent publication.
Remove their intermediate crossings as each pair of adjacent owners becomes
native; preserve reset lifetimes and complete previous-token return.

The eight clocked service command/reply owners account for 2,518 crossing bits;
I2C delivery 359, elapsed delivery 205, SPI delivery 97, SRAM access crossings
708, CPU/completion/admission crossings 185, and source/final receipts 157.
Together they sum to 4,229. A bridge's current existence is not a physical reason
to keep its service-clock client.

## Timed boundaries still need individual justification

I2C's 941-bit wrapper includes eight immutable 104-bit slots, totaling 832 bits,
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

The reproducible declaration scan, complete owner/register assignments, hashes
and priority analysis are retained in `build/async-ram-return-migration/` as
`residual-priority-audit.json`, `residual_priority_scan.py` and
`residual-priority-audit.md`. Item 16 must cover other configurations and resolve
all remaining clocks/resets. Item 17 must qualify characterized cells, complete
paths and routed timing before any maximal-asynchrony claim. Older P&R does not
qualify this implementation.
