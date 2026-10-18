# Architecture-first follow-ups

The [open migration checklist](async-soc-migration.md) owns sequencing and status.
This document expands its boundary decisions and records the implemented slices.
The remaining proposals are open work. Completed build/characterization work
is in the [migration log](history/migration-log.md#source-build-and-mismatch-screen-follow-up).

RISCay is a generic MCU. Neither RTL nor ROM contains application policy. BD is
the tape-out target. Architecture conversions keep BD and Click functionally equal
unless the user explicitly requests otherwise. Each variant gets its own native
implementation and functional regressions. Click physical timing and sizing work
remains frozen; area and sink accounting still accompany functional changes.
Document temporary internal divergence and any approved ABI transition.

## Work order

1. Decide B's replacement host ABI before resuming any 11a2b credit/admission work.
2. Implement A's always-on/application split and B's register-pointer interface,
   moving each producer/consumer pair together. Preserve reset and commit ownership.
3. Add resilient external boot storage and factory provisioning. Measure full-capacity
   boot and firmware wake activity; no application policy moves into silicon.
4. Regenerate the BD request-guard inventory and size surviving guards at each
   corner. Historical guard counts are not the inventory for the new architecture.
5. Run item 16 once on the integrated architecture and supported configurations,
   then regenerate 17a3 and close the BD tape-out gate, including full R2b reset
   distribution and targeted routed hold repair.

Local measurements and affected verification accompany each implementation batch.
Record mapped/repaired logic, clock sinks and wake activity/duration in the
[area ledger](area-ledger.md), against the immediate parent and original baseline.
Full extracted-RC qualification remains item 17. Physical prerequisites may be
resolved earlier when they determine a design choice; optional 15a–c research is
not on the tape-out critical path.

## A. Always-on/application ownership split

The implementation currently has a service clock, a gated work clock and native
POR/application owners, but they are interleaved in Platform/Services. Moving
code into two wrappers alone would not reduce crossings or clock sinks.

| Retained always-on ownership | Application ownership |
| --- | --- |
| LF time/watchdog, reset qualification, crash count, SDA wake | CPU, register file, fetch/execute and CPU transaction presentation |
| Image/lock metadata, host-loader admission, accepted programming work | Uncommitted CPU requests and CPU response presentation |
| SRAM contents and completion of already committed macro work | Application execution eligibility |
| GPIO retention option, POR-retained sample/time state, host telemetry transport | Application words and pending event/deadline/lease state, cleared by the existing reset command |
| Reset/close/rebase coordinator and demand needed to drain owners | Request for sleep/lease, subject to independent watchdog limits |

"Always-on" means retained and able to request progress; it does not mean a
continuously running fast clock. Sampling and the existing service/SRAM boundaries
remain explicit physical obligations. Native storage remains clock-free.
Physical residence does not change reset semantics: an AON owner may host
application-lifetime fields. Pending event flags, deadlines, leases and application
words still clear on application cancellation. Only ordinary GPIO output/OE
retention is configurable; SPI recovery always releases its outputs.

Use the existing close/rebase protocol at the boundary: inhibit admission, close
each receiver on its actual clock, finish or cancel according to the established
commit point, reset native application state, rebase and reopen. No raw reset may
qualify retained synchronous loads. Never cancel a committed loader/SRAM effect
because the CPU resets. Wake demand must include return/rearm, not just valid.

First implementation gate: assign every retained state owner and every periodic
clock sink to a side; move producer and consumer together. Reuse existing channel
schemas, with one ownership crossing per subsystem; move its producer and consumer
as a unit rather than adding a crossing per message type. Do not add a
payload mirror merely to cross the new module hierarchy. Verify reset during host
upload, ADC completion, CPU RAM traffic and sleep, including repeated watchdogs.
Measure mapped/repaired area, periodic sinks and wake activity/duration for each batch.
This absorbs C1e2, the remaining 10b ownership/debt, 11b dispatch, 13a state
projections and 14 temporary round trips. Remove obsolete grant/drain copies,
receipts and gate demand together with their migrated clients.

This is a proposed logical boundary, not implemented power gating. Separate rails
would additionally require isolation, retention cells, supply sequencing and an
external-memory/pad strategy before RTL work starts.

### Existing divergence: retained Telemetry register view

BD removes Services' application/GPIO/pending payload mirrors and reads a closed
bank inside the existing native Telemetry owner. One authorization bit remains at
the existing reply receipt, with one application-view validity bit in Services.
CPU write scheduling and the MMIO crossing are unchanged.
Click currently retains its previous internal state/projections. The next native
event conversion must first supply native app/GPIO MMIO routing in both variants;
neither Fabric currently provides that endpoint. Keep Telemetry as the existing
owner, separating its CPU-written bank from sample observations instead of adding
an independent writer. This is a bounded item-A slice, not completion of the
island split. The [native event contract](native-events.md) tracks the source
inventory, exact clear semantics and protocol work that must precede adoption.
See [the register-view contract](native-app-registers.md) for snapshot atomicity,
reset isolation and the boundary timing obligations.

## B. Register-pointer host interface

The target is a **replacement for the framed loader**, not an additional permanent
protocol. The existing framed ABI remains the implemented interface until the
new ABI and host transition are specified and verified. Decide protocol version,
register allocation, pointer units/increment/wrap, command commit, status/error
behavior and migration of existing host tools before changing RTL. Keep 11a2b and
its occupancy/descriptor/admission substeps paused until that decision.

Use repeated START for coherent register reads. Define the snapshot's atomic point
and retain bytes through the read. Stage multibyte command fields and commit only
a complete accepted write. Specify partial writes, STOP, timeout, pointer bounds,
busy/overflow and application/POR reset behavior; none may partially program RAM,
release the lock or start an unvalidated image. Preserve accepted persistent work
and the association of each command with its admission-time reset/busy context.

Reuse the native Control loader owner, full-width image validation, CRC and SRAM
serialization. Do not create a second image store or programming owner. Keep
explicit flash persistence subject to the generic boot contract and source
payloads stable through actual consumer acceptance and native return.

This replaces the old 11a2/11a2b frame-admission and 13c snapshot plan. Decide
whether frame banks are needed at all. Only surviving banks need the R5 epoch/
stale-history redesign and the R6 private frame-route AND replacement with public
primitives. Remove obsolete banks, copies and receipts with the protocol. Test
wire-level repeated START, partial/oversized writes, pointer limits, lock, busy,
reset, coherent snapshots and the chosen host transition in both implementations.
Implement the replacement natively in both variants; Click physical optimization
remains frozen.

## External boot resilience and provisioning

The current ROM has one flash slot and I²C fallback. A/B selection and golden-image
recovery are new work, not existing guarantees. Specify the flash layout, golden
image placement/protection, versioned selection/commit metadata and bounded boot
attempt/fallback rules. Keep generic boot decisions separate from application
behavior; a golden application belongs in external storage, never mask ROM.

Factory programming must produce a bootable image set and verify read-back,
compatibility and CRC before release. Define how field updates preserve a usable
fallback and how loader locks apply. Test blank/corrupt slots, interrupted erase/
program/metadata commits, POR and watchdog resets, including failure of the chosen
slot and golden-image recovery. The programming lock is not protection against
arbitrary firmware GPIO writes to flash; any physical write protection must be
specified separately.

Measure reset-to-entry and worst-case fallback time at full configured capacity,
including flash transfer, CRC validation, SRAM copy and shared ADC-bus drainage.
Record work-clock edges and elapsed time for boot and ordinary firmware wakes.

## Retained services and arbitration (11c, 12, 13b)

Use a native MUTEX only for independent asynchronous requesters meeting in the
native domain; qualify metastability containment and ownership. Arbitration on
a real receiving clock is acceptable after the requests safely cross into it.
Neither approach may compromise fairness, accepted work or reset containment.

Acquisition has one consumer: the retained measurement/telemetry owner. CPU and
host read its coherent view; no independent Supervisor history or fan-out exists.
Keep elapsed ordering/reduction (12a) and GPIO/event history (12c) only for retained
application services, with bounded capacity, sample validity/age, set-wins events
and correct cancellation lifetimes. Retained residence does not imply POR-only
lifetime for every field. Output publication (13b) concerns generic GPIO and cadence,
POR input defaults, optional watchdog GPIO retention and mandatory SPI recovery
release. There is no board-owned power output or application-policy feedback path.

## Residual audit configuration matrix

Run item 16 once after A and B are integrated. Audit emitted owners, native/event/
periodic storage, reset domains, chip-wrapper state and actual clock sinks. Record
conditional owners and exclude unsupported combinations explicitly; do not revive
removed supervisor-policy configurations.

| Configuration axis | Required coverage |
| --- | --- |
| Production reference | Generic 2 KiB program / 1 KiB working SRAM, SPI boot, scheduled ADC and source-stopping LF sleep |
| Boot | Valid external image, I²C fallback and supported I²C-only builds; A/B/golden paths once implemented |
| Acquisition | ADC disabled/zero measurement channels, scheduled ADC, and autonomous ADC in supported legacy builds |
| Time and sleep | LF with service stopping on/off, plus legacy service-derived time without retained-sleep support |
| Capacity and schema | Supported minimum/non-power-of-two/reference capacities; generic GPIO/channel counts and sparse application words |
| Reset | GPIO retention on/off, SPI release, POR, repeated watchdogs and reset during committed work |
| Implementation | Full BD and Click ownership/sink inventories and functional regressions; BD physical qualification only |

SPI boot requires at least seven logical GPIOs and 256 bytes of working RAM.
SPI boot plus ADC requires explicitly scheduled acquisition; the autonomous ADC
combination is currently rejected. Use the actual parameter validators when
constructing the matrix. Reconcile the final inventory with item 17 clock/reset
constraints and retain a written reason for each clocked boundary.

## External application dependency

Groundlark firmware, its policy tests and board integration are maintained outside
this MCU workstream. Application compatibility is an integration dependency, not
permission to restore power policy, profile-owned GPIO masks or a supervisor in
RTL/ROM. Generic MCU verification uses generic firmware and peripheral stimuli.

## Routed hold repair

The former +0.729 ns feedback result has zero wire RC and is not a routed margin.
Reserve 0.05 mm² additional BD standard-cell area, separately from existing
electrical/CTS repair and whitespace. No reserve cells are inserted in advance.

After routing and electrical repair, enumerate every actual feedback/source-release
path with min/max extracted RC at all corners. Measure earliest next-data arrival
against the latest capture leaf plus its Liberty hold aperture, including the
source's real ACK reaction and return/rearm. Preserve phase-specific contexts and
fail on unresolved paths or out-of-table slew; do not borrow Control's margin for
other owners.

Only paths with failing composed hold get candidate delay cells, outside protected
primitives and on the affected data branch. Recheck setup at the earliest capture
leaf, ACK ordering, pulse width, return/rearm, graph equivalence and all sibling
loads after every repair. If a data buffer cannot repair hold without breaking
setup, revise the relevant capture/ACK ordering and remeasure it; do not blanket
buffer all payload bits. Record cell count/area, limiting pins and before/after
slacks in the existing run receipt and area ledger. The reserve is a planning
allowance, not permission to relax the hold requirement.
