# Application reset boundary

R1 is digitally verified: production reset tests, affected regressions, structural
controls, all four strict export forms and fresh independent review pass. The
boundary retains native request payloads until their clocked receivers close.
This establishes the documented digital containment scope; R2's physical reset
envelope and complete CDC/timing qualification remain separate gates.

The final source/probe/binary/log bindings and original failures are preserved in
`build/async-reset-domain-migration/qualification-evidence.json`. See
[build and test](build-and-test.md#application-reset-boundary-r1) for the cohort,
review fixes and remaining limits.

## Acceptance and reset ownership

`systemReset` remains the immediate, retriggerable qualified watchdog indication.
It isolates application GPIO and retirement visibility and records native
recovery debt. Permanent board GPIO ownership, sensing, time, image validity,
programming lock and accepted effects remain POR-owned.

The service-domain two-flop observation requests a coherent application cutoff.
The old native core, fabric and presentation path remain intact until their
clocked receivers acknowledge closure. Any actual `request.fire` before cutoff
is accepted old-lifetime work; its persistent effects must finish exactly once.
Copying a request, holding a grant or asserting raw reset is not an acceptance.
No CPU acceptance or unaccepted HALT/application Telemetry dispatch is permitted
at or after cutoff. Already accepted MMIO staging and ordered Housekeeping work
retain their independent ownership.

This deliberately changes internal reset sequencing. Raw assertion no longer
destroys the native producer before its clocked consumer can stop sampling.
There is no claim of a physically instantaneous arbitration between watchdog
assertion and an otherwise simultaneous service-clock acceptance.

## Close, reset and restart

Each design owns its coordinator and native-protocol clocked bridges. The five
production crossings are request ingress, Admission grant, Completion plan,
Completion Telemetry and Completion Housekeeping. Clocked response fixtures use
the same boundary at their extra response consumer. Click retains two-phase
request/acknowledgment histories; no four-phase conversion is introduced.

1. A synchronous `close` suppresses transfers and native bus capture. The bridge
   retains payload, request/acknowledgment and synchronizer history.
2. `closed` acknowledges an actual receiving clock edge with capture disabled.
   Services similarly acknowledges an edge with application cancellation active.
3. On a later service edge, the coordinator can assert destructive native reset.
   It does not wait for accepted SRAM, loader or publication effects to drain.
4. With every receiver closed and native peers held reset, synchronous `rebase`
   clears only bridge protocol/history state. Payload storage remains held.
   `rebased` proves that the bridge took that edge; it does **not** prove that
   asynchronous physical reset propagation has settled.
5. Native reset releases after all rebase acknowledgments and the configured
   continuous hold. Reopening waits for actual withdrawal acknowledgments in
   every receiving domain. Core reset stays asserted until reopening completes,
   so clockless boot retirements cannot disappear behind output isolation.

A new observed reset restarts this sequence without opening the boundary. POR
starts closed and can immediately abort all work. With a stopped receiver clock,
closure/rebase cannot be invented. The coordinator holds the work gate and
service source running through restart; deliberate fixture clock stalls retain
the old producer until those clocks actually resume.

If the reset observer rises on the same edge that the coordinator releases the
core, the synchronized cutoff still closes service admission. That edge can
start an internal generation which the new reset then aborts; immediate output
isolation keeps it invisible. It must create no accepted request or memory
effect. Closure/rebase repeats, and only the final fresh generation becomes
visible. Keeping the core held prevents ordinary startup trace loss; it does
not promise that a new watchdog episode cannot abort an internal restart.

Application projections now have POR reset and highest-priority synchronous
cancellation. Immediate GPIO isolation is an output-only branch. The diagnostic
`pending` view used by verification follows that isolation; it is not a hardware
ABI output. Control MMIO reads, WAIT decisions and host snapshot capture use the
internal clocked views, never a raw-isolated value. A snapshot already accepted
before synchronized cancellation retains its own coherent lifetime. Tests retain
the immediate diagnostic/GPIO assertion and separately check unchanged internal
event data between clock edges, cancellation of retained state, and real host
and MMIO event reads after recovery. The diagnostic mask alone proves no ABI
event-clearing behavior.

## Recovery observation

Publication source eligibility and presentation reset follow the delayed native
reset. A separate native debt reset asserts on raw watchdog qualification and
stays asserted continuously through coordinated closure/reset/restart. Native
reservation, proof and effect phases retain POR ownership. Standalone source
tests retain their original single-reset interface; the production split is
explicit in its constructor and metadata.

Each clocked publication client retains one reservation's role, revocation and
recovery episode. A late old grant is cancelled rather than reclassified. One
fresh recovery may be issued and committed per episode. Native debt remains
authoritative: a two-flop observation of complete native debt/return cleanup,
after an observed dirty interval and that episode's committed recovery, permits
the service mirror to clear. The mirror never participates in the native final
receipt's quiet proof. Immutable native role and eligibility remain separately
checked at committed grants; they do not choose POR state updates.

RAM/program service debt is POR-owned and set at the coherent cutoff. The old
raw-pulse ledgers remain independently observable in fixtures; they no longer
control service acceptance. Loader reservation and Stored accounting bypass CPU
recovery while retaining their existing native role/capture contracts.

The raw qualifier may finish while a receiver clock is deliberately stopped.
Consequently a later reset-caused Click response-phase change to zero must be
classified using that phase register's actual presentation-reset pin. Raw
`systemReset` is insufficient for this observation. No other phase change is
exempt from loader/no-unsolicited-response assertions.

## Verification and physical limits

Bridge tests cover native payload/phase retention, each capture/return state,
both Click parities, pause/resume, stopped receiving clocks, illegal early
rebase and reset retriggering. Production tests must additionally cover the
actual Core/Fabric/Services path, retained source data, accepted SRAM effects,
fresh locked-image restart and early boot retirement at slow service clocks.
Original acceptance/effect oracles and failure logs are retained.

The deeper graph traversal also exposed a BD word-return crossing: admission
previously combined synchronized request-low with raw native ACK-low. Both
program and working-RAM access now synchronize the complete return-to-zero
predicate. Byte-request ACKs remain local clocked bridge outputs. Click already
synchronizes its complete request/ACK equality predicate.

The structural export audit must traverse elaborated bit connections to POR
data, enable, clock and reset sinks. Synchronizer exceptions require exact
two-flop topology with exclusive first-stage fanout. Held-bus exceptions are
specific source/sink contracts, never blanket module exclusions. Mutation
controls must restore raw resets, bypass synchronizers and inject raw/native
levels into acceptance to prove rejection.

Coordinator verification separately proves the actual six-way closure join,
five-way rebase/withdrawal joins, receiving flip-flop D/clock/reset pins and all
coordinator next-state equations. It cannot replace the composed tests with a
stopped receiver clock and accepted effects in flight. The independent review
found that the first audit treated close/rebase as unconstrained inputs; the
added proof and actual omitted-ACK/OR-join mutations close that digital gap.

These are additional clocked boundary registers, not asynchronous state removal.
Count them in the residual-state and area/leakage ledgers. Digital tests cannot
qualify synchronizer MTBF, related service/work setup/hold, the last capture to
destructive-reset margin, reset recovery/removal, or the complete physical
controller/reset envelope. `close` is a timed synchronous predicate, not an
unconditionally glitch-free asynchronous isolation primitive. The inherited
eight-edge/250 ns assumptions remain unqualified until R2 is resolved.
