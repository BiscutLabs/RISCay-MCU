# BD Housekeeping compact effects

Batch 4b follows Telemetry commit `c8bcb74`. Click and shared reply schemas
remain unchanged under the BD-only user override. No new clock, synchronizer or
native arbitration is introduced.

Housekeeping retains one 259-bit closed state bank, the existing 147-bit command
Join operand and seeded feedback credit. Its one parent transition computes both
next bank D and publication effects. The child identity stage stores 41 bits:
recovery, timeValid, tick, due, leaseExpired, startAdc, kick, resetApplication,
cpuCompletion and the 32-bit consumed value. Keeping the arithmetic in one parent
avoids duplication across preserved synthesis hierarchy. Stored payload is
676 -> 449 bits. The [area ledger](area-ledger.md#bd-housekeeping-compact-effects)
records whole-chip mapped/repaired savings separately.

## Commit and lifetime

The ordinary registered reply ACK still captures the state bank exactly once.
Effects are captured from the pre-commit state before publication and remain held
through the reply; due, kick and cadence effects do not recompute after bank Q moves.
The next-state transition and all existing overflow, deadline replacement, lease,
period/discard and reset precedence remain unchanged.

Services captures reply.consumed on the original housekeepingReply.fire edge into
the same POR-owned consumedTimeAck. Reading housekeepingView.consumed there would
capture the old value and replay elapsed work. This crossing acknowledgement is
retained for LF progress/wake ownership; it is not replaced by a live native wire.

Services' housekeepingOrdered is the external borrowed command bank. Existing
outstanding, sender-idle, bankReady and overwrite assertions protect its lifetime.
The Join's native output ACK is C(update input ACK, reply ACK), retaining the accepted
command through bank capture and both ACK returns. The existing both-edge bank
feedback guard orders reuse after bank movement. Neither this guard nor held
command identity proves same-event state-Q -> state-D hold.

POR reinstates HousekeepingState.initial. Application recovery remains an ordered
command: deadline, armed, lease and wake mask reset as before; time and acquisition
cadence survive. Accepted elapsed time is not canceled or replayed. Event pending,
clear cutoff, WAIT arbitration and the independent watchdog remain unchanged.

## Reader and timing obligations

Same-edge readers still capture the whole old bank; bankReady inhibits later reads
until guarded publication and synchronized ACK return. Host snapshot/readStart,
CPU admission, cadence retry and WAIT/sleep qualifications are unchanged. The
receipt itself still operates on the actual work clock.

Measure the full original-command/closed-bank transform into the state-bank D and
the effect-stage D. Parent effect_transform_path must compose through update's
passive alias into the actual latch capture; timing only the child's identity
transform omits the arithmetic. All aggregate endpoints have explicit widths.
Measure source retention, state feedback min hold, bank capture-to-credit reuse,
periodic-reader setup/hold and the separate one-period qualifier/selector paths.
Do not apply the bank's multi-edge read bound to those qualifier paths.

Keep the independent Housekeeping expected states and elapsed/overflow oracles.
Run AsyncHousekeepingSpec, deadline/lease/cadence, borrowed-command/reset, WAIT,
sleep/deep-sleep and wake-activity suites, plus CI/export/RDC. Record area, DLYD,
periodic/Services sinks and wake activity against batch 4a. The [independent review](reviews/bd-housekeeping-effects.md) records the new
full-transform/capture binding and limits; extracted min/max RC remains item 17.
