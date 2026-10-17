# Electrical-first correction

The ordering is global electrical repair, rerun existing campaigns, RF and
elapsed composition, then extracted full-chip timing. Timing parameterization
and conservative guard lengthening proceed alongside the electrical work.
Shortening waits for the complete measured envelope. No periodic clock or
clocked pipeline is added to a native owner.

## RTL scope

Both independent implementations now accept separate Control owner/update and
elapsed owner/step timing policies through their Platform and SoC constructors.
Core execute remains independently configurable. Other native owners retain
their existing policies; this is not a claim that every hard-coded policy has
been removed.

| Guard | Previous model | Current target |
|---|---:|---:|
| Elapsed arithmetic step request, BD / Click | 11 ns | 100 ns |
| Execute request, BD / Click | 21 ns | 80 ns |
| BD Control update-to-Join source ACK | direct connection | 32 ns, both edges |

Data-path allowances, arithmetic, state layout, storage/output delays and the
existing Click acknowledgment policy remain unchanged. The 100 ns elapsed
target adds 89 ns to the previous request model, exceeding the earlier 62.3 ns
local deficit, but this is not a physical proof or a selected mismatch derate.
The mapped same-corner envelope and full upstream launch still need validation.

BD Control's additional native buffer holds the Join source beyond the update
controller's ACK. ACK rise cannot disappear before the source sees it: the
source retains REQ until the guarded ACK rises. Guarded ACK fall also delays
source reuse. The circuit uses the public ControlGate primitive and recognized
`acknowledge_guard` ID. No latest-leaf claim is made; the 32 ns target must be
checked against the actual capture tree at every corner and after routing.

Initial 200 ns and 120 ns elapsed candidates failed the unchanged accelerated
BD maintenance sleep oracle (`MAINTENANCE_STARVED_SLEEP`, zero entries). Their
logs remain in `build/electrical-first-rtl-r2.log` and `-r3.log`. The 100 ns
candidate passes that oracle. No deadline, expected sleep count, arithmetic or
functional assertion was relaxed. Review also caught an unrecognized guard ID
that randomized the initial ACK tests to 1–10 ns; those early tests do not count
as 32 ns evidence. The corrected actual-edge campaign checks both edges and an
actual-output bypass must trigger `CONTROL_ACK_RISE_EARLY`. A separate falling-
edge bypass must trigger `CONTROL_ACK_FALL_EARLY`.

## Default electrical repair and acceptance

`gf180_implement.py` runs `repair_gf180_design.py` after synthesis. OpenROAD uses
all five pinned standard-cell corners and zero pre-placement wire RC. Native
leaves and the three SRAMs are protected. Ordinary sequential cells may receive
distribution buffers, but their masters cannot change: sequential library cells
are excluded as resize replacements and graph proof independently checks them.
The SRAM TT view
supplies pin loading only; this does not qualify SRAM at five corners.

Before publishing repaired files, the flow checks original Verilog/JSON
agreement, every original cell and pin, all top ports and constants, equivalent
ordinary-cell functions at each corner, and unchanged native pin/port
partitions. Only noninverting distribution buffers, equivalent combinational
cell replacements and proved constant ties may be added. Physical
multiple drivers, cycles, unused additions and changed native feedback fail.
The actual repaired graph is used for timing; contraction is only a proof.

This OpenROAD version's hierarchical writer needs constant drivers inside their
owning modules. Yosys inserts those before OpenROAD runs, preserving every
original cell and removing unused constant aliases. Native constant boundary
ports keep their exact polarity even when no downstream leaf consumes them.
Earlier rejected runs emitted undriven `one_`/`zero_` nets or colliding tie
instance names; another attempt inserted unused alias drivers. These failures
remain under `build/default-repair-bd-r2` through `-r5`; no failed graph is an
accepted timing input. The writer also disconnects some hierarchical output
buses reused internally. Real buffers on the internal fanout of those data
outputs prevent that alias defect. They are counted in area and remain in the
timed graph. Primitive-local feedback is excluded. The first complete roundtrip
probe preserves the original graph with 890 such buffers; this is an export
control, not an accepted repaired or electrically qualified result.

