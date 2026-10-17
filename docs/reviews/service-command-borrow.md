# Service command ownership batch: 11b2 and 11b3

This batch removes duplicate periodic sender payloads from both implementations.
Housekeeping borrows 211 bits from its existing ordered bank; Telemetry borrows
51 immutable commit operand bits from its existing commit bank. The native
commands and public ABI do not change. No periodic clock, synchronizer, native
payload store or production ownership register is added. The matched maps confirm
262 fewer periodic storage cells per variant, with native/event storage unchanged.
The [single area ledger](../area-ledger.md) records the measured batch costs;
storage counts alone are not area or energy measurements.

## 11b2: one Housekeeping command bank

The existing `housekeepingOrdered` bank now retains every command, including
background elapsed batches and recovery. The existing command sender transports
only the recovery role. That role remains independently attributable through its
native publication reservation, in-flight command and reply. Background writes
force the borrowed bank's unused recovery field to false. Ordered selection
and the borrowed payload's schema output also explicitly drive false, so the
unreset bank's old/self-hold state cannot enter the recovery-role cone. This
avoids an extra physical mirror bit; focused tests require real recovery dispatches to retain
true role identity through the separate sender.

- An ordered CPU action or accepted host period update writes the bank before
  dispatch, exactly as before. Dispatch clears its pending flag but leaves the
  bank unchanged.
- A background command writes the same bank on its existing sender-acceptance
  edge. The unchanged sender settling interval precedes its native request.
- New elapsed observations continue accumulating in `housekeepingQueued` while
  the retained command stalls. The in-flight board-time and period projections
  remain independent of later queued observations.
- Publication updates Housekeeping state and `consumedGray`, then clears the
  in-flight projection. Publication does **not** release the borrowed bank.
- Full sender return releases the bank. BD waits for the complete request/ACK
  return to zero; Click retains its native phase history. Both use the original
  sender's work-clock `in.ready`, with no new synchronizer.

A competing Control period-update reply may arrive after dispatch or publication.
It now waits for both no outstanding Housekeeping command and command-sender
idle, as well as an empty ordered pending slot. CPU admission already observes
Housekeeping outstanding/drainage barriers. The `HOUSEKEEPING_BORROW_OVERWRITE`
assertion covers every ordered-bank write. This backpressure cannot block the
prior Housekeeping reply: that reply does not depend on the waiting Control
period update. Both outcomes are exercised with an actual on-wire host command.

## 11b3: Telemetry immutable commit operands

The periodic Telemetry sender retains recovery, kind, events, elapsed upper bound
and acquisition captures. Its 51-bit `clear`, `offset`, `data` and `appIndex`
projection comes directly from the existing `telemetryCommit` bank for Commit
commands and is explicitly zero for Observe and ResetApplication commands.
These observations remain independently queued; the accumulating Supervisor bank
is not borrowed or frozen.

A CPU commit cannot replace the bank until both the old outstanding command has
published and its sender has fully returned. `telemetryBarrier` includes sender
idle explicitly, and `TELEMETRY_COMMIT_BORROW_OVERWRITE` checks acceptance.
Application cancellation clears the pending-valid bit but does not reset the
payload bank or destroy a dispatched native command. POR remains the only reset
for the transport and persistent accepted effects. Existing stale-reply and
publication identity rules remain unchanged.

## Verification and physical scope

`CommandBorrowSpec` instantiates the production Services, native owners, senders
and receipts. Test-only request/ACK phase stalls and a falling-edge work-clock
gate exercise:

- complete command identity from sender acceptance through full return;
- native capture while the work clock is stopped, without early publication;
- a queued second elapsed interval and competing host period update;
- publication preceding sender return without overwriting the old bank;
- application reset during each stalled borrow, persistent time/sample ingress,
  rejection of stale application effects, and resumed CPU progress;
- actual live-source substitutions in each borrowed path, accepted only with
  their exact fatal diagnostic, never a timeout or unrelated assertion.

