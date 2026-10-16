# A2b loader metadata completion

Acceptance: **digitally verified; matched cost recorded; physical timing open**. Physical timing remains unqualified.
The [completion evidence manifest](loader-metadata-a2b-completion-evidence.json)
binds the executed receipts, source identities and retained failures.
This completes only the loader-metadata WIP scope; the broader migration stays
paused. The accepted comparison baseline is C1e1 `64e6211`. RTL, compiled classes
and functional evidence from checkpoint `3183a54` remain unchanged. Export
validation uses an explicitly reviewed checker-only successor.

## Scope and preserved behavior

Both independent native Control implementations retain byte length and received
count at `bitLength(programBytes)`, including full capacity, and entry at
`max(1, bitLength(programBytes - 1))`. At 2 KiB these fields are 12/12/11 bits;
state/token/reply widths are 244/276/315 bits. Full 32-bit BEGIN length/entry and
WRITE offsets are validated before narrowing. Entry readback pads to 32 bits
before adding the program base. Public command/frame layouts and addresses,
CRC/image IDs, native handshake and return behavior, POR ownership, watchdog
isolation, image/lock retention and permanent supervision are unchanged.

Only Stored for an outstanding word commits CRC and advances the byte count.
Full-capacity completion cannot wrap; duplicate Stored is inert. The reduction
adds no clock, periodic stage, handshake adapter or delay-budget exemption.

## Verification and source custody

The retained run passes 536 Scala tests in 36 suites. Its original 709-test Python
receipt remains unchanged; the current checker successor passes 751 Python tests.
Twelve capacity cases cover both protocols at 4, 12, 1024, 1028, 2048 and 3072
bytes, with independent literal layouts, Java CRC32 expectations, every discarded
host bit, full images, invalid BEGIN preserving a valid image, last/duplicate
Stored, reset, lock and maximum entry readback. CRC rendezvous controls pass
27 original replays and reject 27 mutants at their exact first fatal sites.

Resumption binds the original 436 source files, two checkpoint documents, 481
compiled classes, 59,746 previously rehashed review artifacts and 692 identical
export inputs. Before editing the checker, all 164 original Python tool files
were archived byte-for-byte. Historical records resolve those explicit archive
aliases, preserving the evidence for the original 536 Scala, 709 Python and CRC
campaigns without rewriting their receipts. The checker successor used for
validation contains one changed checker, `tools/check_export.py`, and four added files:
`check_program_address.py`, `test_program_address.py`, `check_probe_budget.py`
and `test_probe_budget.py`. No RTL or compiled class changes accompany them.

The historical library Python tools are reproduced from `f6c3a9b`; the RC1 JAR
dependency is unchanged. Required reviewed hashes bind the ignored orchestration
scripts and complete focused-control evidence as well as maintained sources.
Interrupted and failed outputs remain in their original directories; r2 strict
validation uses fresh export copies. The previously reviewed full artifact cohort
is anchored through its immutable r1 binding rather than relabeled as a new run.

### Bounded-address proof and paired-probe resource limits

ProgramAccess's command input can never assert its capacity-discarded upper
address bits. Requiring one-polarity activity on those bits caused the r1 strict
failure. The successor proves zero from the actual emitted combinational cone,
with every native and periodic storage output unconstrained and no reset, valid,
admission or software-state assumptions. It applies only to the exact validated
command-input schema and capacity; each simulated check still asserts four-state
zero. Mapping comparisons and all four mandatory sweep campaigns remain intact.
Unknown logic, an unsupported boundary or a failed proof rejects the export.
This finite Boolean proof does not establish hazard-free physical behavior.

Focused controls pass on all four actual export graphs. Eight exact mutants
(loader upper-wire injection and CPU range-mux bypass in each graph) produce the
required SAT counterexamples; all 34 proof-helper unit tests pass. Their exact
cone, script, log and receipt files are included in successor custody.

The paired fallback is separately guarded before the library allocates its
stimulus. Its exact driver inventory and pairing-algorithm fingerprints bind an
O(drivers) size calculation. Exceeding 250,000 additional paired samples,
1,000,000 additional source lines or a 64 MiB conservative additional-source
bound fails with `PAIRED_PROBE_RESOURCE_BUDGET_EXCEEDED`. These limits are not
claims about total host memory. No stimulus is truncated and a resource rejection
cannot establish an export pass. Eight resource-helper unit tests pass as part
of the 751-test successor campaign.

All four portable/physical BD/Click strict exports pass, each retaining all four mandatory sweep campaigns. Held-payload controls pass 520 structural negative cases, four actual-wiring baselines and 48 exact wiring faults.

All four actual export graphs pass their baseline audits and reject all 304 exact negative controls. The process replay uses the identical reviewed worker and complete cohort.

The binding and exact original evidence are retained under
`build/async-loader-width-finish-r2/`. Fresh independent review records cover the production checker, strict probes, boundary controls, matched costs and bounded timing evidence. Their hashes are retained in the completion manifest; physical failures remain explicit.

