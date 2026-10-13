# Direct capture of retained native service replies

Status: C1 digitally verified and independently reviewed, 2026-10-13. This is removal of
duplicate periodic-clock payload banks, not a complete native service scheduler
or physical timing qualification.

## Ownership and scope

Control, Telemetry, Housekeeping and Supervisor already own native reply storage
in each separate design. Their previous clocked receivers copied each reply
before the clocked service consumer captured it again on `reply.fire`.
`FourPhaseServiceReplyReceipt` and `ClickServiceReplyReceipt` keep the previous
control synchronizers and acceptance FSM but expose the held native payload
directly. No payload storage or additional delay guard is introduced.

The producer, receipt and permanent service state remain POR-owned. Application
reset does not destroy an offered native reply. Existing synchronous application
cancellation, immutable reservation roles, accepted-effect accounting and
permanent Groundlark supervision remain in force.

The native Control, Telemetry and Supervisor forks retain their complete reply
until the reply branch acknowledges. Housekeeping feeds its state-return request
from reply acknowledgement, retaining the update output until acceptance. These
producer contracts are prerequisites for direct capture; this receipt must not
be substituted for a receiver of a revocable or changing payload.

## Capture and return

Two synchronizer stages observe native request. The receiver preserves its
existing wait/settle/present control sequence. The consumer captures only at a
real work-clock edge with `valid && ready`; that same edge updates ACK. No
speculative acknowledgement is permitted. A stopped work clock cannot capture
or acknowledge. The producer must retain its payload throughout backpressure.

BD retains acknowledgement until synchronized request withdrawal and completes
RTZ before reuse. Click acknowledges the accepted request phase, independently
for both directions, with no four-phase conversion. POR aborts the old token and
clears phase history using the existing asynchronous assertion and local
synchronous reset-release mechanism. Application reset is not a receipt reset.

Payload outside valid is unspecified and may change. Every architectural effect,
publication and accepted effect must remain qualified by the appropriate valid
or fire condition. Payload-dependent ready logic alone does not authorize work.

## Verification and physical obligations

`ServiceReplyReceiptSpec` uses independent data/effect expectations, exercises
every bit of wide replies, pauses acceptance and receiving clocks, and checks
POR and application-reset overlap. A retained old receiver compares control
cadence only. Composed service, supervisor, loader, firmware, sleep and reset
tests retain their original behavioral expectations.

Strict export probes must resolve each actual native producer storage cell and
its complete field packing before driving it. Deleting a clocked data bank does
not authorize forcing its replacement combinational alias or reducing endpoint
activity checks. Require POR/reset binding, exact receipt state/control and
direct payload wiring, unchanged ports, and absence of duplicate payload state.

The old receiver's separate payload-register setup check no longer applies.
Qualify the complete native-storage-to-consumer data/enable paths, request
synchronization aperture, and earliest data release following ACK against the
actual consumer hold requirement. Include skew, routed RC, reset distribution
and all relevant PVT corners. Preserving the digital waiting interval does not
establish these physical bounds. Keep this path explicit in the timing ledger;
do not replace it with blanket false paths or a fictitious periodic native clock.

R2b's excessive reset slew and R3's independent frame-copy race remain open.
Negative dynamic path delays from out-of-range Liberty extrapolation are
violations even without an explicit minimum; nonfinite values fail measurement.

## Matched cost of this correction

The same mapper, pinned libraries, native bindings, guard mapping and physical
policy compare C1 with R4's `2e4169c` RTL (unchanged through `8f2b21a`). Independent
hierarchical accounting finds all savings in ordinary logic. Every mapped native
and guard leaf and all three SRAMs are unchanged.

| Metric | BD before → C1 | Click before → C1 |
| --- | ---: | ---: |
| Logic area excluding SRAM (mm²) | 3.492221 → 3.351844 | 4.345699 → 4.206056 |
| Total mapped leaf cells, including SRAM | 126,405 → 122,587 | 128,223 → 124,516 |
| Work-clock storage cells | 5,985 → 4,731 | 6,036 → 4,782 |
| Work-storage clock-input capacitance (pF) | 20.774969 → 16.579085 | 20.946395 → 16.750511 |
| TT listed-state leakage envelope, including SRAM (µW) | 9.129–11.987 → 8.761–11.453 | 10.817–14.705 → 10.449–14.177 |
| Firmware work-clock edges per wake | 3,256 → 3,256 | 3,161 → 3,161 |

Area decreases by 4.02% BD and 3.21% Click. This is a measured incremental
improvement; both remain substantially larger than the historical clocked
service island. Listed-state leakage is not measured reachable-state standby
power, and clock capacitance alone does not establish energy savings. These
are mapped results, not new P&R or timing closure.
Fresh activity runs retain the same 22 maintenance, three sampling and two
firmware windows per variant, with 43 retired instructions in each firmware
window. Maintenance and sampling work edges remain 22/216 BD and 19/214 Click.

The independent receipts are under
`build/async-service-publication-repair/review-state/`: `r1/receipt.json` and
`r1-controls/controls.json` bind compiled state, public ABI, bit mapping and
actual-RTL rejection controls; `mapped-r2/receipt.json` binds 1,280 mapper/library
inputs. No historical comparison evidence was overwritten.

## Completed checks and retained failures

- The eight new receipt cases cover all wide payload bits, the old control
  cadence, backpressure, POR, immediate legal source reuse and stopped clocks.
  Composed service/reset/sleep/firmware tests preserve application cancellation,
  image/lock, retained SRAM and permanent-supervisor behavior.
- `focused-r1.log` retains the initial 39/40 result. The failing Click scaling
  fixture selected an idle high request phase; its diagnostic proves request
  equals ACK and no pending work. The corrected test selects request/ACK
  mismatch, repeats both phase directions, and asserts their coverage without
  changing the original pending-work, consumed-state or sleep expectations.
- `regression-r2.log` retains 162/164 across 13 suites. The only failures were
  90-second host execution timeouts in BD's long Groundlark sleep and abandoned
  I2C cases. Exact unchanged binaries passed at 63.07855 ms and 93.241 ms simulated
  time, below unchanged 100 ms and 200 ms deadlines. Original binaries, testbenches
  and empty timeout logs are hash-bound in `sleep-exact-binary-r1.json` and
  `deep-exact-binary-r1.json`. Only those long cases receive a 300-second host
  allowance; no simulated timing bound or behavioral assertion was relaxed.
- `regression-r3.log` passes all five follow-up commands: six scaling-sleep
  cases, both Groundlark sleep cases, both abandoned-I2C cases, 65 core/reference,
  activity and quiescing-boundary cases, and four physical-emitter/core-policy
  cases. The initial cohort's other service suites also passed.
- All 452 Python controls and four portable/inline strict exports pass.
  Sixteen emitted receipts and 96 actual RTL mutations validate clock/reset,
  synchronizers, ACK, storage inventory and aliases. Independent emitted bit
  walks and broken-alias controls cover both variants and configurations.
- The routed-probe correction rejects negative dynamic delays, nonfinite
  measurements and unplanned path polarities. Exact graph-proved reset
  exclusions remain diagnostic. Twenty-five focused controls pass; the old
  helper fails 12 targeted controls, and both existing probe catalogues remain
  fully accounted for. This does not turn old physical violations into passes.

`final-evidence-r1.json` binds the passing follow-up logs, original failures,
strict results and reviewed source files. Digital exports, mapped costs and
constraint binding do not qualify the new physical capture boundary.