The next rejected whole-chip exports exposed a second writer defect: 621 uses
of 61 escaped scalar names were emitted as ordinary bus selects. The correction
escapes only references to exact scalar declarations, rejects an ambiguous real
bus declaration, and retains the raw file and every edit offset. Full graph
proof remains mandatory. Another 199 newly inserted constant ties became
orphaned when unused input ports disappeared. Only proved added, unused ties are
removed; original cells, buffers and live ties are never deleted by this cleanup.

Native reset ports receive real parent-side buffers before global repair. This
gives OpenROAD ordinary distribution sinks without modifying protected owner
internals. Shared module definitions are edited once and every physical buffer
instance is counted. POR polarity and each native reset pin/port partition must
still match the original graph. This changes distribution delay and therefore
does not close the complete reset assertion/release envelope.

Wholly unused, constant specialized native inputs may disappear during export
(for example a C-element's absent falling operand). The proof records every
omission and verifies the original local module had no pin consumer. Dynamic
inputs, outputs, connected inputs and changes to retained ports remain errors.

A versioned receipt binds source/tool/PDK inputs, original and repaired graphs,
candidate audit, proof, repair script/log and before/after electrical reports.
The default P&R and stage/Join entry points require that receipt. A retry cannot
overwrite a previous repair attempt. Historical unrepaired results remain
readable; new campaigns cannot use them as repaired inputs.
P&R provenance v2 binds the exact receipt and revalidates it when reading or
resuming checkpoints and extracting RC. Earlier v1 P&R evidence remains
historical and cannot qualify a new run.

Stage bindings resolve cloned adapters through the receipt's original instance
paths and check each live recipe. Exact, uniquely driven tie cells can identify
constant lanes; those lanes retain capture/ACK checks. Added buffers inside
wrappers require their exact physical path in the hash-bound repair proof and
remain in the measured circuit. Original-netlist and proof bytes are checked
before parsing, frozen through the campaign and revalidated at completion.
Unexpected or missing stage inputs still fail. In particular, repair can move a
distribution branch across a stage boundary; its new input cannot be assigned an
invented arrival time simply to reuse the old standalone-stage campaign.
An expected constant protocol input may lose its tie only when recursive
inspection proves that the specialized port reaches no physical leaf input or
public output. The plan records the unused input; native recipe and whole-graph
checks still apply. A live consumer or output alias rejects the exemption.

## Digital verification

The final functional cohorts pass: 84 elapsed/SoC/firmware/sleep/reset tests,
45 Control/CRC/reset tests, six accelerated maintenance-sleep tests and five
physical-export tests. CoreSpec's independent architectural references,
fastest-memory cases and writeback bypass controls also pass. The freshly
generated complete elapsed-capture cohort passes its actual-pin negative
controls. The added ACK controls check both rising and falling edges at the
selected 32 ns policy, with separate exact-fatal bypass cases.

Both fresh strict SoC exports pass with sleep-clock background and vector
coverage: BD checks 2,628 endpoints and 648,301,320 logical mappings; Click checks
2,364 endpoints and 560,535,132 logical mappings. The final Python suite passes
968 tests. The initial strict exports retain two endpoint-binding failures and
600-second simulator wall-time limits. Endpoint aliases are now explicitly
retained; the successful runs allow 1,800 seconds of simulator wall time, with
no functional deadline, stimulus or assertion changes.

## Measured repair result

The final accepted mappings are `build/electrical-first-current-bd-r3` and
`build/electrical-first-current-click-r2`. The pre-repair reports below are
from the prepared graph immediately before OpenROAD repair, with its real
reset and hierarchy-feedback buffers already present. They are not the older
routed results and are not a matched area/power comparison.

| Electrical measure | BD before / after | Click before / after |
|---|---:|---:|
| Unique pins violating the 2 ns slew target | 68,091 / 6,240 | 65,041 / 6,503 |
| Unique nets with those violations | 14,343 / 1,591 | 13,353 / 1,662 |
| Worst reported slew | 626.481 / 9.973 ns | 634.053 / 10.073 ns |
| Capacitance violation rows | 130 / 0 | 109 / 0 |

The proof accepts 4,015 added buffers and 10,561 ordinary cell replacements in
BD; 5,573 buffers and 9,010 replacements in Click. All 55,722 BD and 61,203 Click
native leaves remain unchanged. The replacement count includes equivalent
clock-inverter-to-inverter substitutions; it is not a count of stronger drivers.
These added buffers must remain in subsequent area and leakage accounting.
The subsequent [exact area report](../gf180-estimates.md#electrical-repair-area)
includes every buffer, added tie and resizing delta: repaired logic is
3.032245 mm² BD / 3.816860 mm² Click, an increase of 0.190388 / 0.209668 mm²
over the respective original graph. Updated leakage and activity remain open.

Electrical closure is **not** achieved. The worst remaining net in each variant
drives the three SRAM clocks: its roughly 10 ns slew exceeds the loaded TT
SRAM limit of 3.1779 ns. Click also retains 8.073 ns frame-store capture and
5.699 ns I2C publication capture slew. RF arrival is about 5.041 ns in both
variants. Ordinary logic and reset-qualifier paths still have residual violations.
The 2 ns repair target is stricter than the standard-cell input table maxima,
which range from 5.2 to 15.6 ns across the five corners. The aggregate report
does not label each row's corner, so a violation of 2 ns alone neither proves
extrapolation nor establishes a valid per-corner table lookup.

## Existing-campaign rerun

Four stages per variant bind and resolve across five corners and two input
slews: **80 conditional cases** in total. Their minimum allowed data lag behind
the stage request is:

| Stage | BD | Click |
|---|---:|---:|
| Control update | 15.148 ns | 16.498 ns |
| I2C protocol update | 16.908 ns | 18.295 ns |
| Working-RAM lane 0 issue | 19.579 ns | 20.945 ns |
| Working-RAM lane 0 capture | 19.286 ns | 20.663 ns |

All measured local setup/hold/ACK metrics are nonnegative. Four actual-arc and
period controls also pass on the repaired Control stage in each variant:
short request, early ACK, delayed capture branch and unchanged analysis-period
results. These remain conditional, unextracted observations with residual
electrical violations. In particular, the BD update controller still has a
1.663 ns local ACK margin. This standalone-stage measurement excludes the new
parent-level 32 ns source-ACK guard; its full composed envelope is still open.

The **complete rerun fails**, rather than silently omitting unsupported paths.
Execute and SRAM preparation reject with `CONTROL_SOURCE_WIDTH` after unused
ports disappear from the repaired hierarchy. Elapsed rejects with
`STAGE_UNDECLARED_INPUT`: a real distribution branch now crosses the stage
boundary. Both Control Join campaigns reject with `JOIN_RENDEZVOUS_WIRING`;
both execute Join campaigns reject with `CONTROL_SOURCE_WIDTH`. Preserve the
actual buffers and parent paths when extending these bindings. No old Join
margin or old execute/elapsed measurement qualifies the new graph.

Local evidence is under `build/electrical-first-campaign-{bd,click}-r2`,
`build/electrical-first-control-{nominal,faults}-{bd,click}-r1` and
`build/electrical-first-join-r1`. The [evidence manifest](electrical-first-correction-evidence.json)
records hashes, rejected bindings, reviewed source files and exact test cohorts.

## Qualification gate

Structural acceptance and passing digital tests do not close electrical timing.
Residual ordinary/native-boundary slew and SRAM clock problems, complete reset distribution, RF and
elapsed launch composition, mismatch, pending/return histories and extracted
min/max RC remain explicit gates. The two fresh independent reviews covered
RTL handshake/parameter safety and the repair proof; their findings were fixed.
