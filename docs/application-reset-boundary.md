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

1. A synchronous `close` suppresses transfers and native bus capture. Stored
   bridges retain payload; the C1e1 request receipt masks its output to zero.
   Request/acknowledgment and synchronizer history remain retained, and the
   native source stays intact until all actual receivers acknowledge closure.
2. `closed` acknowledges an actual receiving clock edge with capture disabled.
   Services similarly acknowledges an edge with application cancellation active.
3. On a later service edge, the coordinator can assert destructive native reset.
   It does not wait for accepted SRAM, loader or publication effects to drain.
4. With every receiver closed and native peers held reset, synchronous `rebase`
   clears only bridge protocol/history state. Any bridge payload storage remains
   held; the C1e1 request receipt has no payload copy and stays masked while closed.
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

## C1e1 retained CPU request receipt

Status: digitally verified; physical qualification remains open. C1e1 replaces
only each SoC's request ingress with its design-owned
`FourPhaseQuiescingReceipt` or `ClickQuiescingReceipt`. The four deleted payload
fields total 70 bits: mask 4, data 32, address 32 and operation 2. Native storage,
control history and all other receivers are outside this removal. The six
smaller grant/drain receivers retain ten payload bits under separate C1e2.

The source is the actual core address-stage native payload, through
transactions.serviceRequest: mask [3:0], data [35:4], address [67:36], operation
[69:68]. The receipt selects that bus only while state is 2, close is low and
local reset is released; otherwise every field is zero. This mask is necessary
because background Control commands can sample memory/peripheral fields outside
request.valid. Keep all transitive receiving pins in the structural and timing
scope, including those background consumers and the request-first synchronizer.

The two request synchronizers, settling edge, service-clock state/ACK update,
BD complete return, Click phase histories and POR-owned closure/rebase behavior
remain. Source ownership lasts through actual Services capture on gated
workClock. Ready must be zero when that capture edge is stopped; service-clock
ACK alone is not consumer acceptance. Preserve native retention until all real
receiver closure edges and coordinated native reset. POR is a separate abort
domain; raw watchdog reset cannot destroy the source before closure.

Digital evidence must bind actual source lanes, zero masks, coordinator reset
ordering and physical gate logic in fresh exports. Keep stopped-clock/POR/reset,
both-phase/full-return, source-reuse, background-use and exact-fault oracles.
Strict stimulus uses the catalogued native payload and real receipt state,
never a forced combinational receipt output. The failed production-r1 fixture
compile attempt and its narrow alias corrections remain historical evidence.
The executed manifest also remains immutable; any four-entry derived inventory
correction is separate metadata, not a replacement execution input.

The real-gate fixture stalls the first-stage gate-demand registers and checks an
otherwise-ready RAM store against the actual gate, consumer edge and four byte
effects, in BD and both Click phases. It does not establish natural sleep
reachability or all operation branches. Standalone receipt sends include return
spacing; they are not an earliest-possible generic source-reuse timing test.
Production retention is instead checked against the actual address Stage and
Fabric lifetime, together with composed execution.

The retained request proof binds the complete existing native address Stage and
Fabric controllers, not only the type and width of the payload register. It
checks all native primitive parameters and input equations, request/ACK aliases,
BD return histories or Click phase histories, coordinated reset aliases and all
70 source lanes. Maintained graph fingerprints reject unreviewed controller
changes. Production 2048/1024-byte and reset-fixture 64/32-byte capacities have
separately checked Fabric signatures; an unknown capacity fails closed.

The reset-crossing checker keeps the uncut graph for reset ownership and for
every clock, reset and fixed-macro input. Only periodic D traversal may hand off
at the B input of the four exact zero-when-invalid payload masks, after proving
the native hold lifetime, receipt controller, actual consumer clock qualification
and reset coordinator. The downstream route must be combinational until the
periodic D sink; an intervening native state capture needs a separate contract.
Every receiving register uses the positive service edge or its proved gated
work edge. Its reset is direct POR, an exact POR release chain, or the existing
resetless payload-storage shape; an unrelated clock or reset is rejected.
Mask selects, other cells and parallel bypasses remain
in the traversal. The report lists discharged data findings separately; neither
an entire source nor a destination register is exempted. This structural proof
does not qualify physical data settling, mask opening/removal or clock skew.