The original Housekeeping and Telemetry suites passed 22 tests before the focused
campaign. `final-focused-exports-r3.log` passes all 10 final focused cases (six
positive scenarios and four exact-diagnostic controls), including explicit
recovery-role ownership, plus five physical export/policy tests. It emits the
final `physical-r3/{bd,click}` and `portable-r3/{bd,click}` exports. Independent review confirmed all four emitted recovery cones contain no
ordered-bank recovery register and the scalar sender role is
`!OrderedPending && recoveryReady`. `build/command-borrow/activity-r3.json`
compares all 27 ordered wakes per variant with the prior
`build/control-frame-borrow/completion-activity.json`: 22 maintenance, three ADC
and two firmware wakes match exactly, including edge counts, duration and BD ACK
guard activity. It verifies all 304 baseline hashes and freezes the final
sources, testbench, compiled simulation, logs and parser. The activity fixtures
also match the final physical exports; the only primitive-resource differences
are the exact firtool version comment and trailing blank line. The 43-instruction
wakes remain 3,257 work edges for BD and 3,212 for Click. These are native model
activity counts, not energy measurements.

The final broad run passes **284/284 cases in 16 suites**, exit 0, recorded in
`build/command-borrow/regression-r3.json` and its log. It covers activity,
firmware, publication, recovery ownership/return, quiescing receipt/bridge,
reset boundary and integrated reset boundary, I²C, frame admission/wake, core,
Housekeeping, Telemetry and Control reset. At run completion, the receipt
rechecked 419 repository code/build/fixture hashes and listed every exact case.
`verifier-delta-r4.json` subsequently confirms 418 remain unchanged and records
the exact two-line export-adapter addition, new helper and its tests. The reviewed
helper preserves the original polarity checks. A separate final run passes
**20/20 Sleep/DeepSleep cases**, exit 0, recorded in `sleep-r3.json`. Its 196
Scala/build/RTL/firmware/sbt inputs match the original r3 hashes; the receipt
separately records the concurrent export-checker Python change, which these
suites do not execute. Original snapshots and cancelled-run evidence remain
unchanged. Together with the 15 final focused/physical-policy cases,
these runs pass **319 final Scala cases**. All four complete r4b strict exports
also pass with vector coverage and sleep-clock background.
Failure evidence is retained under `build/command-borrow/`: `focused-r1.log` is a
test-fixture Scala indexing error; `focused-r2.log` rejects two Telemetry mutation
cases because the first mutant also removed the non-Commit mask and triggered its
earlier mask diagnostic. The corrected mutant preserves that mask and changes
only the Commit operand source; all eight initial focused cases then passed in
`focused-r3.log`. Positive scenarios and existing oracles were unchanged. Initial strict-export
runs also rejected the old `housekeeping_command_bridge.in_bits_recovery` pin
binding after the sender became scalar. The checker was updated to the exact
new scalar schema and pin, with layout/pin negative controls; the original
`PUBLICATION_BOUNDARY_PIN` failures remain retained. With that binding corrected,
the first candidate failed the existing `PUBLICATION_SOURCE_BINDING` oracle:
background capture had made the otherwise-unused ordered-bank recovery bit live,
so independently probed states could select it as a recovery role. A write-only
constant-false correction passed the reachable-state focused tests but independent
review found the unreset self-hold register still present in all four r2 exports.
The final correction explicitly drives false at ordered-command selection and
at the borrowed schema output; the actual native role still comes from the
sender. The oracle is unchanged; final emitted-cone review and all four passing
strict reruns establish the correction within their digital scope. The first-candidate broad regression remains separate from
those final reruns. `regression-r1-partial.json` records 112 completed cases in
10 suites through DeepSleep before scheduling cancellation; the interrupted
Firmware suite is rerun in full. The r2 regression was cancelled during its
first activity suite after the emitted-cone finding; it contributes no passes.
The four `strict-{physical,portable}-{bd,click}-r3.log` runs retain a further
`ACTIVITY_GAP` on exactly 51 masked Telemetry command/Join lanes: the generic
single-source sweep does not combine a Commit header with nonzero borrowed
operands. Binding checks pass, but the paired fallback correctly rejects its
148–155 million samples and estimated 38–40 GB source under the unchanged budget.
The reviewed checker addition supplies 440 actual-source steps and six pin
equations, preserving all generic campaigns and required bit-polarity coverage.
The initial r4 attempt used an incomplete export copy: physical exports failed
`MISSING_PROBE_ABI`, while portable exports failed `Invalid/missing generated source`
for the quiescing bridge's `verification/assert` source. Both failed before
simulation. The completed copy inventory restores the
required ABI and verification sources without changing RTL;
`strict-r4-export-copy-complete.json` records it.
All four complete r4b strict reruns pass. Their executed mapping-check
counts are **641,757,600 physical BD**, **551,570,844 physical Click**,
**641,546,400 portable BD** and **551,381,724 portable Click**. The
`strict-*-r4b.log` files and each export's `mapping-probe-attestation.json`
bind the actual input sources, compiled binary and simulation log.
`strict-r4-inputs.json` verifies all 690 copied source/ABI/metadata files against
r3. Original generic campaigns, comparisons and every required polarity remain
unchanged. Fresh independent review is recorded in
`build/command-borrow/independent-review-r4.json`.

