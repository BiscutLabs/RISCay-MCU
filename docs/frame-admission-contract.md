# Native I2C frame delivery and admission

Item 11a1's payload-free original receipt is digitally verified and committed.
Item 11a2a moves accepted payload/epoch retention into separate native BD and
Click banks. Digital qualification and independent review pass. Narrow logical
credits, descriptor ordering and dispatch remain
clocked for 11a2b/11b/14. No physical timing or minimum-state claim follows.

## Events, retention and acceptance

O is the original native I2C publisher's completed-frame offer. A is its original
receipt's accepting service/work-clock edge. D is the actual selected Host
`ControlCommand.fire`. These are distinct events; native copy completion is
neither A nor D. All three retain independent testbench ordinals.

`FourPhaseFrameReceipt` and `ClickFrameReceipt` retain five POR-owned clocked
bits each: two request synchronizers, acknowledgment and two local reset-release
stages. They transport the publisher's held 337-bit frame without another
payload register. Their ready requires local POR release and the actual work
clock's running state. A acknowledges that original publisher and captures one
narrow descriptor on the same edge. The original receipt remains on the ungated
front service clock; the falling-edge retained gate still controls work edges.

Original O, ready and publisher ACK do not depend on bank availability or copy
ACK. Full logical occupancy does not conceal O or delay A: a third accepted,
undispatched frame still trips `CONTROL_HOST_MAILBOX_OVERFLOW`, even with D on
that same edge. When D occurs one edge earlier, A must succeed. Keep Q=A-D,
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

Copy ACK is checked at A together with exact 337-bit identity, but does not
control A. These assertions alone cannot distinguish an old equal payload.
Qualification therefore also checks actual O-time complete availability, capture
ordinals, identical consecutive frames, all four bank wraps and unavailable-bank
faults while keeping original O visible.

## Context and head dispatch

Two four-bit descriptors retain bank ID and A-time reset/busy context. A two-bit
clocked Q retains the exact original capacity/overflow decision. With Q=0, A
writes the first descriptor. With Q=1 and no D it writes the second. A+D at Q=1
replaces the first after its old command capture; Q=2 plus A faults regardless
of D. Both descriptors, Q and tail are POR-owned.

At A, reset context joins the sampled flag, current reset, source/current epoch
mismatch and Services' synchronized application reset. Busy context joins sampled
busy, physical program activity, pending loader effects/control work and an older
Host loader command dispatched on that same edge. Later idle observations cannot
erase this history; Stored command/reply-edge tests retain their old assertions.

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
It is not permissible to extend that aperture by waiting for the copy.

BD's route data path has a complete 10 ns budget and an 11 ns request delay.
Route capture Q is bounded by O+21 ns and decoded selection by O+31 ns. A 32 ns
request guard precedes a preserved atomic AND (1..10 ns), followed by the native
bank's request/capture/ACK path. The resulting copy-ACK bound is:

    32 + 10 + 11 + 10 + 10 + 10 = 83 ns from O.

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

For the fixed ring, let S(T) bound earliest next O after A and P(T) the minimum
A spacing, conservatively inherited from the original publisher/receipt:

    S_BD = (ceil(111/T)+2)*T + 115 ns
    P_BD = (ceil(111/T)+ceil(115/T)+4)*T
    S_Click = 114 ns
    P_Click = (ceil(114/T)+2)*T

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

The logical D-to-next-A decision remains at most one 50 ns service period.
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

The emitted comparison against `a0e2d1a` confirms unchanged 34-port public tops
and 516 fewer periodic-clocked bits per variant. The old 550-bit mailbox/count/
debt becomes ten descriptor/count bits, removing 540. Four five-bit head
receipts plus two tail and two busy-synchronizer bits add 24. Existing original
receipt and epoch state are outside that subtraction. Four native 337-bit banks
add 1,348 payload bits plus native controls; there is no claim of smaller total
storage, mapped area or power. All 34 new temporary clocked bits remain audit
candidates for 11a2b, 11b and 14. The independent 15-bit snapshot crossing remains.