The first four strict runs failed with 1,452 data findings each. Those failed
reports and producer logs remain immutable. The checker-only repair uses
byte-identical copies of the original exported RTL and explicitly separates its
current source inventory from the original 508-test execution, compiled classes
and runtime. It does not relabel that regression as a new execution. Review
found and corrected fixture-capacity and proof-identity integration defects.
Root and independent review then found two false negatives in the first handoff
implementation: masked payload could reach a clock pin or an intermediate native
owner whose output reached periodic D. The r1 saved-graph/control acceptance is
superseded and retained as historical evidence. The r2 repair requires exact
destination, capture-clock and POR/resetless ownership checks, and rejects both
counterexamples without altering the RTL or functional oracles.

The next strict attempt passed the RDC audit, then both portable forms rejected
a stale assertion-layer name for the replaced request bridge. Root stopped the
two still-running physical probes and retained their partial output; those are
interrupted runs, not physical passes. The real-gate fixture audit also rejected
Yosys' equivalent negative-edge clock form and the existing two-edge local POR
release. Narrow checker repairs preserve the actual falling edge, exact POR
chain, assertion predicates, bind targets and executable assertion wrappers.
Their source changes are confined to the relevant structural proofs; functional
fixture generation and mutation logic remain unchanged. The failed and stopped
runs remain under `build/async-quiescing-receipt-strict-preparation-r3/strict-r1/`
and `build/async-quiescing-receipt-gate-graphs-r2/`.

The fresh receipt controls pass 11 positive replays and 151 exact faults,
including all three actual gate fixtures. The historical 132 handoff fault
executions remain separately bound to all four fresh graphs by exact graph
equality after a recorded export-root rename in source attributes and generated
identifier keys only. No connection, bit ID, parameter, source position or other
attribute is changed, and these are not relabelled as new fault executions.
All four fresh strict exports now pass their four mandatory campaigns: BD
portable/physical perform 657,242,250 / 657,452,250 checks, and Click performs
568,118,844 / 568,307,964. Held-bus controls pass four structural campaigns
(520 faults) and four positive compiled wiring replays with 48 exact faults.
The graph-control replay initially rejected six Python tuple/JSON list alias
pairs before executing any negative controls. Its preserved failure is a report
serialization mismatch, not an RTL failure. The comparison-only repair retains
all report fields and the original 304 mutation oracles. The serial replay was
stopped after 31 records to run the four independent export cohorts in parallel;
its partial output is preserved. That complete replay passes four baselines and
all 304 exact faults. Worker logic is unchanged. The late maintained comparison
repair is recorded separately from the frozen execution inputs. Cost and wake
activity and bounded receiving-aperture results are complete. The bounded
screen records timing violations; physical timing and reset-distribution
qualification remain open.

| Required C1e1 evidence | Result / remaining work |
| --- | --- |
| Distinct Scala tests/suites and repeated activity executions | 508 tests across 33 suites pass (144 primary, 360 affected and 4 physical-policy tests), followed by two fresh PhysicalEstimateSpec activity executions. |
| Python controls | The frozen 436-file checker inventory passes 703 tests. The final comparison-only repair adds two regression tests; acceptance requires its separately bound 705-test full replay. Original functional RTL/classes are unchanged. |
| Four fresh exports, strict campaigns and exact receipt/gate/graph controls | Four strict exports pass all mandatory campaigns; receipt controls pass 11 positives + 151 faults and three gate fixtures. Held controls pass 520 structural faults and four positives + 48 compiled faults. Graph controls pass four baselines + 304 exact faults. |
| Complete periodic/native state and actual mapped storage pins | 70 fewer periodic bits per variant: portable 5,797 BD / 5,798 Click, physical 5,807 / 5,808. Native register/latch storage remains 11,454 / 11,607 bits; the independent SDA event bit remains one. Four payload objects disappear; all nine control/reset bits (eight register objects) remain. |
| Whole mapped area, all five leakage envelopes and clock-pin loads | Logic excluding SRAM: 2.862584704 mm² BD / 3.629653440 mm² Click (-0.2404% / -0.2999%). All five listed-state leakage envelopes decrease. Service storage clock-pin load falls 0.234220 pF each; other domain loads are unchanged. See [GF180 estimates](gf180-estimates.md). |
| All 27 ordinal wake windows per variant, exact workload and observers | All 27 windows per variant are identical in kind, phase, duration, fast/work edges, retired instructions and ADC count. Each firmware wake retires 43 instructions with 3,255 BD / 3,160 Click work edges (271,607.839 / 263,691.109 ns). This is activity, not wake energy. |
| Bounded receiving-aperture measurements, failures and missing bounds | 20 bounded cases record all 4,860 group extrema, with 787 negative setup extrema and violations in every case. All selected hold/recovery/removal minima are positive under ideal-clock assumptions; complete native, reset, electrical/pulse and routed qualification stays open. See the detailed screen below. |
| Final source/evidence binding and independent review | Source, exact-control, matched-measurement and timing reviews are separately recorded. Final acceptance binds the unchanged executed RTL/classes, seven documentation updates and the two-file comparison-only checker repair in `build/async-quiescing-receipt-final-r1/final-evidence.json`, after the final Python and source/evidence review. No previous execution is relabelled. |

