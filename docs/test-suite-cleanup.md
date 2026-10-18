# Test-suite cleanup

The goal is a small set of durable properties plus chip simulations, rather than
a separate checker and custody campaign for every migration substep. This change
preserves independent BD and native Click implementations and changes no chip
behavior. The preceding generic-MCU correction has separate RTL evidence.

## Inventory

Counts use Python unittest discovery and physical source lines, including comments
and blank lines, under `tools/*.py`. The starting tree includes the generic boot
work, which added four tests since the earlier 1,198-test migration baseline.

| Measure | Before | After |
| --- | ---: | ---: |
| Python tests | 1,202 | 292 |
| Test modules | 107 | 36 |
| Python test lines | 18,422 | 3,826 |
| Python implementation lines | 35,161 | 12,973 |

These are measurements, not CI count assertions. Discovery must be nonempty and
successful. The reduced Windows suite passes in about eight seconds, versus about
146 seconds for the retained pre-cleanup run. CI additionally runs fast RTL
simulation; tool-unit-test speed is not chip verification coverage.

## Removed tools

All twelve requested unreferenced checkers are removed:
`check_completion_wiring_controls`, `check_control_frame_borrow`,
`check_gf180_slew_controls`, `check_leaf_join_controls`,
`check_ordering_guard_controls`, `check_passive_feedback_controls`,
`check_program_return_controls`, `check_program_source_controls`,
`check_publication_source_controls`, `check_ram_return_controls`,
`check_ram_source_controls` and `check_sram_fusion_controls`.

Completed-step quiescing, program/RAM source/return, frame admission/capture,
recovery, saved-address, seal-ordering, command-borrow and SRAM-fusion mutation
checkers and their checker-only fixtures are retired. The successor registry,
class-file/source attestation binding and per-campaign receipt tests are removed.
Unused pilot graph-edit implementations are reduced to the three helpers still
used by production guard sizing. The actual experimental SRAM byte-owner pin
campaign stays: Scala invokes it and it tests real reads/writes, masks, reset,
contention and invalid requests rather than a retired migration source shape.

## Durable coverage

| Obligation | Current owner |
| --- | --- |
| Primitive and owner inventory; native outputs driven | chisel-async `StructureAudit`, at export generation |
| No ordinary sequential helper hidden in a native owner | Same typed HW/Seq audit, including helper ancestry |
| No combinational periodic-clock path into native storage | Same audit, checking all storage inputs, not only triggers |
| Primitive cells/pins intact after mapping/repair | Complete mapped graph and buffer-contraction proof |
| Only reviewed keeper arcs cut | Native leaf timing and routed query generation |
| No unused added cells | Repair graph proof |
| POR/application reset containment, close/rebase crossings | MCU RDC audit and actual reset/bridge RTL suites |
| Fixed SRAM identity/model semantics | Locked asset validation and chip SRAM tests |
| Setup, hold, ACK ordering, period invariance | Shared stage/leaf margin properties and one actual-arc control runner |
| Routed polarity/query completeness and finite arrivals | Production routed checks plus selected headless Tcl properties |
| Join/RF source and lane identity | Production composition plus two source-provenance properties |
| P&R RC, clock and repair checkpoint dependencies | Production resume checks plus three regression properties |
| ABI, boot, lock, sleep and functional behavior | Scala RTL tests; Python image/firmware utilities where appropriate |

The library addition is source-pinned at
[`83d6468`](https://github.com/BiscutLabs/chisel-async/commit/83d646825da854f93d59f6b2055ecde369e62242).
Its eleven structural tests include negative generation cases. It is a
combinational clock-provenance audit: divided clocks need explicit classification.
Opaque external models, such as the fixed SRAM, remain explicit boundaries.
It is not an RDC, timing, metastability or physical cell proof.

Assertions now follow actual selected owners, lanes, faults and corner/slew
inventories. The SRAM candidate requires every case in its live inventory to
complete with its expected outcome/site. Counts in diagnostics remain useful;
counts from an old implementation are not acceptance criteria. Small exact
widths/constants remain where they define an ABI or a deliberately fixed fixture.

## Coverage deliberately retired

The following were unique checks; removing them is a reduction in verification,
not a claim that a generic structural audit proves the same behavior:

- Exhaustive production-pin mutation sweeps and owner-specific generated mailbox,
  borrow, cancellation, return and seal equations. Behavioral Scala tests and the
  retained RDC/graph proofs cover the contracts, but do not reproduce every
  injected fault or every source-shape equation.
- MCU whole-export endpoint/polarity walks and large probe comparisons. The new
  export reader checks bound generation evidence; it does not run those dynamic
  probe walks or recreate their fault inventory.
- MCU calls to the library's full manifest/port-ABI validator, including endpoint
  packing/signedness, timing-marker wiring and reset-binding equations. The
  library still owns its validation and tests; the MCU retains ABI behavioral
  tests and digest binding, which are narrower integration coverage.
- Per-campaign fault combinations beyond the shared setup/hold/ACK/period/graph
  controls. A newly unusual controller or boundary still needs a focused chip
  test; the shared controls do not qualify arbitrary circuitry automatically.
- Source/class-file family tamper, successor-chain and repeated evidence custody
  tests. Normal reproducible builds, the pinned library and one run receipt
  replace this workflow; they are not a security attestation system.

Routed-query truncation/nonfinite/reset-exclusion controls, Join provenance and
P&R corner/clock/resume properties were initially candidates for deletion but
were retained after independent review because they protect distinct live checks.
No behavioral chip oracle or simulated deadline was relaxed for this cleanup.

## One receipt and CI

`RunReceipt` records input/tool/output hashes once per distinct file and the actual
command outcomes. Changed input size/mtime, missing outputs and failed commands
fail the run. It does not authorize successors or rehash an attestation chain.
Existing mapping/P&R dependency records remain necessary to resume the same
physical graph; they are not additional review approvals. Historical evidence
stays in ignored build directories and source history.

The GitHub workflow runs the same `tools/ci.py` command on main pushes and PRs.
It publishes the pinned library source locally, sets up pinned JDK/firtool/Icarus,
runs Python properties and fast Scala chip simulations, checks fresh JUnit
execution, and uploads results even on failure. Only the named Windows-path test
may be skipped on Linux. The full boot/reset/SRAM/firmware suites remain extended
checks when those subsystems change. See [build and test](build-and-test.md).

## Verification for this batch

Both Windows and Linux Python gates pass; Linux skips only the explicit
Windows-path fixture. The first Linux attempts failed closed on missing Tcl and
Icarus, then passed after installing the same dependencies used in CI.

The complete local fast gate passed 292 Python tests and 166 Scala tests
(153 core/service/boundary cases, eight SPI boot cases and five physical-export/
core-policy cases), with fresh JUnit reports. The final routed truncation control
was then strengthened and all 292 Python tests passed again. Both variants'
production and portable exports pass the generation-audit reader. Both production
RDC proofs pass. The full 28-case boot suite and experimental SRAM byte-owner
campaign pass separately. These are digital/structural results, not physical
timing qualification.

The library's normal sbt run passes 87 tests, including the eleven new generation
audit cases. The generic MCU and cleanup received separate independent reviews;
the final integrated tree avoids publishing a stale legacy checker between them.
Logs and receipts are under `build/test-suite-cleanup/`, `build/generic-regression-r9.log`, `build/generic-regression-r10.log` and
`build/generic-mcu-r10/`. Earlier strict export results predate the final CPU/host
arbitration fix and are not claimed as final-tree passes.
