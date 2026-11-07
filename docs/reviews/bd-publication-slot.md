# BD publication-slot review

Batch 2 against `212a5d5`. Independent reviewer: `bd_publication_slot_review`.
The implementation, RDC proof, adapted tests and repaired bank-reader results
have no remaining functional review blocker. Final fast CI passes: 387 Python tests and 224 Scala cases (206 fast chip,
12 generic boot and six physical/export checks). The r2 receipt includes new
untracked source files as inputs; the CI inventory now covers them.

The new POR-owned receiving-edge slot replaces Telemetry/Housekeeping reservation
round trips. It has no payload. Native banks, command senders, reply receipts,
reader qualification and accepted effects remain. Program/RAM native eligibility
and Click RTL are unchanged.

Findings fixed:

- Rejected grants retire silently: no accepted effect means no drain receipt.
- Client quietness no longer depends on publication backpressure. Outstanding/
  queued state and real channel return establish occupancy. Existing held-reply
  tests caught this stale dependency; both initial deadline failures are retained.
- Debt clears only after an accepted fresh recovery, its qualified reply and full
  actual return. Later cancellation revokes recovery too; idle channels alone
  never prove completion.
- RDC proves the actual work clock, POR defaults and coordinator cancellation.
  No native-status/payload exemption was added. The assertion-only diagnostic
  tag may disappear; functional phase, role, revocation and debt may not.
- Tests stall the real reply receipt ACK return, observe request/ACK/bank-ready,
  and repeatedly reset there. Staged-effect tests change the unaccepted CPU bus
  and verify the original retained command when it issues, exactly once.

Three former tests assumed offset 8 still reserved both owners. That was already
false: both variants fail on the parent (`build/bd-word-loop/publication-baseline-deadline.log`).
Replacements test actual Telemetry offset 24 and Housekeeping offset 56 separately,
retaining admission, cancellation and payload oracles. The other owner must not
be a dependency. The second directed run passes 36/36 cases in both variants.
Both generation and RDC audits pass. Original native BD Source/RecoveryReturn
component fixtures moved to verification-only sources; unused Boundary and
ReturnReceipt production helpers were deleted.

The broader digital run passed 100/101 cases. Its remaining test failed to
compile because the monitor named deleted Boundary debt wires. BD now probes
the actual slot debt; Click keeps its existing probes. Both targeted real-gate
tests pass, retaining receiving-edge, payload, exactly-once and macro-write
assertions. The four BD deep-sleep cases also pass. Initial failures remain in
`build/bd-publication-slot-tests-r1.log` and `build/bd-publication-slot-extended-r1.log`;
passing replacements are in their r2 logs.

## Repaired timing and open physical gate

Five corners and two input slews were run on the repaired hierarchical map.
The application bank's 224 periodic reader D pins pass: minimum setup +25.652 ns,
hold +1.160 ns, bank-to-feedback ordering +13.047 ns. Exact Services aliases now
bind in either inline or retained hierarchy, with conflicting aliases rejected.
No reader or qualification check was removed.

Housekeeping's 905 bank-reader paths have positive bounds: setup +183.430 ns,
hold +1.395 ns, feedback +11.079 ns. However, the **overall Housekeeping campaign
fails** its separate one-period qualifier/selector setup check: -7.680 / -8.167 ns
at SS125 for 0.02 / 2 ns slew. The other eight cases pass. Qualifier hold is at
least +0.432 ns. The bank's A+5 allowance is never applied to qualifier paths.

The same `housekeepingReturning.Q -> housekeepingPayload.period[11].D` path
already fails on the SRAM parent at -5.349 ns for SS125/2 ns. Remapping worsens it
by 2.818 ns derated (raw combinational delay 39.145 -> 41.493 ns). Two ordinary
enable gates driving 116 and 163 loads contribute 13.958 ns. The concrete next
physical correction is graph-preserving bounded-fanout buffering on these nets,
then the same setup and hold checks. No storage, clock, longer period or native
guard is justified by that ordinary path. This remains a physical-gate failure.

No logged electrical-violation pin intersects the reported winning paths in
70 path logs. This is not complete electrical closure: other cones, continuous
slew, extracted min/max RC, CTS skew and reset distribution remain open. No native
bank transform or surviving guard count changes in this batch. Evidence is
`build/bd-publication-slot/{application-bank-r2,housekeeping-bank-r2,
parent-housekeeping-ss125-2-r1,bank-review-summary.json}` plus both full path reports.
The Housekeeping and targeted parent receipts correctly report **fail**.

Flat logic measures 1.591292 mm² (parent 1.718196); hierarchical repaired logic
1.855785 mm² (parent 1.988072). Flat periodic sinks fall 2,898 -> 2,822 and
hierarchical sinks 3,125 -> 3,019. Services stays at 64 service + 912 work sinks.
DLYD falls 4,973 -> 3,549. Firmware wake activity falls 4,166 -> 4,138 work edges;
maintenance/acquisition and Click are unchanged. The [ledger](../area-ledger.md#bd-publication-slot-rewrite)
separates these measured reductions from open physical qualification.

Final CI evidence: `build/bd-publication-slot-ci-r2/{receipt.json,python.log,scala.log}`.
