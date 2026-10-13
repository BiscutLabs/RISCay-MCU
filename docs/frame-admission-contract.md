# Native I2C frame delivery and admission

Item 11a1's payload-free original receipt is digitally verified and committed.
Item 11a2a moves accepted payload/epoch retention into separate native BD and
Click banks. Digital qualification and independent review pass. Narrow logical
credits, descriptor ordering and dispatch remain
clocked for 11a2b/11b/14. No physical timing or minimum-state claim follows.

**R3 completion repair is digitally verified, 2026-10-13.** The implementation below replaces the
old copy-before-receipt timing assumption with an explicit completion condition.
Fresh independent review and affected verification/export/cost checks pass in a
separate R3 campaign. Complete physical qualification remains open. Historical timing evidence
and the failed physical copy assumption remain recorded below.

## Events, retention and acceptance

O is the original native I2C publisher's completed-frame offer. O_f is a work edge
on which that original request receipt is valid and its work gate is running,
independent of native copy completion. A is the receipt's actual accepting
service/work-clock edge, now qualified by synchronized copy completion. D is the actual selected Host
`ControlCommand.fire`. These are distinct events; native copy completion is
neither A nor D. O, A and D retain independent testbench ordinals; O_f records
the clocked observation of the original offer.

`FourPhaseFrameReceipt` and `ClickFrameReceipt` retain five POR-owned clocked
bits each: two request synchronizers, acknowledgment and two local reset-release
stages. They transport the publisher's held 337-bit frame without another
payload register. Their ready requires local POR release, the actual work
clock's running state and copy completion. A changes the receipt's retained ACK
and captures one narrow descriptor on the same edge. The publisher's ACK then
changes through a native completion join; it is not an additional clocked capture.
The original receipt remains on the ungated
front service clock; the falling-edge retained gate still controls work edges.

Original request observation and `host.frameOffered` do not depend on bank
availability or copy ACK. `frameOffered` is original receipt valid AND actual
work-gate running, while `frame.valid` remains actual A. Full logical occupancy
does not conceal O_f: a third offered frame trips `CONTROL_HOST_MAILBOX_OVERFLOW`
at the eligible observation edge even if copying is delayed and even with D on
that same edge. When D occurs one edge earlier and copy is complete, A succeeds.
Keep Q=A-D,
0<=Q<=2, independently of physical native-bank return occupancy.

The source packs 264 byte bits, six length bits, overflow, sampled reset/busy
flags and a 64-bit reset epoch. Four fixed physical banks each retain all 337
bits. The ring tail advances modulo four at A. Banks finishing an old return
are separate from the two accepted-undispatched logical credits. These extra
banks provide return spacing; they never authorize a third logical credit.

BD borrows original REQ and payload, captures the two-bit route natively, and
holds that route through the complete original RTZ. Advancing the clocked tail
at A cannot redirect the still-high old REQ. Four independent LongHoldBuffers
retain payload through native head acceptance and complete return. Availability
requires input and output REQ/ACK idle plus a 32 ns internal-return guard.

Click sends original phase directly into the native request comparison. A common
atomic pending-and-available event captures four payload registers, four bank
phase registers and one global accepted-phase register. Unselected registers
retain their own complete feedback. Each bank toggles its own phase; four global
offers later the global phase has repeated and cannot identify that bank's new
transaction. Availability checks both retained and guarded output phase against
head ACK. There is no phase-masking mux, RTZ adapter or periodic capture clock.

Two additional POR front-clock registers synchronize the native copy ACK. BD's
ready requires its synchronized high level; Click's ready requires synchronized
copy phase different from the last clocked receipt ACK. Click does not compare
the raw native request in a clocked acceptance cone.

Publisher ACK is a native C-element join. Click joins the raw copy and receipt
phases. BD joins raw copy ACK, receipt ACK AND synchronized copy ACK: its falling
return cannot complete until the clocked observation has returned low. This
prevents a fast next request from reusing the preceding synchronized high copy
level. Both source request and payload remain retained until their joined return.
The tail advances only at A, so a slow Click copy cannot see the next slot.

Copy ACK is still checked at A together with exact 337-bit identity. These
assertions alone cannot distinguish an old equal payload.
Qualification therefore also checks actual O-time complete availability, capture
ordinals, identical consecutive frames, all four bank wraps and unavailable-bank
faults while keeping original O visible.

## Context and head dispatch

