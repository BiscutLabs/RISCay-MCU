# BD native Telemetry register view

This batch removes Services' clocked application/GPIO/pending projections. It
keeps **FourPhaseTelemetry as the sole owner**, with its existing command path,
reply receipt and ordered application-reset command. No second register owner,
native arbiter, new MMIO address, or application policy is introduced. Click is
unchanged. Digital verification is complete; physical qualification remains open.

## State and ABI

Telemetry stores configured application words, `gpioCount` output/OE bits and
six pending bits in one closed native event register. These fields are removed
from the feedback FIFO; its token carries sample state and a unit credit. The
update stage explicitly includes the closed bank in its input bundle, so its
transform has no hidden upstream data source. Samples, GPIO input sampling,
event accumulation/clearing, command scheduling and the host snapshot bank stay
on their existing paths.

Services reads that bank instead of maintaining payload mirrors. GPIO output,
OE, application selector and selected word retain MMIO offsets `0x18`, `0x1c`,
`0x30`, `0x34`. The selector remains in Control. Full-word aligned accesses are
required; partial masks fault, an undeclared selector write faults without an
effect, and absent host words read `0xffffffff` with their supported bit clear.
Pending/event registers preserve their addresses and clear semantics.

CPU reads still use the existing clocked MMIO/Control crossing. Admission waits
for Telemetry's outstanding/commit/recovery/command-return and reply-return barrier; unused
peripheral data is masked in unrelated Control commands. CPU writes keep the
existing validated Telemetry-command path. This batch does **not** implement
MMIO access with the work clock stopped. It removes copies, not that scheduler.

## Commit, pins and snapshots

The existing Telemetry reply receipt captures one authorization bit on its actual
work-clock `out.fire`. Its bank ACK rises only for a live or attributed recovery
publication, using the previous Services projection predicate. It stays high
through reply return, then clears before another acceptance. Revoked replies
still drain through the ordinary ACK without changing the architectural bank.
One application-valid bit clears on cancellation and becomes valid on a qualified
publication. During recovery return, pending readback uses the existing dispatched
events, retained until both the reply and recovery returns finish. Application
words remain masked until recovery finishes. These two control bits replace the
payload mirrors; no new event payload register is added.

The bank captures on that qualified ACK event. Native feedback waits for base
ACK and the relative settling guard before making another state token available;
full fork return retains the source payload. The owner has no periodic clock,
ordinary register or synchronizer. GPIO pads use closed bank outputs, plus the
existing reset isolation. An accepted GPIO write changes each pin at most once.

The host keeps its existing POR receipt and snapshot bank. Its acceptance is
qualified by the actual work-clock enable. **A snapshot coincident with a bank
commit captures the complete old bank; a later work edge captures the complete
new bank.** This coherence covers the application words selected by that snapshot.
Pending readback also includes the existing clocked incoming/dispatched event
accumulators; it is not a cross-space atomic snapshot of application and event
state. Dispatched events overlap native pending through full reply return, so an
Observe publication cannot momentarily remove a set event. New commands wait for
that return. The snapshot bank freezes its captured values for the serial read. No new
native snapshot contender or reset/replay boundary is needed.

That statement has a physical boundary contract, not just a simulation rule:

- The earliest receipt clock-to-Q, bank trigger-tree and bank-Q path must preserve
  the coincident host/Control capture hold aperture, including clock skew.
- The latest qualified-ACK-to-bank-Q and read mux path must meet setup at the
  next enabled work edge (50 ns at the maximum 20 MHz service rate).
- Earliest base-ACK-to-feedback capture must follow latest qualified-ACK-to-bank-Q
  and the next transform aperture. Compare at each corner using the project's
  20% two-sided derate and 2 ns residual floor.
- Preserve qualified/base ACK return ordering, bank data hold and reset propagation.
  New guard values are digital models until their actual loaded paths are measured.

## Reset

