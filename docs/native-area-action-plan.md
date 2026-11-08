# Native area: concrete redesign plan

Status: **BD batches 1–4 implemented and verified locally**. The user selected BD first; Click
keeps its current independent implementation during these batches. Source
baseline: `1f256eb`; approved-plan commit: `30dc3f2`.
Batch 1's [word loop](native-sram-word-loop.md) is implemented, independently
reviewed and verified locally: flat mapped logic is **1.718196 mm²**, down
0.175504 mm². [Evidence and limits](reviews/bd-sram-word-loop.md) include its
longer firmware wake. Batch 2 removes the Telemetry/Housekeeping reservation
detours: [publication slots](publication-slot.md) bring the flat map to
**1.591292 mm²**, below the 1.60 mm² stretch target. Its [review](reviews/bd-publication-slot.md)
retains an open, pre-existing ordinary Housekeeping qualifier timing failure.
Batch 3 replaces Control transport and speculative CRC with a
[closed bank](native-control-bank.md): **1.531099 mm²** flat mapped logic,
323 Control payload bits, with [independent review and local timing](reviews/bd-control-bank.md).
Batch 4a [Telemetry effects](native-telemetry-effects.md) is also implemented
and [reviewed](reviews/bd-telemetry-effects.md): **1.519368 mm²** flat logic,
259 Telemetry payload bits. Batch 4b [Housekeeping effects](native-housekeeping-effects.md)
reduces its payload storage to 449 bits: **1.506013 mm² flat**, **1.749243 mm²
hierarchical repaired**. The four batches remove 3,449 native bits and 247 flat
periodic sinks. The 1.60 mm² target is met; firmware work edges are 27.67% above
the original baseline, chiefly from full-return byte sequencing. Local timing,
remaining qualifier failures and the final verification are recorded in its
[review](reviews/bd-housekeeping-effects.md) and the [ledger](area-ledger.md).
This replaces the opportunity ranking in the
[overhead investigation](native-overhead-investigation.md), not its measurements.
The plan is based on the actual owners, their commit/return dependencies and the
existing matched netlists. A fresh independent review is recorded
[separately](reviews/native-area-action-plan.md).

## Diagnosis and acceptance budget

The matched flat maps contain **1.893700 mm² BD versus 0.531833 mm² clocked
logic**, excluding the same SRAM macros. This is 3.56 times the mapped logic,
not a measured 3.56-times die requirement or a timing-matched implementation.
Of the 1.361867 mm² difference, storage is 0.510617, DLYD is 0.394455,
buffers/inverters are 0.177535 and other logic is 0.279260 mm². Ordinary BD
logic already receives flat synthesis; retaining ordinary hierarchy costs
0.077763 mm² in the matched experiment. Hierarchy is not the main problem.

The decisive costs are repeated transaction storage and controllers around
single outstanding operations. The plan deletes those structures before sizing
their delays. It does not start with the 715 candidate dead/constant bits:
that entire storage pool is only 0.034636 mm², and much disappears in the
larger replacements below.

| Batch, in execution order | Existing BD native storage / protected recipe area | Replacement and engineering budget |
| --- | ---: | --- |
| 1. SRAM word loops | 1,079 bits per memory; 0.209185 mm² combined | One request, assembly and byte path per memory; at most 128 native latch/FF bits each at reference capacity; combined recipes at most 0.080 mm² |
| 2. Telemetry/HK reservation round trips | Two PublicationSource owners; 0.117127 mm² combined | Delete both owners and their auxiliary crossings; retain existing receiving-edge arbitration and actual native command/reply path |
| 3. Control bank and committed CRC | 1,302 bits; 0.085314 mm² | 252-bit architectural bank plus 71-bit result; at most 352 native latch/FF bits including control; recipes at most 0.050 mm² |
| 4. Telemetry/HK result copies | 515 / 676 bits; 0.100338 mm² combined | Keep banks and held commands, store only effects; at most 272 / 464 bits; recipes at most 0.080 mm² combined |

