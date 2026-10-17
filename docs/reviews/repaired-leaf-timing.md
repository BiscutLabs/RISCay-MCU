# Repaired native leaf binding

The canonical-stage and Join runners now use the original graph only to resolve
contract identities. STA reads the **complete repaired netlist**, including all
parent buffers and physical loads. No contracted or original slice supplies a
timing measurement. This fixes the earlier `CONTROL_SOURCE_WIDTH`,
`STAGE_UNDECLARED_INPUT` and `JOIN_RENDEZVOUS_WIRING` rejections without inventing
an arrival time for a repair-created hierarchy input.

The hash-validated repair proof supplies both buffer and tie inventories.
Original logical data lanes resolve to retained leaf drivers; every original
fanout receiver must still connect through the recorded noninverting buffers.
A logical input is unused only when the original instance has neither a physical
consumer nor an output alias. Constant lanes retain capture and ACK obligations.
Keeper cuts are limited to the reviewed A1 feedback arc in verified protected
AOI/NOR pairs. All four root slew combinations are annotated and read back.

## Scope of the measurements

A clock at a retained source Q is an analysis reference, not a clock added to
RTL or a measurement of that source's launch. Stage input alignment, execute RF
launch **and hold**, elapsed owner/admission composition, variation, reset and
wire RC remain open. The local hold calculation grants **zero** parent-data or
transform contamination-delay credit. Results retain the limiting ACK receiver
and distinguish internal feedback from external receivers.

Combinational ACK inputs are not valid constrained PathEnd endpoints. Their
propagated graph arrivals are reported separately from constrained data/capture
queries. Click paths retain fire, phase-clock, CLK-to-Q and actual ACK cells.
The complete Click capture/pulse/retention proof remains open.

The BD Join initial-admission context still conditions the operand's ACK
receivers. That removes timing arrivals at those input pins. The return probe
therefore observes each receiver's unique **actual live driver**, with all loads
retained, and records the driver and conditioned receiver separately. It includes
the parent 32 ns ACK guard and any intervening repair buffers. Minimum driver
arrival is conservative for earliest return; maximum driver arrival is not a
bound on receiver wire delay. This mode uses zero wire RC and must not accept
extracted/interconnect RC until that receiver-wire path is included.

## Binding and fault evidence

The first default-runner smoke cohort is TT, 0.2 ns input slew only, on
`electrical-first-current-bd-r3` and `electrical-first-current-click-r2`.

| Conditional local metric | BD execute | BD elapsed | Click execute | Click elapsed |
|---|---:|---:|---:|---:|
| Allowed input-data lag, ns | 213.051 | 240.486 | 213.727 | 242.723 |
| Hold, zero contamination credit, ns | 2.116 | 2.056 | 97.859 | 97.953 |
| ACK after latest capture, ns | 2.420 | 2.360 | 98.267 | 98.361 |

SRAM preparation also resolves in both variants, including its genuinely unused
logical input. Control Join conditional setup is at least 119.035 ns BD and
131.210 ns Click in this nominal smoke cohort. BD return-driver arrival is at
least 229.106 ns after the latest source closure. These are **not all-corner
guard margins or physical qualification**. Residual electrical violations remain.

Both elapsed variants pass five actual-tool controls: period invariance, shortened
request, early ACK, delayed capture branch and delayed repaired parent-mode
buffer. The last control perturbs one real buffer I-to-Z arc, changes exactly
220 BD / 219 Click destination lanes, and leaves capture/ACK unchanged. Existing
negative results cannot count as mutation detections. The Click static lane keeps
its capture obligation in the delayed-capture control.

Final Join controls also pass: period changes leave every result unchanged in
both variants; perturbing one actual BD parent-ACK IOPATH moves all eight return
bounds and leaves non-return paths unchanged. This is path-sensitivity evidence,
not a claim that the added-delay mutation should violate a minimum-order bound.

Evidence directories are `build/native-leaf-{bd,click}-smoke-r3`,
`build/native-leaf-{bd,click}-controls-r2`, `build/leaf-join-{bd,click}-final-r1`
and `build/leaf-join-{bd,click}-final-controls-r1`. Each final runner receipt hashes its source,
netlist, libraries, runtime, scripts, logs and parsed results. Earlier failed
binding/probe attempts are retained. Focused Python verification passes 124 tests;
the complete tools suite passes 1,016 tests. Two independent review rounds found
and closed hold-credit, proof-read custody, parent-path control and full-chip
storage/RC-validation gaps. See the [evidence manifest](repaired-leaf-timing-evidence.json).

The next full corner/slew campaigns must use the final graph after the outstanding
SRAM-clock and wide-capture repairs. This nominal binding evidence does not
replace them, RF/elapsed source composition, or extracted min/max RC checks.