Root-owned digital evidence is retained under
`build/async-quiescing-receipt-production-r2/`, strict evidence under
`build/async-quiescing-receipt-strict-preparation-r4/strict-r1/`, and matched
measurement under `build/async-quiescing-receipt-measurement-r3/`. Its baseline is
the accepted C1f candidate maps. The independently reviewed mapped inventory
and generated plan bind the execution under
`build/async-quiescing-receipt-grouped-aperture-run-r1/`. The original sealed
harness preparation remains separate from those completed results.

### Bounded receiving-aperture screen

The twenty cases cover baseline/candidate × BD/Click × all five pinned corners.
There are 274 baseline and 212 candidate min/max queries per corner. Every query
records a selected path; this does not mean every possible endpoint path was
checked. Group minima/maxima compete across both data transitions. Actual mapped
launch/capture pins, clock edges and Liberty check types are retained in each
record. Only existing native keeper feedback arcs are cut for analysis; no
native clock, false path or multicycle waiver is invented.

| Corner | BD worst setup, before → after (ns) | Click worst setup, before → after (ns) | Candidate minimum hold, BD / Click (ns) |
| --- | ---: | ---: | ---: |
| TT25 | -47.35632 → -47.51893 | -47.12824 → -45.00468 | 0.77807 / 0.82404 |
| SS−40 | -80.24592 → -80.54436 | -81.33476 → -78.58835 | 1.31183 / 1.37205 |
| SS125 | -137.07308 → -137.41502 | -136.76926 → -132.38118 | 2.07854 / 2.16390 |
| FF−40 | -8.55492 → -8.64879 | -8.59441 → -7.31172 | 0.23061 / 0.25888 |
| FF125 | -33.09709 → -33.23222 | -30.99081 → -29.30357 | 0.53408 / 0.57442 |

These are extrema of each design's own groups, **not matched physical-endpoint
deltas**. Synthesis changes physical names, paths and group membership. The old
payload-Q groups disappear because the source becomes native; their removal is
not a timing improvement or an empty pass. BD's worst selected setup becomes
slightly worse at every corner. Click's worst setup extremum improves, while its
hold minimum decreases slightly. All remain conditional component estimates.

There are **787 negative setup extrema across 20 cases**. Selected hold,
recovery and removal extrema are positive; the candidate's smallest selected
removal margin is only **0.14251 ns BD / 0.20541 ns Click** at FF−40. Ideal clock
and reset assumptions do not establish real reset distribution, recovery/removal
or mask-release safety. The existing C1f SRAM-controller failures remain open
as well; this CPU-receipt screen does not replace that larger timing scope.

The result explicitly leaves **262,500 endpoint/family/mode relations** unproved
across these runs. Candidate inventories also retain **73 BD / 80 Click** native
or otherwise unqualified groups. Electrical and pulse checks are unmeasured;
the complete inventories exceed the bounded electrical sweep ceilings. No larger
sweep or retry was substituted. Native source settling, mask opening/removal,
source reuse, actual gated-clock skew, reset distribution and routed RC therefore
remain separate physical obligations. `coverage_complete` stays false and
physical qualification stays OPEN.