These are **design budgets, not mapped predictions or timing results**. Counts
and caps refer to BD's reference production profile. Click stays unchanged in
this BD-first pass; any later equivalent conversion needs its own inventory. Other capacities/software-sample
configurations need formulas and their own generated inventories. C-element
keeper state is accounted in recipe area, not in these latch/FF bit totals.
Price each replacement using its actual cell type: a closed EventRegister bank
uses reset flip-flops, which cost more per bit than the current pipeline latches.

The integrated stretch acceptance target for batches 1–4 is **BD flat mapped logic at
or below 1.60 mm²**, with fewer than the current 3,069 periodic sinks, no added
clocked payload mirror and no regression of existing wake/deadline bounds.
The recipe budgets remove approximately 0.302 mm² gross before replacement
boundary control and changes in ordinary mux/arithmetic logic; therefore the
whole-chip measurement, not their sum, decides acceptance. If a batch misses
its budget, identify the new cells/cones and revise that design before proceeding.

Even 1.60 mm² is about three times the synchronous map. It is an intermediate
gate, not a claim that the design is optimized. The framed host interface and
remaining arithmetic/CPU transport need the second phase below. No smaller
die is promised until a routed implementation passes the physical gates.

## 1. Replace the unrolled SRAM word pipeline

Files: each variant's `*Sram.scala`, `*ProgramAccess.scala`, `*RamAccess.scala`
and `SramBank.scala`, plus the corresponding internal port schemas/fixtures.
Keep the fixed GF180 macro model and the independent clocked design unchanged.

**What is redundant.** One execution credit permits one word, yet each memory
has a 69-bit input request, four 101-bit retained work operands, four 101-bit
capture results, four 42-bit issue stores and four 8-bit response stores, plus
credit storage. The four byte lanes also have separate receipt/reply crossings
into the same macro controller. They provide no four-word concurrency.

**Implement this replacement:**

1. Validate the full CPU/loader address before narrowing. Capture one immutable
   word request: word address, write flag, data and mask. At 2 KiB program /
   1 KiB RAM this is 46 / 45 bits. Retain full-width range checks at admission.
2. Keep one 32-bit read assembly bank and a two-bit lane counter. Form the byte
   address/data/enable from that request and lane. Use one reusable byte issue
   store, conservatively 21 / 20 bits, and at most one eight-bit response store.
3. Replace four request receipts and four reply senders with one pair per
   memory. Give the macro boundary one request/response port; remove its lane
   priority encoder and two-bit return tag. Preserve its falling-edge pin
   launch, rising-edge access and full-cycle Q capture.
4. Execute four byte completions, including disabled write lanes. Keep CEN
   inactive for disabled lanes. Do not combine masked-lane skipping or a
   request-derived macro clock with this change.
5. Capture a read byte into assembly before acknowledging its response. Do
   not advance/reuse the lane until both byte channels have fully returned:
   BD request and ACK low; Click phases acknowledged and capture rearmed.
6. Hold assembly until the SRAM-result-to-Return input channel has completed
   its handshake and return/rearm. Return retains its separate payload copy.
   Access may additionally wait for Return idle before admitting the next word,
   but `effectsDrained` must still exclude Return idle. Accepted accesses drain
   despite application cancellation; POR still aborts them.

**Keep the ProgramReturn/RamReturn payload banks and native eligibility.**
They separate macro drainage from publication. Borrowing assembly instead can
create a cycle: word ACK waits for Return release, Access waits for word return
to report `effectsDrained`, Source waits for that report to acknowledge
publication, and Return release waits for publication acknowledgement.
Deleting that buffer requires a different lifetime proof, not this batch.

**Acceptance:** extend the existing AsyncSram/Sram, source/return, firmware and
boot cases across all masks, backpressure on each byte phase, boundary addresses,
consecutive reads/writes, loader writes and repeated resets. Keep four-completion
semantics and exact read data. Test no CEN assertion while idle, one assembly
update per completed byte, no lane reuse before return, and no new word before
drain. Run full-capacity boot and the same 43-instruction workload. Fewer crossing
instances does not by itself promise four times fewer work edges: each byte still
uses the real macro clock. Measure the resulting edges and latency.

## 2. Delete the Telemetry/Housekeeping reservation detour

