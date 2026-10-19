# Single-writer Housekeeping view

Both variants read Housekeeping's retained native state directly. Services no
longer stores a second architectural state bank. Routed qualification remains
open; the measurements below are local repaired-netlist checks.

Housekeeping remains the sole native writer of time, deadline, lease, wake mask
and acquisition cadence state. Services keeps receiving-edge arbitration among
elapsed time, CPU writes, host period writes and recovery. No native MUTEX or new
periodic clock is introduced. The independent LF watchdog remains unchanged.

## Ownership and representation

BD replaces its wide feedback FIFO and Join operand with a one-bit seeded credit
and one closed architectural bank. The update stage explicitly receives the bank
and the accepted command as bundled inputs. A receipt ACK captures the result once;
a relative bank-to-feedback guard prevents reuse before capture completes. The
bank is initialized to `HousekeepingState.initial`, not an empty FIFO payload.

Click retains its existing seeded phase-decoupled state buffer. Its event-register
payload remains closed while idle. The unseeded **input ACK phase**, synchronized
at the receiving work-clock boundary, qualifies readers against the receipt ACK
phase. The seeded output phase cannot serve this purpose. Existing native Click
pulse, ACK guard and rearm rules remain in force; no four-phase adapter is added.

Services removes the state mirror and the two unused elapsed-age lanes from the
ordered and accumulated commands. Only nominal elapsed milliseconds plus a sticky
overflow flag enter Housekeeping. The independent upper-time coordinate receives
its conservative delta before this queue; sample age and staleness are unchanged.
Reply copies of unused elapsed/single fields are removed, not architectural state.

The physical LF/wake boundary retains its existing 32-bit consumed-time
acknowledgement, captured from the reply on the receiving edge. It has POR
lifetime, including maintenance and recovery receipts. Only this acknowledgement
drives consumedGray; native bank movement never enters the asynchronous
oscillator-wake reset cone. It is a crossing obligation, not a second writer of
Housekeeping's architectural state.

## Atomicity, reset and sleep

- While a reply is stalled, every reader sees the previous committed bank.
- On the receipt acceptance edge, clocked readers capture the whole old bank.
  They are inhibited during bank movement, then observe the committed bank.
- BD reopens readers after the existing registered receipt return. Capture and
  guarded feedback precede native reply withdrawal and synchronized ACK return.
  If A is the accepting work-clock edge, the two request synchronizers, registered
  ACK clearance and registered returning flag prevent a later read before A+5.
  Same-edge A reads still require the old-bank hold aperture. Tests bind the
  actual receipt and work clock, delay feedback, and reject premature readiness.
- Host status snapshots (including loader space 1), CPU MMIO preparation/admission,
  host-versus-CPU priority and acquisition retries must use the qualified view.
  WAIT remains parked and wake demand remains asserted while it is unavailable.
- POR reinstalls the initial native state and phases. Application cancellation is
  the existing ordered reset command: retained time/cadence survive; deadline,
  armed state and lease clear, and wake mask returns to 15. Accepted time is never
  replayed or canceled by watchdog recovery.
- The first command never waits for its own feedback. Both initial banks are
  valid immediately after POR; normal seed/start sequencing still applies.

The existing host snapshot storage and event arrival/clear arbitration are outside
this change. GPIO/ADC pin sampling, SRAM access and the clocked command arbitration
remain documented physical/ordering boundaries.

## Verification and remaining physical obligations

Keep the independent nominal-overflow and upper-age oracles, full borrowed-command
retention checks, reset ownership, event cutoff and sleep regressions. Native tests
must check the entire bank remains unchanged while speculative input changes and
replies stall. Integration tests cover snapshots before/on/after acceptance,
delayed feedback, concurrent host/CPU WAIT, POR and repeated watchdog recovery.

The BD feedback guard needs its own same-corner capture-to-Q/distribution envelope.
It follows capture and therefore **does not establish the same-edge clocked-reader
hold margin**. Independently measure ACK-to-bank-Q minimum hold, next qualified
read setup, transform bundling and bank-to-feedback composition. No other owner's
guard count or timing margin is a substitute. Click has functional verification
and area/sink accounting only, per the physical-work policy.

The retained-bank timing tool enumerates every first storage endpoint. Reached
SRAM pins, non-data storage pins and unknown clock domains fail; separately
inventoried native endpoints must belong to the audited primitive inventory.
A Liberty Boolean enclosure proves that all periodic reader inputs are independent
of bank movement while the returning flag is set. It frees unrelated inputs and
state and cuts only the reviewed keeper input arcs. The actual receipt ACK and
qualifier bind to the work clock. Qualifier propagation has its own one-period
setup/hold checks; it never receives the bank's five-edge bound. The functional
return monitor establishes the temporal assumption separately from the Boolean
proof. Native bank-to-update paths remain a separate composition obligation.

The proof preserves host selector correlation by exhaustively cofactoring the
16 actual work-clock selector Q bits. Both values are explored; a branch closes
only when every remaining reader is proven bank-independent. No internal decode
predicate is assumed. All selector Q paths receive the ordinary one-period setup
and same-edge hold screen, because steady-state correlation alone does not prove
decoder transitions harmless. Negative bypass controls cover both selector values.

The final repaired BD campaign checks ten PVT/slew cases. The 920 periodic
bank-reader endpoints have at least +192.568 ns later-read setup and +1.247 ns
same-edge hold. Bank-to-feedback ordering is at least +11.105 ns with nine DLYD
cells. The 17 returning/selector sources reach 1,074 periodic targets; their
one-period setup and same-edge hold minima are +0.834 ns and +0.482 ns. All ten
update-stage local cases are positive too. These are zero-wire-RC results without
CTS skew, not routed qualification. The [ledger](area-ledger.md) identifies the
run receipts and the separately inventoried native launch obligations.

Qualifier timing composes every reachable source, both launch polarities and its
loaded CLK-to-Q before selecting the worst arrival. In the STA search context
only, endpoint setup/hold costs are set to zero so either sink transition is
ranked by propagation delay. The final calculation restores the full worst
Liberty aperture, the 50 ns period and the two-sided 20% derate. Without that
separation STA ranks by slack and can select different, incorrectly ordered
minimum/maximum propagation paths. The coverage and reversed-bound checks stay
enabled; a source-winner-switch control checks the composition.

Electrical repair now exposes high-fanout ordinary hierarchy outputs to parent
drivers, in addition to the existing native output isolation. The complete graph
inventory selects the elapsed-valid and I²C readStart outputs in this design;
two repairable buffers remove the overloaded child readStart driver. Protected
native/SRAM interfaces, clock/reset/set cones, aliases and external ports are
excluded. Shared/nested wrapper tests and the full graph/exclusive-driver proofs
prevent bypasses or edits leaking into other instances. This is a combinational
mapping change, with no new clock or storage. It does not clear the outstanding
whole-chip routed electrical violations.

The starting Services contribution was 541 sinks: ordered 211, state 194 and
queued 136. Mapping measures **292 fewer Services work sinks in each variant**,
leaving 915 work and 14 service sinks. The 32-bit wake acknowledgement stays;
Click adds two crossing qualification flops outside Services. Remaining queue
bits have receiving-edge arbitration roles. The [area ledger](area-ledger.md)
records mapped/repaired area and the extra work-clock edges required by safe
reader qualification; this change is not a measured power reduction.