Two four-bit descriptors retain bank ID and reset/busy context through A. A two-bit
clocked Q retains the exact original capacity/overflow decision. With Q=0, A
writes the first descriptor. With Q=1 and no D it writes the second. A+D at Q=1
replaces the first after its old command capture; Q=2 plus A faults regardless
of D; the independent O_f check diagnoses a full queue before delayed A as well.
Both descriptors, Q and tail are POR-owned.

At A, reset context joins the sampled flag, current reset, source/current epoch
mismatch and Services' synchronized application reset. Busy context joins sampled
busy, physical program activity, pending loader effects/control work and an older
Host loader command dispatched on that same edge. Two POR-owned one-bit facts
also accumulate these exact context cones on each O_f while copying delays A.
The descriptor ORs retained and current context; the facts clear only on actual
accepted enqueue. Later idle or application-cancel release cannot erase a fact
seen at the former accepting opportunity. Epoch comparison still independently
detects complete watchdog episodes; equal epochs are not a substitute for held
admission context. Stored command/reply-edge tests retain their old assertions.

Each bank has a separate five-bit payload-free head receipt on the ungated front
clock. Only the descriptor-selected valid head may feed Host dispatch. Its ready
requires actual Host D and work-clock running. D retires that descriptor and
acknowledges that same bank once. Nonselected banks and non-Host winners cannot
retire. A queued descriptor waiting for head synchronization retains priority
over CPU MMIO; `mmioLaunch` must require the descriptor queue empty.

The retained raw epoch survives through D. Reset context at D includes A's
retained context, current application reset and raw-bank/current-epoch mismatch.
Current epoch includes a coincident increment. This replaces queued reset debt
and catches complete intervening watchdog episodes, including multiple episodes
before D. Epoch wrap remains a fatal unsupported lifetime boundary. Program busy
at D includes retained A context and current program activity. The existing
ControlCommand crossing captures the final command; no new wide clocked head
copy is introduced. Post-D START recovery and persistent loader effects retain
their original rules.

Application reset resets neither publisher, bank, descriptor, tail, epoch nor
receipt phases. POR aborts their shared lifetime. Stored/MMIO commit/reset/HALT
precedence and the one-outstanding Control dispatcher remain unchanged.

## Digital timing and fixed-ring obligations

SocParameters accepts 1 kHz through 20 MHz: periods of 50 through 1,000,000 ns.
The principal measured sweep covers 3.2 through 20 MHz (312.5 through 50 ns);
that campaign does not redefine the wider parameter contract. Original receipt
observation provides at least two periods from O to A, hence >=100 ns at 20 MHz.
That is only a lower bound on A. **The old prohibition on waiting for copy is
removed by R3.** A now additionally waits until two copy synchronizers observe
the correct completion. Copy may take longer than two service periods without
admitting an unfinished payload or advancing its slot. This is handshake
completion, not a larger assumed delay guard.

BD's route data path has a complete 10 ns budget and an 11 ns request delay.
Route capture Q is bounded by O+21 ns and decoded selection by O+31 ns. A 32 ns
request guard precedes a preserved atomic AND (1..10 ns), followed by the native
bank's request/capture/ACK path. The resulting copy-ACK bound is:

    32 + 10 + 11 + 10 + 10 + 10 = 83 ns from O.

This historical digital copy bound did not prove the old 100 ns physical race
safe: measured 32 ns guards alone ranged roughly 51-211 ns. The implementation
must no longer depend on copy finishing before that original accepting edge.

Click's complete 1,352-bit selected/unselected transform includes every payload
and phase feedback bit. Its source endpoint is 1,691 bits (slot + source + old
bank state). With 10 ns data and 11 ns request delays, 1..10 ns comparison,
atomic capture and register cells, guarded copy ACK is bounded by:

    11 + 10 + 10 + 10 + 32 = 73 ns from O.

All nine Click trigger pins require setup/hold, high/low pulse and distribution
checks. The shortest high-pulse path is bank-phase feedback plus the atomic AND:
its minimum is 2 ns, not the ordinary Click three-cell minimum. The digital
aperture/distribution assumptions are 100 ps. A 110 ns bank output guard is
separate from copy ACK. These bounds require complete mapped path/distribution
qualification; the fixed digital delay is not an additional decorative buffer.

For the fixed ring, the historical analysis used S(T) as an earliest-next-O
lower bound after A and P(T) as minimum A spacing:

    S_BD = (ceil(111/T)+2)*T + 115 ns
    P_BD = (ceil(111/T)+ceil(115/T)+4)*T
    S_Click = 114 ns
    P_Click = (ceil(114/T)+2)*T

