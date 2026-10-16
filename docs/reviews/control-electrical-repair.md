# Bounded Control electrical repair

Status: **opt-in electrical improvement measured; paired capture/hold analysis
incomplete; physical timing unqualified**. This is a physical-netlist experiment
on the `6aa8033` tree, after the merged A2b loader-metadata work. It changes no
Scala RTL, native controller, bridge, delay budget, reset policy or library.
The default mapper and P&R flow do not silently apply this repair.

## Scope and graph proof

`tools/repair_gf180_control.py` repairs one identified ordinary combinational net
in each Control update stage. The BD NOR2 drives 125 ordinary inputs (0.707999 pF
at SS/125 C); the Click NOR4 drives 33 (0.202394 pF). Both exceed their listed
Liberty output-capacitance limits. These are real electrical loads, independent
of the difficulties of analyzing asynchronous feedback with STA.

The repair inserts a noninverting tree: a root buffer and branches of at most
eight original sink inputs. BD uses 17 BUF4 cells; Click uses one BUF2 root and
five BUF4 branches. The smaller Click root is necessary: its first BUF4-root
candidate still measured 2.583653 ns slew and was rejected. No protected native
pin is rewired and no clock is introduced.

Acceptance requires exact module/instance/driver/net/sink membership, one driver,
no module-port alias, and only the enumerated ordinary sink edits. Contracting
the added buffers must reproduce the complete original JSON, including all
other modules and protected cells. New signals cannot alias any original port,
cell connection or named net, even an unused one. Both original and repaired
Verilog are reparsed with the pinned Yosys and compared against their JSON
connectivity, independently of net numbering. Only Yosys's escaped private-name
representation and omitted empty connections are normalized. Inputs, tools and
all five Liberty files are hashed before and after execution.

## Measured result

The screen uses the same isolated mapped stage, 0.05 pF output loads, five pinned
cell corners and 0.02/2 ns input transitions before and after repair. There is no
wire RC. The following are diagnostic static results, not qualified silicon
delays: other stage electrical violations remain.

| Measurement | BD before → after | Click before → after |
| --- | ---: | ---: |
| Largest data-path maximum across the cohort | 51.492380 → 36.664134 ns | 37.777405 → 30.536030 ns |
| Largest slew on the selected net/tree | 62.469322 → 1.708843 ns | 36.462383 → 1.888956 ns |
| Added cell area | 522.4576 µm² | 171.2256 µm² |
| Added TT cell leakage, state mean | 0.0015234 µW | 0.0005038 µW |
| Remaining numerical 10 ns data-budget failures | 9/10 repaired cases | 8/10 repaired cases |

All changed source/branch nets meet their pin-only capacitance limits at all five
corners, and all selected-tree output slews are below 2 ns for both input slews.
The original driver and every original sink remain present. Logic area excluding
SRAM becomes 2.831489696 mm² BD / 3.5966947072 mm² Click for these opt-in netlists.
These small added costs are cell bookkeeping; they do not establish total power
or routed area. Firmware wake activity has not been remeasured for a timed
physical netlist.

## Timing evidence and its limits

The final 40 cases resolve all **50,400 data queries**: every one of the 315
payload D pins, both endpoint transitions, min/max, both variants, before/after,
five corners and two input slews. A fixed endpoint transition and one result per
endpoint avoid the old cross-endpoint worst-slack sampling ambiguity. Batching
was checked against all 1,260 individual baseline Click data rows and their exact
paths; values and paths agree. Missing/duplicate endpoints, reversed bounds,
nonfinite values and inconsistent source/arrival values reject.

The screen also resolves **120 request-guard queries**, targeting the actual
last DLYD output in a separate linked-design context. Keeping that intermediate
measurement endpoint out of the capture context prevents it from breaking the
longer search. The guard is unchanged. At SS/125 C with 2 ns inputs, BD data plus
the existing 8 ns setup allowance settles 26.899537 ns before the rising request
guard completes after repair, versus 12.071291 ns before. Across the complete
cohort this earlier-node margin falls to only 0.048162 ns for BD; Click's minimum
is 4.221173 ns with its 5 ns allowance. This assumes aligned stage-boundary
data/request launch. It is **not** an actual capture margin, a measured upstream
alignment, or a wire budget.

All **37,920 direct capture/ACK queries remain unresolved**: 632 per BD case and
1,264 per Click case. The queries target every actual E/CLK pin, both Click
request phases, and ACK min/max. Neither a missing result nor the earlier guard
comparison is accepted as a capture pass. Fresh isolated witnesses resolve the
request guard but not the actual capture pin or its directly connected buffer
output. No false path, created clock, reset case or manual loop cut was added to
force a result. Explicit min/max path constraints are measurement constraints.

The repaired stage still reports 309–1,253 BD and 410–1,385 Click electrical
violation rows across the cohort; these are repeated pin/report rows, not counts
of distinct nets. Numbers outside electrical limits remain diagnostic. The
unchanged 10 ns simulation allowance remains visible independently of capture
coverage; meeting it numerically does not confer physical qualification.

The next analysis must separately bound the native control chain under explicit
state assumptions: BD request guard → C-element set arc → long-hold gate → actual
capture distribution; Click request guard → phase comparator → fire gate →
actual capture distribution. Any isolated keeper feedback cut needs exact
binding and a documented state assumption. ACK, source reuse, hold, pulse,
reset/recovery and extracted min/max RC remain separate obligations. Do not add
periodic stages or waive those requirements to obtain a report.

## Verification and retained evidence

The final full Python suite passes 780 tests. After separating the numerical
data-budget field from missing capture evidence, the focused suite passes 29 tests.
The existing 81 GF180 controls also pass. RTL and budgets are unchanged, so the
merged A2b digital regression is not relabeled as a newly executed Scala run.

An independent agent reviewed the edit containment, timing query design and
results. Its material finding was an unused-input alias hole in the new verifier;
the verifier now reserves all original signal identifiers, and a negative test
reproduces that exact fault. It also required source-custody checks, independent
setup/ACK reporting, and explicit missing capture evidence. Those fixes are in.

The [evidence manifest](control-electrical-repair-evidence.json) binds the final
source, input maps, repair receipts, timing scripts/logs/results, test logs and
review record. Working evidence lives in ignored directories:

- `build/control-electrical-repair-r5/{bd,click}`: final repaired netlists and
  complete graph/Verilog proofs.
- `build/control-electrical-screen-r3/{bd,click}`: final 40-case analysis.
- Earlier `control-electrical-repair-r1`–`r4` and screen pilots: retained emitter,
  alias/graph, timeout and slew failures. The first screen's per-query constraint
  rebuilding exceeded its 110-second bound; no partial run was called a pass.

Reproduction uses fresh output directories and the exact source maps named in
the repair receipts:

```powershell
python tools/repair_gf180_control.py <original-map> <fresh-repair> --variant bd
python tools/screen_gf180_control_repair.py <original-map> <fresh-repair> <fresh-screen> --variant bd
python -m unittest discover -s tools -p test_control_electrical_repair.py
```

Repeat with `--variant click`. The target membership is deliberately specific
to this reviewed mapping; a new RTL/mapper result requires a fresh target review.