POR clears the closed bank and receipt. Application/watchdog reset uses the
existing synchronous cancellation and ordered `ResetApplication` command.
Application read views remain zero through recovery return. Pending projects only
fresh events after an attributed recovery publication, retaining them while the
return handshake retires. Ordinary GPIO is retained only when configured; SPI boot pins
3-5 always clear/release. GPIO isolation remains asserted through Telemetry's
recovery barrier so pre-reset enables cannot reappear before the native clear.
Raw watchdog reset is used only by the existing immediate pad-isolation path,
never as a bank data or capture qualifier. Samples, image, lock and SRAM retain
their previous lifetime rules.

## Evidence and remaining obligations

Baseline `4943239`: 4,125 periodic sinks (service 1,203, work 2,844, LF 78).
Services owns 14 service and 1,689 work storage cells plus three SRAM clock pins.
The removable register copies are 192 application + 14 GPIO + 6 pending bits.
The receipt and view-valid flag add two work-clock control bits; mapped counts are authoritative.

The reusable inventory command is:

```powershell
python tools/report_clock_owners.py build/generic-mcu-r10/map-bd build/native-app-registers/baseline-clock-owners.json
```

It preserves per-sink owner/domain/local-storage attribution and reports native
or unclassified clock pins explicitly. It is not a clock-tree or timing proof.

Tests cover sparse ABI/masks, GPIO transition counts, POR and both watchdog
retention options, repeated recovery, a revoked delayed completion, serial reads
during recovery, same-edge host snapshot/CPU commit, and continuous pending-event
visibility through Observe publication/return followed by an explicit clear. Existing event, sleep,
boot, loader and frozen Click regressions pass. Generation audit, RDC proof,
mapped/repaired area and actual wake windows are recorded below and in the ledger.
Routed min/max RC and targeted hold repair remain item 17.

The final fast gate (`build/native-app-registers/ci-r2/receipt.json`) passes
300 Python and 169 Scala tests. Both `export-r3` variants pass generation audit
and reset-crossing containment. Independent review identified recovery pin
isolation and event handoff hazards; the fixes preserve existing assertions and
retain dispatched events through both reply and recovery return. The earlier
failing run is retained as `handoff-r1.log`; its unchanged focused suites pass
in `handoff-r2.log` (25 tests). The 12-suite extended run passes 192 tests
(`extended-r2.log`, with reports in `extended-r2-junit/`). CI's original JUnit
reports are preserved in `ci-r2/junit/`, matching the receipt hashes, before the
extended run replaces shared sbt report paths. Final area and activity results
are recorded in the [area ledger](area-ledger.md#bd-telemetry-register-view-slice).

### Physical status: unqualified

The repaired `map-bd-r2` preserves all native primitives and uses nine DLYD cells
for this owner's new feedback guard. Its own loaded, same-corner screen covers
five corners and two source slews. With the 20% two-sided derate, earliest
feedback follows latest bank Q by at least **12.639 ns**, above the 2 ns floor;
no other owner's measured delay is borrowed. The zero-wire host-snapshot screen
has at least **19.545 ns next-edge setup residual** and **0.816 ns same-edge hold
residual**. Clock skew, extracted wires, electrical/table-range acceptance and
the full source-hold/return composition are still open. These are screening
results, not physical acceptance (`bank-screen-r4/`).

The standard update-stage campaign resolves eight of ten cases with positive
local bounds. Fast/hot and fast/cold at 2 ns input slew fail `RELATIVE_NUMERIC`
on negative NLDM min-path results; the campaign remains failed/unresolved, with
its logs retained (`telemetry-stage-r2/`). The broad, unconditioned bank/valid-to-
clocked-consumer screen also has a **-30.458 ns next-edge setup residual** and
**-0.026 ns hold residual**. The digital return barrier excludes new commands
and dispatched events overlap bank updates, but this is not a timing waiver:
prove each receiver's actual qualification and earliest reopening, then close
all enabled paths and apertures. Do not infer full-chip timing closure from the
positive snapshot or feedback subsets. Routed qualification and failing-path
hold repair remain part of item 17.
