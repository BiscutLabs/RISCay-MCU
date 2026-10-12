# Native I2C frame delivery and admission

Checklist item 11a1 is digitally verified. It removes the redundant clocked frame
copy in each design. The following two-slot mailbox and dispatch logic remain
clocked and are scheduled for items 11a2 and 11b. This is not physical timing
qualification or completion of the deeper asynchronous migration.

## Retention and acceptance

`FourPhaseFrameReceipt` and `ClickFrameReceipt` are separate implementations.
Each transports the native I2C publisher's retained 337-bit frame directly to
the existing service admission logic. There is no new payload register. The
receipt owns five POR-only clocked bits: two request synchronizers, one retained
acknowledgment and two local reset-release stages. Click compares native request
and acknowledgment phases; it has no four-phase adapter.

The receipt observes a pending native offer on the ungated service clock. Its
ready input requires both the target's local POR release and the destination's
actual work-clock enable. In low-power builds this enable is the existing
falling-edge `RetainedClock` register; in ungated builds it is literal true.
The receipt acknowledges only on an accepting rising edge. That same edge
delivers `host.frame.valid` to Services and writes the selected mailbox slot.
Ready is not qualified by mailbox capacity: offering a third accepted,
undispatched frame must still trip `CONTROL_HOST_MAILBOX_OVERFLOW`.

A pending receipt contributes to ungated I2C busy/wake demand even with ready
low. It must not be reduced to a one-cycle delivery indication. Native frame
and snapshot pending state, sampled activity and START/STOP demand retain their
existing roles; the seven-edge ordinary clock-drain guard is unchanged.

BD retains acknowledgment until the synchronized request returns low, and the
publisher retains its frame through the complete native return. Click retains
the accepted phase until the next acceptance. The native publisher cannot
replace the frame while request and acknowledgment differ. Application reset
does not reset either publisher or receipt; POR aborts both lifetimes.

## Context and mailbox semantics

The source packs 264 byte bits, a six-bit length, overflow, sampled reset and
busy flags, and a 64-bit reset epoch. The existing mailbox stores a 273-bit
`ControlIngress`; the epoch feeds reset classification rather than being stored
there. Item 11a1 preserves this distinction and does not remove queued reset
debt. Item 11a2 must retain epoch identity through native Host dispatch.

At admission, reset context includes the sampled flag, current reset and an
epoch mismatch. Services also joins its synchronized application-reset state.
Busy context includes sampled busy, physical program activity, pending loader
effects, pending loader Control work and a loader command accepted on that same
edge. Later idle observations cannot erase this history. The epoch is POR-owned;
wrap is rejected and is outside the supported lifetime.

With zero queued frames, admission writes the first slot. With one queued frame
and no dispatch, it writes the second. Simultaneous admission and dispatch with
one queued frame replaces the first slot after its previous value is captured
by Control. A full mailbox rejects another offer, including a simultaneous
dispatch. These are the existing capacity and overflow rules.

## Timing obligations

The request synchronizers provide two service periods between the earliest
request observation and receiving acceptance, in addition to the native output
guard. This gives at least 100 ns at the supported 20 MHz ceiling in the digital
model. It is not a substitute for checking the complete publisher-to-mailbox
path, including byte routing and epoch/context logic.

Qualification binds the actual native `frame_payload.q`, receipt ports,
selected mailbox data/load expressions, work clock and destination registers.
Check all 337 source bits, all 273 destination bits, both slots, opposing native
delays, service-frequency limits, held offers, immediate reuse and reset overlap.
The retained native bus must meet the 100 ps digital setup/hold aperture.
Synchronous context sources require separate pre-edge identity and post-edge
capture checks; zero-delay RTL flip-flops do not establish their physical hold
time. Any excluded simultaneous context transition must be identified explicitly.

The five-bit receipt, its two-flop synchronization, gate handoff, metastability
resolution, reset recovery/removal, epoch comparison and mailbox setup/hold all
require physical qualification. Earlier P&R results do not qualify this path.

## Verification scope

`FrameReceiptSpec` covers both native protocols, all source bits, backpressure,
POR, application-reset isolation and stopped front/work clocks. The existing
I2C wire, earliest-status, ring, overflow and reset-history tests retain their
functional assertions and deadlines. The composed `FrameAdmissionSpec` and `FrameWakeSpec`, 56 positive capture
replays and 32 exact negative controls exercise the actual publisher-to-mailbox
path; standalone receipt tests alone are insufficient.

Fresh production declaration and ABI comparison records a verified reduction
of 339 periodic-clocked RTL bits per variant and unchanged 34-port public tops.
The old frame bridge held 344 bits; the replacement holds five. The independent
15-bit snapshot bridge remains, so I2C delivery now totals 20 bits. The 550-bit
mailbox/count/reset-debt group is unchanged. These are emitted RTL counts, not
mapped area, power or a minimum-state result. Evidence is retained under
`build/async-host-frame-migration/qualification-evidence.json`; the complete
cohort, failure history and review scope are in [build and test](build-and-test.md).
Native payload/epoch ownership and native credit observation are separate
11a2a/11a2b obligations. Any temporary narrow occupancy count remains explicit;
physical return must not hide a later full-queue offer.
