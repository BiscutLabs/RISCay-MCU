# BD compact Telemetry effects review

Independent review has no remaining blocking RTL/test finding. The accepted
command remains in the Join until both effect acceptance and full reply return.
Application/GPIO capture uses the qualified ACK; optional software sample capture
uses ordinary ACK and survives application cancellation. No periodic clock,
payload mirror, crossing or Click RTL change is introduced.

The reply stores kind and recovery only (three bits), eliminating 256 native
payload bits at reference capacity. Existing closed banks, bankReady/returning
reader qualification, GPIO pin isolation, snapshot atomicity and event arbitration
remain. Bank transforms use passive allowances, not per-bit delay cells.

Verification: the fast gate passes 397 Python and 225 Scala tests. Focused and
extended AppRegisters, snapshot/recovery, admission, command borrowing, deep sleep,
activity, Telemetry and PublicationSource suites pass. The final targeted run has
40 passing cases, including the review's delayed qualified-ACK direction. The
first sequence-wrap fixture forced an output-only alias; it now seeds the actual
old bank Q, leaving the increment, real capture and original oracle active.
The original failed log is retained. Generation audits and RDC pass for BD, Click
and the optional software configuration.

The repaired maps pass graph, protected-leaf and direct-control/alias proofs.
Direct-bank composition covers 20 cases (two maps, five corners, two slews):

| Local bound | Production | Optional software map |
| --- | ---: | ---: |
| Setup without receipt-cycle credit | +32.515 ns | +30.512 ns app / +30.629 ns sample |
| Held-command reuse, one guaranteed receipt edge | +51.108 ns | +51.013 ns |
| Same-event bank feedback hold | +1.085 ns | +1.060 ns app / +0.838 ns sample |

Capture high/low margins are at least +41.819 ns. All 754,341 sampled operand and
feedback arc checks stay inside their Liberty tables; ten receipts pass with
unchanged inputs/tools. Setup also reports a conservative existing work-edge
credit separately, rather than hiding it inside the native path.

Production bank readers: 224 paths, minimum next-edge setup +26.391 ns,
same-edge hold +1.160 ns, bank-to-feedback +13.074 ns. Optional software readers
also pass: setup +211.789 ns, hold +1.260 ns, feedback +12.921 ns. Their separate
periodic time arithmetic remains under one 50 ns period (setup +6.651 ns,
hold +0.406 ns), not the conditional bank-read allowance. Conditional ingress
setup/hold is +77.209 / +1.068 ns.

Production selected data-driver trees pass all five corners (worst slew 1.864 ns).
The software map has a retained global electrical failure: rebase-Q reaches
2.577701 ns at SS/hot against the flow's 2 ns target. Its 0.05505 pF load and slew
remain characterized (FF pin limit 15.6 ns; table ceiling 0.3527 pF), and it is
outside every Telemetry operand, bank and capture/source root. It is not waived
or counted as an electrical pass. Whole-chip electrical/reset/noise closure,
extracted min/max RC, clock skew, statistical mismatch and complete primitive
transition qualification remain item 17. Existing Housekeeping periodic qualifier
failures are separate and remain open.

Evidence: `build/bd-telemetry-effects/{map-r1,software-map-r1,timing-bind-r1,
application-bank-r1,software-bank-r1,ordinary-data-production-r1,
ordinary-data-software-r1,summary-r1.json,activity-r1.json}`; fast CI receipt in
`build/bd-telemetry-effects-ci-r1`, failed/updated focused runs in the r1/r2/r3 logs.
The final ACK-skew addition changes tests only and passes the targeted r3 run;
RTL and exports are identical to the completed CI run.

The 27 native-model wake windows per variant match the parent exactly. This
workload sends no Telemetry commands, so no exercised-command energy saving is
claimed. Mapped/repaired area and clock inventories are in the ledger. This is
local zero-wire-RC evidence, not routed signoff.
