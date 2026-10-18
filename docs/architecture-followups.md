# Architecture-first follow-ups

BD is selected for tape-out, subject to physical qualification. Click remains
a native, independently implemented functional reference. Keep its regressions
and correctness/ABI fixes; stop Click-specific sizing and physical campaigns.
An architecture change may diverge internally while preserving the common ABI.
Record that divergence rather than silently calling both implementations equal.

## Current baseline and order

1. **Done locally:** generic SPI boot, removal of all fixed application policy,
   and Python suite cleanup (1,202 to 292 tests) plus a main-push CI workflow.
   Commit `d690e8f` is verified and local. GitHub publication and the first hosted
   CI run await a credential with `workflow` scope. Groundlark firmware is outside
   this repository's workstream.
2. **Build reproducibility:** consume exact chisel-async source `83d6468` directly
   in sbt. This includes `06b1216`'s passive primitives and the structural audit.
   No local SNAPSHOT publication is needed.
3. **Always-on/application split:** establish reset, ownership and demand
   boundaries before moving state. The initial proposal below uses one supply;
   physical power gating requires a separate isolation/retention implementation.
4. **Register-pointer loader:** define the host wire ABI before implementing it.
   The initial proposal adds it alongside the framed interface, preserving current
   hosts. It must reuse the same native loader owner and compatibility/CRC rules.
5. **BD request guards:** regenerate the inventory after those architecture changes,
   then size every surviving canonical request guard in one same-corner campaign.
   The historical 89 count predates supervisor removal. Include source launch,
   data/setup, feedback hold, ACK, reset and throughput; keep absolute pulse floors.
6. **Full routed qualification:** electrical repair, composed min/max-RC timing,
   reset distribution, macro timing and measured mismatch envelope. Locally
   measured counts can be adopted beforehand; shorten nothing on simulation alone.

The [statistical screen](../analog/gf180-guard-variation/README.md) passes 192
samples with both ratio tails checked and timestep/seed controls. It supports
keeping the engineering derate. It does not qualify all stages for shortening
or change the architecture-first order.

## Verified follow-up batch

- A fresh source tree, empty Ivy repository and fresh sbt Git staging directory
  build the exact library source and pass 31 core/schema/fabric tests
  (`build/source-clean-r1.log`). No locally published library is used.
- The full fast gate passes 292 Python and 166 Scala cases with the source-built
  JAR in its receipt (`build/followup-ci-r1`). After adding two statistical-screen
  property checks, all 294 Python tests pass on Windows and Linux
  (`build/followup-python-r2`, `build/followup-linux-python-r1`). Linux has only the
  documented Windows-path skip. The 31 clean-build tests overlap the 166; do not
  add them to claim a larger distinct test count.
- The final Monte Carlo screen is `build/guard-mismatch-r3`; the first convergence
  failure and the superseded one-tail r2 result remain available.
- Fresh independent review corrected two-tail statistical acceptance and the
  proposed ownership table's reset semantics. No review blocker remains.

This follow-up changes build resolution, characterization and planning only. It
adds no RTL, guard cells or clocks, and claims no new mapped/P&R measurement.
The latest area remains the generic-MCU batch in the ledger. The island and
register-pointer sections below remain proposals awaiting their boundary/ABI
decisions; no architecture migration is counted as complete here.

## Proposed ownership split

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
schemas, with one ownership crossing per subsystem where possible. Do not add a
payload mirror merely to cross the new module hierarchy. Verify reset during host
upload, ADC completion, CPU RAM traffic and sleep, including repeated watchdogs.
Measure area, sinks and wake activity before accepting any migration.

This is a proposed logical boundary, not implemented power gating. Separate rails
would additionally require isolation, retention cells, supply sequencing and an
external-memory/pad strategy before RTL work starts.

## Proposed register-pointer loader

Preserve the existing framed loader until the host ABI decision is settled.
Reserve a distinct extension opcode so old SELECT/BEGIN/WRITE/COMMIT/START/LOCK
frames remain unambiguous. The pointer identifies a byte-addressed register
window; repeated START reads a coherent snapshot and advances the read position.
Stage multibyte command fields, and commit a command only after its complete
write is accepted. Partial writes, STOP, timeout and reset must never partially
program RAM, release the lock or start an image. Report errors through existing
status. Range overflow must reject, not wrap into another register window.

The register front end must drive the existing native Control loader path,
including full metadata validation, image CRC, programming serialization and lock
enforcement. It must not create a second image store, policy engine or independent
programming owner. Explicit persistence remains subject to the generic boot
contract. Gate acceptance on the real consumer edge and keep payloads held through
native completion. Add wire-level repeated-START, partial/oversized write, pointer
boundary, busy, lock, reset and old-host compatibility tests in both variants.

Exact register allocation and command framing remain to be specified before RTL
changes; this document does not claim a new host interface already exists.

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
