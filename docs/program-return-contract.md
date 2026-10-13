# Program/loader native return contract

Status: item 10b2d2 is digitally verified, 2026-10-12. Physical qualification
remains open. Evidence, fresh independent reviews and actual failed attempts
are retained in `build/async-program-return-migration/qualification-evidence.json`
and its sibling logs. See [the qualification record](build-and-test.md).

## Native ownership and retained role

Each design owns separate ProgramAccess, ProgramCaptureReceipt and ProgramReturn
files. They share port schemas with working RAM, not implementation logic. Native
SRAM sends its retained 32-bit word directly to ProgramReturn. ProgramReturn
publishes directly to ProgramSource and presents CPU data directly to
Completion.memory. The old word-reply, publication and Completion-memory clocked
crossings are removed. Completion retains separate program and working-RAM inputs
and the existing immutable four-source plan. Click uses native phase channels.

ProgramSource retains an immutable CPU-read/loader-write tag for each reservation.
Its `eligible` output alone is insufficient: loader reservations also set it.
`cpuPresentationPermit` requires an owned reservation, a CPU role and live
eligibility; Click additionally requires the captured arm identity to match the
reservation phase. The word owner snapshots this permission with the word.
Neither projected loader state, the next offered request nor later permission
changes can reclassify a captured word. A loader word must never offer an
application response, even outside application reset and at either Click phase.

POR owns accepted SRAM effects, retained word data, input/publication/capture
transport and receive/issue/completion history. Qualified application reset owns
captured CPU permission, application response phase and Click's saved application
target. Under the [R1 digital-containment correction](application-reset-boundary.md), ProgramReturn
and Completion share the coordinated native reset, after their clocked receivers
acknowledge closure. The raw qualifier alone no longer identifies the lifetime
of the response phase. The inherited reset-duration assumptions remain open in R2.
Application reset cancels CPU presentation but cannot cancel loader publication,
Stored delivery, accepted byte writes or Control accounting. A word captured
while reset is held cannot become eligible upon release.

BD access admission synchronizes the complete word request-low/ACK-low predicate;
raw native ACK must not enter the POR access owner's readiness cone. Click
already synchronizes complete phase equality. The response monitor uses the
actual presentation-reset pin and permits only its reinitialization to zero;
all other loader-time response phase changes remain fatal.

## Independent returns and Stored accounting

Native capture acknowledges the SRAM word and retains its data before three
independent branches return: ProgramSource publication, the temporary clocked
capture receipt and application presentation. Publication carries the retained
word's actual bit zero. Loader words complete the presentation branch without a
CPU token, preserving an independent application phase history.

The capture receipt is control-only: two request synchronizers, one ACK phase
and two POR-release bits. Its ACK means ProgramAccess.active cleared on that same
work-clock edge. Acceptance depends only on active and a pending request; it must
not wait for publication, Stored, reset debt, source idle or return-owner idle.

`effectsDrained` joins inactive access, original command/word/byte returns and
capture-receipt idle. ProgramSource.wordDrained additionally requires retained
application presentation settlement. It excludes publication, Stored and native
return-owner occupancy, and never waits for source reservation, grant or decision
occupancy. Full busy/admission/sleep drainage additionally includes
synchronized return-owner idle. A reservation cannot block its own word commit.
The source and return owners jointly retain publication and Stored lifetime;
removing the old bridge does not remove either obligation.

Stored selection requires the retained loader role, a committed decision and an
actual word publication. Stored ACK still means its Control command fired.
Stored command and reply must progress while capture receipt remains stalled and
full ProgramAccess busy is asserted, provided the work clock runs. Native Control
retains loaderPending until Stored acceptance, increments received exactly once
and commits the pending CRC. Clocked admission-time busy/reset context and status
projection retain the command-to-reply gap. Early native return cannot authorize
WRITE or VERIFY before that Control publication.

BD retains input withdrawal and every branch's complete request/ACK return.
Stored full return gates reservation ACK falling. Click retains independent POR
word/publication and Stored histories, separate from application response phase.
Every captured word has an unconditional issue event before cancellation can
count as terminal proof. The next word cannot overwrite data during any old
selected return.

## Timing and remaining synchronous state

Native return uses the working-RAM controller's reviewed digital assumptions:
10 ns data paths, 1–10 ns control cells, 100 ps capture aperture/pulse/distribution
limits and 200 ns cleanup guards. Tests bound stalled-receiver offers to 800 ns
and cleanup after all external returns to 1 microsecond. These are simulation
bounds, not characterized physical cells or routed paths. The new retained-role
cone and composed source-to-return permission aperture require their own closure.

The retained source role precedes its guarded grant, clocked atomic word commit,
command crossing and all four SRAM byte stages. Source retirement requires the
post-capture effects and presentation proof. This ordering keeps role/ownership
stable through word capture without deriving permission from the live requester.
The digital composed campaign checks the actual permission/data/trigger pins
against independent CPU/loader identity, with opposing 1–10 ns source/return
control delays. It preserves the fixed source/return guards and data budgets.
POR capture checks remain active during application reset; each application
register's own reset governs only its capture exemption. These checks cover the
20 MHz, 16-byte test fixtures, not every supported configuration or physical path.

Fresh Groundlark low-power portable-SoC emission, compared with commit `60c5590`,
removes 87 clocked RTL bits in the three old crossings and adds five capture-receipt
bits plus two owner-idle synchronizers: **80 fewer clocked RTL bits per variant**.
Nonprimitive totals fall from 8,685 to 8,605 bits for BD and 8,686 to 8,606 for
Click across 66 owners; each includes one unchanged asynchronous SDA capture bit.
All 34 public port schemas and emitted declarations are identical. Native
primitive storage and fixed macro arrays are excluded. This inventory pass is
not an area estimate, minimum-state proof, whole-chip audit, configuration-complete
count. The five-bit Stored receipt, clocked admission,
status projection, source crossings/debt and physical SRAM byte boundary remain
candidates for later checklist items. Independent watchdog/time and permanent
Groundlark supervision remain required.

## Qualification gates

Preserve every existing AsyncProgramSourceSpec, ProgramSourceSpec, StoredReceiptSpec,
SramSpec and firmware/serial-loader oracle. Add native-return capture/reset/stall
cases, retained permission, loader/CPU phase alternation without reset, actual
native CPU-offer suppression, bounded Stored progress under held capture,
stopped work-clock/reset recovery and exact macro-CLK write/received/CRC counts.
Exercise both banks and capacities, BEGIN revalidation and cancelled CPU slots.

Close actual primitive/data/reset pins, complete role equations, capture receipt
and access logic, native response packing and literal error aliases before any
impossible-polarity mask. Both program and RAM error bits in Completion's packed
result require independently proven constant obligations. Keep all dynamic
activity checks, original probe campaigns and full composed check counts.

Require actual-pin skew/reset capture controls, actual RTL fault campaigns and
fresh strict exports. Production mutations must compile and hit their exact
intended fatal assertion in the attested positive probe; unrelated errors,
timeouts, missing activity and displayed text do not count. Finish ABI/state
comparison, both independent core references, Python, firmware/sleep regressions,
fresh independent review, fixes, documentation, commit and push before closure.
Old P&R results do not qualify this implementation.