Files: both `*Platform.scala`, `*Services.scala`, `*PublicationBoundary.scala`,
`*PublicationSource.scala`, `*RecoveryReturn.scala` and their port schemas.
Delete a helper only after checking its remaining users.

**What is redundant.** Reserve, grant, decision, publication and drain messages
start/end in the same Services work-clock domain. The existing clocked
PublicationBoundary already owns the client's role, cancellation and recovery
generation. The two native Source owners duplicate that bookkeeping with
1,424 DLYD cells, including eight 200 ns guards. Their native recipe area is
0.117127 mm², before counting auxiliary bridges and clocked boundary mirrors.

**Implement this replacement:**

1. Keep the existing work-edge arbitration as the sole slot owner. Reserve the
   slot on the same edge as actual CPU/queued-command acceptance. Keep the
   actual command sender, native Telemetry/HK datapath and reply receipt.
2. Delete each subsystem's five auxiliary channel bridges, final return
   receipt, native PublicationSource/RecoveryReturn and obsolete clean/dirty
   synchronization. Replace PublicationBoundary's duplicate protocol with one
   POR-owned slot: active/issued, role, revoked, reply-seen and recovery-pending
   facts. POR starts with recovery pending and no accepted/reply history.
   Target no more control storage than the existing ten-flop boundary;
   count all added completion synchronization separately.
3. Use the sequence `ready -> accepted -> reply accepted -> fully returned ->
   ready`. Cancellation sets sticky revocation/recovery debt; it does not
   discard accepted work. Drain the old command, then issue a fresh
   ResetApplication command, accept its qualified reply, observe full return
   and only then reopen ordinary admission.
4. Require recorded command acceptance **and** reply acceptance before
   declaring completion. Two apparently idle endpoints are insufficient:
   the native transform can still be working between them. Reuse additionally
   requires command sender idle, reply receipt returned and bank-reader-ready.
   Click uses its own phase-completion conditions, not a four-phase wrapper.
5. Repeated cancellation revokes an in-flight recovery too. Clear recovery
   debt only after a fresh, non-revoked recovery has actually applied and
   returned, with no later cancellation. Do not use a wrapping generation to
   substitute for draining the single slot.

**Retain the existing accepted-effect payloads.** `mmioCommit`,
`telemetryCommitPending` and the ordered Housekeeping command are POR-owned
for a reason. A cancel may revoke application-bank application and CPU
completion, but accepted commands still execute/drain, including retained
software-sample effects. Keep borrowed operands immutable until sender return.
If cancellation precedes command issue, retain that accepted payload while
issue is inhibited; after cancellation releases, execute/drain it before fresh
recovery. A queued accepted command is not an empty slot.
Keep ordered HK data after reply acceptance until that return. Preserve
`consumedTimeAck` on the actual receiving edge.

No clock enters a native bank/controller. This removes a round trip around an
already documented clocked arbitration point. Raw watchdog reset remains in
pad isolation and the existing close/reset/rebase coordinator; only its
synchronized cancellation reaches the retained slot logic. Wake demand includes
every accepted, returning or recovering slot.

**Do not apply this deletion to ProgramSource/RamSource yet.** Their native
eligibility is captured asynchronously by Return, armed before memory commit
and revoked by coordinated native reset. Feeding that capture from a new
clocked `eligible` level would introduce a different crossing race. Keep it.

**Acceptance:** preserve PublicationSourceIntegrationSpec and
RecoveryOwnershipSpec outcomes/deadlines: staged reset, stalled publication,
held return, old reply versus a new CPU request, reset after recovery commit
but before return, prolonged reset and maintenance progress. Move fixture stalls
from deleted reserve/grant ports to the corresponding admission/command/reply
return point; do not delete the behavioral scenario. Both RDC proofs must
account for the new slot and show that raw reset cannot qualify its retained
loads. Leave native bank transforms/commit timing unchanged in this batch.

## 3. Collapse Control state transport and commit CRC on Stored

Files: both `*Control.scala`, `ControlSchema.scala`, CRC integration and
Platform's Control command wiring. The host protocol remains unchanged.

**What is redundant.** Control stores a 284-bit state/CRC token in its FIFO,
again in the Join, a 379-bit command operand, a 323-bit update result and a
32-bit speculative CRC result. There is only one serialized Control operation.
The sender already retains the command header, and the frame bank remains
retained until native command ACK.