`telemetry-borrow-controls-r3/report.json` independently freezes the focused
actual-export controls for that checker addition. Both BD and Click baselines
pass all 51 borrowed-bit polarities at the native command and Join input. They
retain the complete original `check` task and execute the helper's 440 source
steps; they make no whole-export coverage claim. Six actual emitted-RTL faults
(wrong selector, removed mask and live CPU source substitution, in each variant)
each compile successfully and stop at exactly the intended first fatal pin and
testbench line. Source, harness, compiled binary and log hashes are retained.
The initial focused harness attempts remain visible: `telemetry-borrow-controls.log`
rejected an incomplete expected port-metadata record, and `-r2.log` records the
missing SoC root in the Icarus compile command. The final harness includes both
the real SoC and `ContractProbe` roots; no production RTL or oracle was changed.

## Matched cost

`build/command-borrow/area-bd-r3.json`, `area-click-r3.json` and `cost-r3.json`
record the final mapped and accepted electrically repaired graphs, matched to
the 11b1 baseline. Area excludes SRAM; repair is before placement.

| Metric | BD before → after | Click before → after |
| --- | ---: | ---: |
| Mapped logic, mm² | 2.825888 → 2.792933 | 3.585890 → 3.554119 |
| Repaired logic, mm² | 3.014986 → 2.978974 | 3.795762 → 3.757950 |
| Periodic clock sinks (including SRAM) | 5,072 → 4,810 | 5,127 → 4,865 |
| Work-clock sinks (including SRAM) | 3,741 → 3,479 | 3,792 → 3,530 |
| Work-clock pin load, pF | 13.2871 → 12.4104 | 13.4585 → 12.5819 |
| Native/other storage cells | 11,271 → 11,271 | 11,424 → 11,424 |

The TT independent listed-state leakage interval changes from 7.9615–10.2012 to
7.8661–10.0698 µW for BD, and 9.4853–12.5217 to 9.3875–12.3838 µW for Click.
These are cell-model bounds, not reachable deep-sleep power measurements. No new
P&R or whole-chip energy claim is made by this batch.

Digital simulation does not qualify either new bundled-data path. Item 17 must
measure each retained Services bank Q through selection/masking into actual
native operand storage D, its sender request/capture aperture, source retention
through latest capture/ACK/return, and POR behavior with real cell/load/slew and
extracted min/max RC. The original settling, guard and reset policies are
unchanged. No guard shortening or new physical timing claim is part of this batch.