These formulas describe the older digital publisher/receipt path. R3 preserves
A as the actual descriptor capture; O_f names the earlier eligible observation,
not a new acceptance event. Waiting for copy, the native ACK join, and BD's
synchronized-low rearm add nonnegative delay to the old earliest-next-O and
A-spacing paths. Thus the formulas remain conservative lower bounds under their
original cell/digital assumptions; they are not exact new ACK latencies or
maximum service deadlines. Receipt ACK still changes at A, while native ACK
follows the characterized join (1-10 ns in the digital cell campaign).
Re-run actual return/capture monitors with those distinct endpoints. In particular,
BD source return must include clocked copy-low before reuse. Arbitrarily prolonged
copy/return stalls are governed by the handshake, not the old 83/73 ns equations.

FIFO ordering and Q<=2 imply D_i <= A_(i+2)-T before legal reuse. Old source
input/capture feedback must also be quiet by that point: BD's selected input
REQ/ACK return is bounded by 32+10+11+10=63 ns after original REQ falls, before
the original synchronized ACK return and next publication; Click's global
capture/ACK feedback settles before the next original O. Anchor physical bank
return at the later of D_i and old-input quiet, never at an early D alone.

Using a conservative 110 ns BD output-return guard, including a missed receipt
edge and the actual 32 ns availability guard, the conditional return bounds are:

    R_BD <= (floor(120/T)+3)*T + 32 ns
    R_Click <= 20 ns after old capture feedback is quiet

The reuse-O age is at least T+P+S; bank readiness by A_(i+3) gets T+P. Evaluating
all ceil/floor breakpoints over 50..312.5 ns gives minimum
margins of 543 ns BD / 379 ns Click at reuse O, and 198 ns BD / 265 ns Click by
A_(i+3). For T>120 ns the margins simplify to increasing functions:

    BD: reuse 7*T+83 ns; ready-by-A_(i+3) 4*T-32 ns
    Click: reuse 4*T+94 ns; ready-by-A_(i+3) 4*T-20 ns

Thus the same minima cover the entire accepted interval through 1,000,000 ns;
slower periods do not require another bank. Supplemental 1 us and 1 ms period
controls exercise the slower arithmetic regime without changing original
real-wire test deadlines. These are conservative digital arithmetic obligations,
not physical signoff. Directed campaigns must independently observe complete return and
exercise the quantization boundaries, including 50, 57, 57.5, 60, 111, 114, 115,
120, 125 and 312.5 ns. Unbounded forced return stalls must diagnose unavailable
reuse; finite bank count cannot make such stalls safe.

Once copy completion is available, the logical D-to-next-A admission decision
remains at most one 50 ns service period. Copy completion is an additional
prerequisite, so that statement is not a bound on the total O-to-A latency.
Additional physical banks do not solve that native-credit proof. Item 11a2b must
remove Q only with a reviewed path satisfying both next-edge release and
same-edge-full rejection. Otherwise Q remains explicitly temporary while the
native dispatcher removes the periodic edge dependency.

## Sleep and physical obligations

Original pending receipt demand, descriptor occupancy, head receipt busy and
two-stage synchronized native-store busy cover speculative copy, logical work
and complete native return. Q=0 alone is not quiet. Actual A/D require actual
work edges; stopping a clock cannot synthesize receipt progress. Keep the full
synchronized demand and seven-edge ordinary drain guard. Verify final-return
source stopping and wake while preserving LF time, acquisition and permanent
Groundlark power supervision independently of a stalled Host dispatcher.
With workClock stopped, a native bank copy may finish while A, tail and receipt
ACK remain held. When the gate returns, completion-qualified A occurs once;
BD's native return continues to retain demand until synchronized copy-low.

Actual native buses require digital aperture checks through source, bank and
ControlCommand capture pins. Synchronous descriptor/epoch/busy context requires
independent pre-edge identity and post-edge destination checks; zero-delay
flip-flops do not prove physical hold time. Metastability, complete data paths,
reset recovery/removal, pin pulse/distribution, clock-gate handoff and supported
configuration limits remain physical item 17 obligations. Old P&R does not
qualify these controllers.

## Verification and state accounting

11a1's committed evidence remains under `build/async-host-frame-migration/`.
11a2a's digitally qualified evidence is under
`build/async-host-admission-payload-migration/`. Native `AsyncFrameStoreSpec`
checks service-clock-free capture, every source bit, repeated bank rotation,
identical payloads, original O/A ordinals, actual pins and POR phases.
`FrameAdmissionSpec` retains its original 14 cases and adds continuous reuse,
multiple completed reset episodes and queued-Host/MMIO priority cases for both
variants. Real I2C, Stored-edge, earliest-status, sleep/wake, firmware and core
reference assertions/deadlines remain required. Structural fingerprints only
attest the reviewed emitted graph; independent simulation/fault controls carry
the behavioral and digital aperture evidence.