**Implement this replacement:**

1. Keep one closed architectural ControlState bank (252 bits at reference
   capacity). Keep one result/effect bank (71 bits: kind, program write,
   period update/value, host wake and memory response). Use public native
   event/storage primitives with passive data allowances.
2. Borrow the held command/header/frame until both banks capture the accepted
   transition. Only then acknowledge input. Publish the closed state and held
   effects; remain busy until reply return before accepting another command.
   Keep Services' existing Control-state view in this batch so externally
   visible commit/read behavior does not change simultaneously.
3. Remove the state FIFO, state Join copy, command Join payload copy, full-state
   update payload store, speculative `pendingCrc` field and its CRC rendezvous.
4. On `Stored` with `loaderPending`, compute CRC over the held loader word from
   the architectural CRC and commit CRC/received/pending together. No CRC work
   is needed on unrelated selector, status, halt or timer commands.

The correctness invariant is specific: while `loaderPending`, programming
admission prevents another data/header operation from changing `loaderWord`
or `crc`. Other permitted commands leave both unchanged. `Stored` consumes that
pair; POR ends its lifetime. Application reset must retain accepted programming
effects. Assert this invariant and compare CRC/received after each committed
word against the existing oracle, including interleaved host/MMIO/halt/reset
commands and duplicate Stored. This is not permission to calculate CRC from
the incoming Stored command or to update it before memory has committed.

The new bank uses edge capture; do not substitute a transparent feedback latch.
Prove a single capture pulse, data setup/hold around feedback, publication after
the latest state/effect capture and full rearm. Size the new Stored CRC cone
from its own measurements. Existing Control timing does not qualify it.
Run Control/CRC/command-borrow/reset, lock, host loader and generic boot tests.

## 4. Remove full-state Telemetry/HK result copies

Files: both `*Telemetry.scala`, `*Housekeeping.scala`, reply schemas, Platform
receipts and Services consumers. Do this **after batch 2**, in separate commits
for the two owners. Identity/recovery and bank commit must not change together.

| Owner | Keep | Delete / replace |
| --- | --- | --- |
| Telemetry | 206-bit closed application/GPIO bank; held 48-bit command; optional software-sample banks | 259-bit full candidate-state reply -> held three-bit kind/recovery result plus native control |
| Housekeeping | 259-bit closed state bank; held 147-bit command | 268-bit full candidate-state reply -> nine held effect bits and 32-bit consumed-time value |

Compute the next bank input from the old closed bank and held command. Retain
the command through capture and full reply return. Keep the **same commit
event**: in BD, Telemetry application/GPIO captures on qualified `commitAck`,
its software samples on ordinary reply ACK, and Housekeeping on ordinary reply ACK.
Compute/hold reply effects from the pre-commit state before publication: due,
leaseExpired, startAdc and kick must not recompute when the state bank changes.

Keep the consumed-time reply value in the first implementation. Reading the
post-ACK bank on the ACK edge would return the old value and break LF progress
and wake accounting. Keep all existing reader inhibition/stable qualification,
same-edge old-value semantics, snapshot atomicity and GPIO closed-output rules.
Size feedback hold and bank-settle-to-reuse ordering for the new paths.

Click retains its own seeded phase state and bank-completion handshake.
Both reply-ACK phase changes launch the bank; a revoked Telemetry application
write recaptures the old registers while accepted software samples still commit.
Keep `applyBank` stable through that capture, then expose the completed bank
phase to existing reader qualification. Remove Click's redundant state operand
copy as part of the fold, without replacing phase completion with an ACK level
or borrowing BD's bit totals as a Click measurement.

Acceptance includes concurrent snapshots/MMIO and writes, both GPIO-retention
settings, SPI recovery release, pin-transition monitoring, optional software
sample channels, deadline replacement, elapsed overflow, lease, ADC cadence,
queued kicks and repeated cancellation. Reuse Telemetry/Housekeeping oracles
and unchanged sleep/deep-sleep deadlines. No pending events return to Telemetry.

## 5. Optimize surviving delay recipes, not deleted controllers

