# Native event ownership

**Status: baseline and shared behavioral oracle; native conversion is not
implemented.** Production RTL remains at `49ca683`. In particular, event ingress,
clear masking and WAIT admission still run in Services. No guard value or physical
margin is established by this document.

Architecture conversions now cover both independent implementations. BD remains
the physical tape-out target. Click must keep native phase signaling and gets the
same functional conversion and tests, without a Click physical/sizing campaign.

## Sources and consumers before conversion

The following inventory applies to both Services implementations. “Native origin”
does not mean the current event delivery path is clockless.

| Bit | Event | Origin and present commit point |
| --- | --- | --- |
| 0 | Tick | LF Gray timebase crosses to service/work; elapsed scaling publishes a nonzero elapsed interval. With no low-power timebase, the work-clock millisecond divider supplies it. Services recognizes `elapsed != 0`. |
| 1 | Due | Native Housekeeping computes deadline expiry; Services recognizes an accepted, eligible Housekeeping reply. Replacement suppresses the old deadline's event at the ordered write boundary. |
| 2 | GPIO | Two service-clock input synchronizers, then work-clock previous-sample comparison masked by `gpioEventMask`. SPI boot pins 3–6 are excluded. |
| 3 | Acquisition | Accepted physical ADC result **or a validated CPU measurement publication** for a software-owned channel. The physical ADC has native assembly/scaling but its result currently crosses into Services. |
| 4 | Lease expired | Native Housekeeping computes expiry; Services recognizes the accepted, eligible reply. |
| 5 | Host wake | Native Control accepts valid host opcode 8, then its clocked reply commits the effect. This is not raw I2C START or receipt of an unvalidated frame. |

SDA START independently requests the service oscillator through the retained wire
wake path. It must remain usable with the service clock stopped, without turning
every START into a host-wake pending event. Unsampled GPIO differences also retain
their existing asynchronous oscillator-wake path with the same SPI exclusion.

| Consumer | Current observation |
| --- | --- |
| MMIO read, offset 12 | `pendingView`, selected through Services/Control |
| MMIO clear, offset 12 | Masked by events accumulated since request arrival, including stalled admission |
| WAIT read, offset 16 | Completes only when `pendingView & (wakeMask | 0x30)` is nonzero; returns pending bits |
| Sleep entry and maintenance kicks | Parked WAIT, lease, native admission credit and existing drain/busy conditions |
| Wake demand | GPIO/SDA physical paths, LF work, and existing service work/drain demand |
| Host low-power status, space 3 / instance 0 / word 5 | Pending captured with the selected bank at `readStart`, then held for the I2C read |

BD's pending projection reads the closed native Telemetry bank plus queued and
dispatched events; Click additionally has a clocked pending mirror. Neither Fabric
currently routes app/GPIO MMIO directly to Telemetry. The prerequisite is still
open in **both** variants: keep Telemetry as the owner, separate its CPU-written
bank from sample observation work, and provide a native CPU endpoint. Connecting
a second requester to the existing Telemetry command port is not a solution to
the single-writer requirement.

## Shared executable rules

[`EventReferenceModel`](../verification/src/test/scala/riscay/EventReferenceModel.scala)
is the common oracle for future BD and Click tests. It uses unbounded occurrence
numbers; it is not a proposed hardware counter width. The implementation must
prove that its finite encoding has the same observable behavior.

1. Every admitted event occurrence sets its bit. Repeated occurrences coalesce
   in the software-visible bit. A clear with no newer events consumes all observed
   occurrences of the selected bits in one operation.
2. A clear saves a watermark **at request arrival**, before admission can stall.
   At commit it removes only occurrences at or before that watermark. Later
   occurrences survive, even if the source was already pending when clear arrived.
   An event on the arrival edge also survives: test drivers take the watermark
   before applying raises for that logical instant. This preserves the existing
   set-wins rule rather than treating a simultaneous event as already observed.
3. A successful deadline replacement consumes old due only. Conceptually each
   deadline has a generation: an old generation cannot publish into the new one,
   while a new already-expired deadline may raise fresh due. Rejected writes do
   nothing. The model's tags specify the ordering to prove, not implemented RTL.
4. WAIT tests the requested mask plus unconditional bits 4 and 5. Acceptance
   consumes the sleep lease through the existing Housekeeping ordering. Parking
   alone does not consume admission credit or bypass drain/busy conditions.
5. Application cutoff clears application pending state and discards event ingress
   while cancellation is asserted. Fresh events after reopening survive an old
   reply's return. Cancelled clear watermarks and old deadline generations cannot
   act on a new lifetime. POR also resets the source/owner transport together.