R3 requires directed copies slower than two front periods, both relative offer/
completion orders, stopped-work-clock capture, repeated identical frames across
all four banks and both Click phases, delayed-copy reset/busy context, POR and
full Q plus same-edge D. Preserve the exact overflow fatal and independent source,
copy, A and D ordinals. Mutate the completion qualification, BD rearm input,
original-offer visibility and each context fact separately; unrelated failures
do not prove a control. The separate R3 results below supplement the historical
campaigns above.

The emitted comparison against `a0e2d1a` confirms unchanged 34-port public tops
and 516 fewer periodic-clocked bits per variant. The old 550-bit mailbox/count/
debt becomes ten descriptor/count bits, removing 540. Four five-bit head
receipts plus two tail and two busy-synchronizer bits add 24. Existing original
receipt and epoch state are outside that subtraction. Four native 337-bit banks
add 1,348 payload bits plus native controls; there is no claim of smaller total
storage, mapped area or power. All 34 new temporary clocked bits remain audit
candidates for 11a2b, 11b and 14. The independent 15-bit snapshot crossing remains.

R3 adds four periodic-clocked bits per variant beyond that implementation:
two copy-ACK synchronizers and two descriptor-context facts. It adds one native
completion C-element (three inputs BD, two Click), with no payload bank. Count
these controls in the matched mapper and state inventory. This correction keeps
the real clocked descriptor consumer; it does not remove its scheduler, establish
minimum clocked state or qualify physical capture/reset/fork timing.

The final R3 physical-r2 exports have completed matched mapping against C1;
see [incremental cost and constraint binding](gf180-matched-comparison.md#r3-incremental-frame-completion-comparison).
Logic area increases 0.04833% BD / 0.00423% Click. The exact preserved-native
increment is one C-element, 15/13 physical leaves, and all existing native payload
storage/guards remain unchanged. Both copy first stages remain timed; constraint
binding adds no false paths. Evidence is under `build/async-frame-completion-repair/`
in `mapped-cost-r2/receipt.json` and `constraints-binding-r2.json`. Fresh native-model
activity (`activity-r1-receipt.json`) measures unchanged clock-edge counts and
durations in all 27 maintenance/sampling/firmware windows per variant; it does not
measure loader transfer latency. The R3 final functional and fresh-review gates
pass; physical timing remains unqualified.

## R3 final verification

Evidence under `build/async-frame-completion-repair/` retains every failed attempt
and its diagnosis. `final-evidence-r1.json` records 262 distinct passing Scala
cases in 28 suites after affected reruns, 457 Python tests plus the final ten-case
integration-helper rerun, and all four portable/physical strict exports. This
includes both core/reference implementations, firmware, service/reset/sleep,
real-wire I2C and the 33 focused frame-admission/wake cases.

The final campaigns pass 312 capture controls (260 positive, 52 exact-site
negative), 20 wake controls (16 positive, four negative), 2,880 receipt mutations
and 3,868 actual RTL integration mutations. Extracted integration inputs are
immutable snapshots bound to their final export origins; inline inputs and all
mutants retain hash attestations. Independent review additionally exercised
seven completion/rearm/context mutants and checked emitted state, ABI, mapped
cost, measured activity and the campaign receipts under `review-r1/`.

Initial synthetic-delay tests failed because the override did not bind, then
because an injected 8 us delay exceeded the ordinary 2 us POR. Overrides now
resolve exactly one metadata owner/primitive; only those artificial-delay cases
use 20 us POR. Initial strict checks exposed missing retained aliases and
semantic-marker/emitted-alias binding assumptions, all corrected before the
final exports. Supplemental campaigns also exposed stimulus, exact co-fatal,
mutator-formatting and mutable-input attestation failures; original logs remain.

The first broad run passed 140 of 153 cases. Twelve I2C failures came from the old
structural assumption that receipt ready equals work-gate running immediately
after reset. The updated independent ready oracle also checks actual retained
copy phase; all functional wire/reset/overflow assertions and stimuli remain.
The remaining failure was a 240-second BD cold-boot host timeout. Independent
replay of the exact unchanged binary passed in 251.222 seconds, preserving all
original artifacts and the 1.2-second simulated deadline. Only this BD test's
host allowance changes to 600 seconds; its fresh Scala rerun passes. No functional
expectation or simulated deadline was relaxed.