After batches 1–4 and the three adaptive loops, nine 200 ns guards survive:
two grant, one ProgramSource decision, two reserve-ACK, two Return-armed and
two Return-cleanup. They contain 1,539 DLYD cells, about 0.114866 mm². Eight of
the original seventeen guards disappeared with their owners. The live map has
126 long guard instances and 3,603 DLYD cells in total; do not reuse historical
owner or guard counts when estimating further savings.

For each survivor, bind source and destination to protected leaf pins:

| Family | Required ordered endpoints |
| --- | --- |
| Grant | Reservation/role capture and latest stable eligibility before the actual grant consumer |
| Decision | Stable decision value and request before commit/cancel use and retirement |
| Reserve ACK | Retained history before the sender may withdraw/reuse; complete low/return before a new reservation |
| Return armed | Latest payload/permission capture before publication/receipt offer |
| Return cleanup | Every branch returned and history captured before pending clear/rearm; preserve absolute pulse floors |

Use the existing reusable leaf timing tool and
[same-corner policy](gf180-guard-sizing.md): 20% two-sided engineering derate,
2 ns residual, actual loads/slews, setup/hold, both transition polarities,
reset and return contexts. Measure the competing cone, calculate a candidate
chain, validate the selected count at every affected instance/corner; avoid a
large blind sweep. Missing paths, extrapolated electrical failures or an
uncomposed launch are not a pass. Keep absolute SRAM/pulse/reset timing distinct.

Only then evaluate the nine-buffer primitive output recipes (3,960 buffers /
0.052158 mm² at `a5a68cd`, down from the historical 0.082623 mm² as owners were
deleted). Keeper isolation and an exclusive repairable parent driver
remain necessary; the nine-buffer depth is not automatically necessary. A
smaller characterized recipe must reclose minimum pulse, ACK, reset and rearm
obligations. Regenerate the declared graph rather than relaxing its proof.

The FrameStore's four-lane return guard and the SRAM owners' four-lane output
guards delay independent handshake histories. They are not per-bit payload
allowances; sharing one chain requires an ownership change. The prior Return
cleanup-deletion candidate remains a separate opportunity: causal completion
could remove 342 DLYD cells, but historical nominal SPICE observations do not
bound its keeper pulse and return apertures. Reuse the argument and chip tests;
remeasure the current graph before adopting the deletion.

## 6. Resolve the large I2C storage cost through the host ABI decision

Current I2C native recipes occupy 0.191465 mm² and its ordinary edge/front state
contains 942 flip-flops. The hierarchical attribution is about 0.350690 mm²
including ordinary logic; that is not an exact module partition of the flat map.
The four frame banks, publication copy, byte buffer, 64-bit reset epochs and
per-edge read-word payload reflect the framed protocol and backpressure contract.
They cannot all be called dead storage.

The next concrete deliverable is B's register-pointer wire specification and
matching host-tool transition, before frame RTL. Recommended shape for review:
one staged 32-bit write plus pointer/admission context, explicit busy/error and
completion status, commit only on a complete accepted word, and NACK before
accepting another word when full. Partial STOP/timeout/repeated START must not
commit a word. Define pointer units/endian/increment/bounds and versioning in
that specification; reuse Control's existing streaming loader/CRC path.

That decision should delete the 33-byte command assembly/publication and four
frame banks as a set, rather than optimize their routing. Keep the current
269-bit read snapshot until its replacement atomicity is explicitly specified.
Do not assume a clock-stretch output exists or discard accepted traffic when
native processing is slow. Retain bounded wire sampling and asynchronous SDA
wake. Both native implementations and host tools must migrate together.

Directly writing bytes into the existing frame banks is not the preferred
intermediate step: converting 1,348 latch bits to event flip-flops would add
about 0.0355 mm². Removing the 601 existing receive/publication event bits saves
about 0.0449 mm², leaving only about 0.0094 mm² before new byte capture trees.
Changing bank technology can consume nearly all the apparent bit-count saving.
No unmeasured I2C saving is included in the 1.60 mm² gate.

## Mapping and library changes that are actually justified