6. Snapshot atomicity remains the existing whole-bank `readStart` capture: pending
   in that snapshot is held through the host read. A continuously changing native
   view cannot simply be wired into a clocked multibit capture without proving its
   crossing and acceptance aperture.

The decisive existing arrival regression is
[`AdmissionSpec`](../verification/src/test/scala/riscay/AdmissionSpec.scala): a clear
waits behind a previous response, GPIO changes three service edges later, and the
event must survive even after fifty stalled edges. Moving the cutoff to eventual
source acceptance or MMIO commit would change the ABI and fail this test.

## Counter protocol rejected by independent review

The suggested two-bit Gray counters, saturated at two outstanding generations,
cannot implement rule 2 by assigning `acked = observedRaised`:

| Step | Raised (binary) | Acked (binary) | Meaning |
| --- | ---: | ---: | --- |
| Two old events | 2 | 0 | Source is at its credit limit |
| Clear arrives | 2 | 0 | Clear saves watermark 2 |
| New event after arrival | 2 | 0 | Saturation coalesces it without a state change |
| Clear commits | 2 | 2 | Pending incorrectly disappears |

The trace without the new event has exactly the same stored state. The two cases
require different results, so this is an information loss, not a guard-sizing
problem. ACK 0→2 also maps Gray 00→11, changing both bits. Merely sequencing the
ACK through intermediate values fixes neither the lost event nor the clear cut.
Clearing only one credit keeps pending after two old events and therefore changes
the coalescing behavior. A sticky overflow flag by itself moves the saturation
point without resolving the indistinguishable histories.

`EventReferenceSpec` retains these executable counterexamples, the illegal-wrap
negative control, and independent occurrence-set stress over 80,000 steps. These
are model tests, **not tests of a new BD or Click implementation**. No RTL is
adopted from the rejected sketch. The review did not prove that all designs
without arbitration are impossible. A replacement needs a retained-history and
crossing proof, or an explicitly agreed architecture change; a later source-local
clear cutoff must not silently replace the existing arrival cutoff.

## Implementation and qualification still required

- Native app/GPIO routing in both variants, with sole Telemetry ownership, closed
  pad storage, atomic host capture and coordinator-managed application clearing.
- A finite source protocol proven against the shared oracle, including saturation,
  reset/rebase, every crossing transition and arbitrary response backpressure.
- BD four-phase event read/clear/withheld WAIT response with full return to zero;
  independent Click phase implementation with ACK guard, rearm and pulse bounds.
- Source effects originate at the validated native commit points above. Retain
  only physical sampling/CDC state at clocked sources. No event transaction goes
  through Telemetry and no new clocked stage is inserted in a native path.
- Remove Services event accumulation, dispatched sets, mirrors and MMIO masks;
  remove event/clear/pending fields from Telemetry schemas and reset transitions.
- Synchronize one parked indication into sleep control; preserve stopped-clock
  GPIO/SDA wake, lease consumption and all source/drain conditions.
- Run the new randomized native/source-phase tests and identical histories on
  both implementations, existing behavior suites unchanged, both RDC proofs,
  fast CI and StructureAudit on all four exports. Verify Click has no four-phase
  adapter in this path.
- Measure after-area, clock sinks and wake activity against the baseline in the
  [area ledger](area-ledger.md#native-events-baseline). Size BD guards from this
  owner's same-corner paths, not another owner's measurements. Full routed
  qualification remains item 17; no Click timing/sizing campaign is authorized.

## Preparation evidence

The final fast gate (`build/native-events/ci-baseline-r2/receipt.json`) passes
300 Python and 185 Scala tests. Separate baseline runs pass both activity cases
and the ten existing BD/Click admission cases, including the held-clear race.
Both production RDC audits pass with zero violations, and strict generation
checks pass on both clean functional exports and both physical exports. These
results establish the unchanged chip baseline, not a converted event path.

Independent review rejected the saturated-counter sketch and required an explicit
same-arrival-edge set-wins rule in the oracle; that rule and its focused test are
included in the final gate. Review found no remaining issue with this preparation.
The rejected attempt to audit a simulation fixture is retained in
`baseline/functional-four-phase/`: that fixture substitutes simulator cell models
and fails the canonical RTL digest check. The clean `functional-exports/` emitters
pass without modifying the checker or manifest. Area and physical timing are
unchanged; the no-arbiter protocol decision and all implementation work above
remain open.