## Matched cost and bounded physical screens

Against the accepted C1e1 maps, logic area excluding SRAM changes from
2.862584704 to 2.8309672384 mm² BD and 3.629653440 to 3.5965234816 mm² Click.
183 native payload bits and 40 periodic bits
are removed per variant. The mapped work-clock inventory falls from 4,068 to 4,009 storage-cell inputs in BD and from 4,119 to 4,060 in Click. Pin-only clock capacitance falls from 14.378128 to 14.183811 pF and from 14.549554 to 14.355237 pF, respectively. The complete fanout inventory reports 43 to 43 BD and 46 to 42 Click nets exceeding a listed pin-capacitance limit; wire RC, slew and the full capture/hold aperture remain unqualified.

All 27 ordinal wake windows per variant remain unchanged; the 43-instruction firmware wakes still use 3,255 BD / 3,160 Click work-clock edges. The full five-corner listed-state leakage and accounting
appear in [the estimates](../gf180-estimates.md) and [area checklist](../native-area-reduction.md#a2b-capacity-sized-loader-metadata).
These are mapped costs and native-model activity, not measured deep-sleep power
or wake energy. Three SRAMs and unrelated native ownership remain accounted.

The bounded screen records all 100 selected input-to-payload-D queries across 20 baseline/candidate, BD/Click and five-corner cases. All queries resolve; 28 exceed the unchanged 10 ns budget: every Control update case and both slow-corner CRC cases for each side/variant. The largest reported update propagation changes from 58.590066 to 51.492380 ns in BD and from 33.859032 to 37.777405 ns in Click. Click's selected update path worsens at all five corners; that regression remains explicitly open. CRC results are unchanged, reaching 16.852150 ns BD / 16.849191 ns Click. These are selected worst-slack paths with source arrival subtracted, not a proof of maximum propagation over all paths. No clocks, false paths, case analysis, loop cuts or timing waivers were added.

The historical CRC transform already exceeded its 10 ns allowance (16.025093 ns
BD / 16.021669 ns Click); no later screen converts that historical failure into
a pass. Complete native source reuse/hold, request/data alignment, actual capture
and ACK-release aperture, pulse widths, reset/clock distribution, electrical
limits and routed min/max RC remain open. Isolated selected-path screens do not
establish every path's propagation bound or complete timing qualification.

## Retained failures and remaining work

The original four strict runs were interrupted at the user's pause and remain
`FAIL_OR_INCOMPLETE`, with all four cases recorded as failed after their owned
processes stopped. The [paused checkpoint](loader-metadata-a2b-review.md) and
its [original evidence manifest](loader-metadata-a2b-evidence.json) remain history.
The earlier runtime selector failure (`vvp.conf` / `vvp.tgt` mistaken for an
executable) remains archived; the repaired selector and its negative controls
were used for completed CRC evidence. Resumption's initial custody preparation
was also interrupted before copying exports when review found the CRC-count
and evidence-binding defects; its original script and interruption record remain.

The first completed resumption attempt under `async-loader-width-finish-r1`
failed all four strict cases. Each first pass reported `INACTIVE_ENDPOINT` for
ProgramAccess command-address upper bits. The fallback then attempted roughly
155–164 million pair stimuli per export and raised `MemoryError`; source text
alone was estimated above 30 GB per export. Its logs, first-pass probes and
receipts remain bound in `retained-r1-failure.json`. The checker-only r2 successor
addresses the proven constant-bit obligation and fails excessive paired work
before allocation; it does not erase or reclassify those failed executions.

The coordinating agent deliberately stopped the threaded graph-control run because its CPU-bound workers shared one Python interpreter. Its INCOMPLETE_INTERRUPTED_FOR_PROCESS_PARALLEL_REPLAY receipt and partial files remain preserved. The separate process successor replays the identical reviewed worker and complete four-baseline/304-mutation cohort; partial results from the stopped run do not substitute for that replay.

The first transform preparation failed on the original/current checker hash collision before creating a plan or launching hardware. The successor resolves historical checker bytes through the preserved archive aliases and retains the original failure receipt.

The r2 timing screen then stopped at its first case: OpenSTA exited successfully, but the strict parser rejected an unrecognized hierarchy annotation with A2B_TRANSFORM_RAW_UNKNOWN_LINE. The other 19 cases remain NOT_RUN. The reviewed r3 parser accepts only exact ordered hierarchy boundaries on the mapped net route between adjacent numeric leaf pins; unknown, missing, duplicated, reordered or off-net annotations still fail. Tcl queries, path membership, numeric timing checks, the 10 ns budget and process bounds are unchanged. The observed 29.806380 ns update propagation remains a data-budget failure. The earlier failed r3 pure mutation control is also retained.

C1e2's ten smaller receiver payload bits, remaining I2C frame/publication/epoch
reductions, service scheduling, production self-timed SRAM, guard replacement
and physical reset-tree qualification remain open. This PR does not resume them.