`tools/gf180_physical.py` preserves every native recipe leaf and exact connection.
This blocks removal of unused payload lanes, constant propagation across those
banks, equivalent-copy merging, delay shortening and weak-driver resizing.
Protecting keeper graphs, capture distribution and handshake timing is correct;
protecting needless payload is a cost that must be fixed before mapping.

- Project fields **before** protected storage and regenerate typed endpoints,
  trees and exact graph checks. Do not globally remove `keep`/`dont_touch` or
  ask synchronous ABC to infer asynchronous retiming. The CPU's 107 physical
  trace and 37 consumed writeback bits are removed in
  [adaptive loop 3](area-optimization-loops.md), preserving trace in default
  verification exports. The measured flat saving is 0.011593 mm²; this is a
  follow-up to the larger ownership rewrites, not a substitute for them.
- Propose a public resettable native AND in chisel-async. Currently 28 BD
  logical-AND helpers each use four public ControlGates because the library AND
  is private. Replacing them with a public primitive has a gross current recipe
  opportunity of about 0.0129 mm² before any hold repair. The current four-gate
  recipe uses 48 cells versus 12 for the existing internal AND binding. Require reset/hold/ACK and both-variant tests;
  the shorter logic path is not a timing-free substitution. This library change
  needs its own approval, tests and review; it is not prerequisite to batches 1–4.
- Do not remove meaningful reset state, memory-return buffers, native eligibility,
  GPIO pin isolation, clocked event cutoff arbitration or physical pin controllers
  to meet an area target. Do not replace closed feedback banks with transparent
  latches without a new feedback/race-through contract.

Resetless storage is a selective opportunity: 3,188 ClosingLatch bits and 2,239
EventRegister bits remain at `a5a68cd`. Separate validity-qualified transient
payload from initialized tokens and architectural state. Do not replace an
edge-capture feedback bank or GPIO output register with a transparent latch.
Payload optimization needs an explicit live-lane correspondence and regenerated
capture/reset trees; dropping all protection is not an equivalent implementation.

After the host change, evaluate one-work-bank implementations of ADC scaling
and elapsed arithmetic, then CPU state transport. Preserve the independent LF
watchdog and RF write guard. Set their budgets from the new map; do not promise
an additional total by adding overlapping historical opportunity pools.

## Execution and evidence for each batch

1. The user selected BD first after this plan was reviewed. Implement these
   batches only in BD, retaining shared semantic oracles and unchanged Click
   regressions. Keep Click and the independent synchronous design as comparison
   references; a later Click conversion requires its own scope and review.
2. Run affected chip tests listed above, fast CI, generation audits and RDC
   proofs. Preserve behavioral expectations and deadlines. Test cancellation
   and backpressure at every changed ownership transition; no new count-only
   test suite. Reuse existing negative controls by timing/proof kind.
3. Map against the immediate parent using the identical production profile,
   compiler/library, flat mapper and fixed macros. Record latch/FF storage,
   DLYD and other delay buffers by purpose, protected versus ordinary logic,
   Services/bridge periodic sinks and total area in the existing area ledger.
   Use the hierarchical attribution only to locate ordinary cones, not to mix
   area totals with the flat reference.
4. Run the accepted electrical repair and affected BD local timing/launch/
   feedback/return checks. Record actual added repair area. Neither the existing
   repaired hierarchy area nor an unchanged owner name qualifies a new flat
   design. Measure the same maintenance, ADC and firmware wake windows plus
   full-capacity boot; report edges and elapsed time separately.
5. Obtain a fresh independent review, fix findings and commit a verified batch.
   If a storage/area budget misses, stop and explain which replacement cost
   consumed it. Do not compensate by weakening a timing/test requirement.

Full-chip P&R follows the integrated ownership/host work, rather than another
die experiment after every small edit. Item 17 still requires zero router DRC,
compact keeper/output geometry, extracted min/max RC, electrical and coupled
noise checks, complete launch/capture/ACK/hold/reset and SRAM clock checks.
Keep the separate 0.05 mm² routed hold-repair reserve. Results from pre-fix
wire units or missing SPEF remain void. A mapped-area milestone is never the
tape-out gate.

The original planning review used source and existing measurements. Implemented
batches and their fresh verification are linked in the status above; none claims
new routed qualification.