Acceptance changes state and can remove the mask immediately after capture.
Measure the full minimum service CLK-to-Q/valid/mask-zero path against actual
consumer hold, plus latest native data and valid opening, lawful BD/Click source
reuse, close/rebase/POR and gate restart. Retain actual launch/capture edges,
all branch loads, signed failures and missing checks. Native Q-to-D segments
omit the native launch/capture envelope; ideal clocks omit routed skew/RC.
Neither digital cadence nor fewer bits establishes physical qualification or
energy savings. Native aperture, reset/clock distribution and routed timing
remain OPEN; C1e and minimum boundary state are not complete.

## Reset intervals (R2a digitally verified)

The raw pulse qualifier still requires eight ungated service edges. It observes
short pulses and wakes a stopped source; its 350 ns conservative minimum is not
the native reset hold. The coordinator separately requires 64 continuous service
edges after observed reset is low and all receivers acknowledge rebase. It then
removes native application reset while retaining cutoff and core reset for another
64 service edges. Reopening additionally requires every rebase acknowledgment
to withdraw. The counter saturates while withdrawal is missing, and a new reset
restarts closure. Stopped service clocks cannot advance either interval.

At the supported 20 MHz ceiling, each interval is conservatively at least
`(64-1)/20 MHz = 3.15 us`. This exceeds twice the rounded 1.55 us worst measured
local guard reset propagation. The reused counter grows from three to six bits,
adding three periodic bits per variant. The eight-bit raw qualifier is unchanged.

The 250 ns limit on custom digital timing parameters remains a compatibility
check, now named `digitalDelayLimitFs`; it is not a physical settlement bound.
V3 physical policy records distinguish these quantities and remain unqualified.
Local guard measurements exclude upstream logic, reset distribution and wiring.
The later core-reset removal/startup path also needs its own full envelope.
These longer intervals repair the known numerical mismatch but do not close
complete physical reset recovery/removal or controller timing (R2b/item 17a3).
R2a passes the affected regressions, independent actual-RTL mutation review and
all four strict exports. The exact sources, probes, binaries, logs and retained
failures are bound in `build/async-reset-hold-migration/qualification-evidence.json`.

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

### Verification-only observers (C1c)

`ramResetDebt` and `programResetDebt` are raw-reset history observers used only
by the RAM/program test fixtures. The raw native telemetry/housekeeping return
fence expressions likewise live in PublicationSource fixtures and are inherited
by RecoveryOwnership fixtures. None belong in the production Platform.
Production cancellation uses the unchanged POR-owned service debt and publication
boundary state. Moving these observers removes no implemented storage or clocks.

The four affected suites pass 52 tests; all 468 Python tests pass. Six positive
replays and six exact-fatal mutations preserve the relocated diagnostics. The
RAM early-release mutation initially survived: the historical 12-edge window
ended while the new 64+64-edge recovery still held the observer in reset. Keeping
the same held-publication assertions active for 200 edges closes that test gap;
all 11 RAM tests pass again. These controls verify diagnostic sensitivity, not
additional production reset-fault coverage.

Evidence is `build/async-platform-diagnostic-cleanup/`: `regression-exports-r3.log`,
`ram-regression-r4.log`, `python-r1.log`, `observer-controls-r2/receipt.json` and
`export-identity.json`. Fresh portable/physical exports for both variants retain
the same executable inputs under default, `SYNTHESIS` and the recorded strict
compile flags. Every contract field matches except the derived top RTL hash and
aggregate hash: FIRRTL renumbers simulation-only random initialization slices
when unused source registers disappear. Comparison preserves strings, validates
the historical probe/binary/log attestations and includes verification auxiliaries
and chip wrappers. `RANDOMIZE_REG_INIT` is disabled in this scoped equivalence;
the previous strict PASS is reused, not relabeled as a new execution. Compiled
periodic totals remain 6,000/6,001 portable and 6,010/6,011 enabled-policy physical.
No new area, energy or physical timing qualification is claimed.

### Production boundary coverage

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
eight-edge/250 ns physical interpretation is superseded by R2's separate
intervals above; complete physical qualification remains open.
