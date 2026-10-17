# Repair efficiency and retained electrical failures

Status: the matched density comparison, initial slew-policy experiment and failure classification are complete;
electrical closure remains open. The density runs use the same PR9 RTL/mapping,
patched OpenROAD executable, 3,250 µm square outline, macro positions and corrected
periodic CTS flow. Only placement density differs. The default remains 0.50;
neither experiment authorizes a timing or power claim.

## Density 0.60 versus 0.70

OpenROAD reported cell area includes the three SRAMs; it is not die area.

| Variant / density | Floorplan, mm² | After placement repair | After CTS | After global-route repair |
| --- | ---: | ---: | ---: | ---: |
| BD / 0.60 | 3.792616 | 4.096270 | 4.163631 | 4.225286 |
| BD / 0.70 | 3.792616 | 4.089726 | 4.154590 | 4.223451 |
| Click / 0.60 | 4.576884 | 4.895337 | 4.963363 | 5.021924 |
| Click / 0.70 | 4.576884 | 4.883879 | 4.948242 | 5.019961 |

Raising density saves only 0.001835 mm² BD and 0.001963 mm² Click at this checkpoint.
It increases slow/hot violating-net counts. Use 0.60 for the next repair experiment;
density alone has not solved repair cost. These results still use the existing
blanket slew policy. The separate corner-specific policy experiment must be
evaluated before integrating it into placement repair.

The new CTS implementation includes work-clock branches previously skipped.
Its extra physical cells must remain in area and later energy accounting. The
old incomplete CTS run is not a matched baseline for attributing density savings.
All four construction/graph proofs pass; CTS latency-balancing warnings, pulse
width, skew and async timing remain unresolved.

## Corner-specific slew policy: first matched experiment

An isolated pre-placement experiment compares the blanket 2 ns repair target
with ordinary-logic limits of 80% of each corner's Liberty limit. Native control,
capture, reset and ACK networks, plus top-level boundaries, retain 2 ns. The
ordinary limits are 4.16, 5.92, 6.88, 8.80 and 12.48 ns for FF-cold, FF-hot, TT,
SS-cold and SS-hot respectively. No timing table, capacitance limit or native
primitive is changed. Macro limits remain independent.

| Variant | Blanket repair: logic area, mm² | Split repair: logic area, mm² | Difference |
| --- | ---: | ---: | ---: |
| BD | 3.040749 | 3.041612 | +0.000863 |
| Click | 3.823964 | 3.824809 | +0.000845 |

These totals count **every physical standard cell in OpenDB**, including orphan
constant cells that the connectivity proof may discard. The three SRAMs add
0.628201 mm² in either variant. They are zero-wire, pre-placement results and
must not be compared directly with the placed-area table above. The policy has
not demonstrated an area saving at this checkpoint and is **not the default**.
A wire-dependent comparison remains necessary before integration.

Both candidates are evaluated under the same split policy in fresh OpenROAD
processes. Residual slew-row counts are identical between candidates:

| Corner | BD rows | Click rows |
| --- | ---: | ---: |
| FF-cold | 0 | 11 |
| FF-hot | 71 | 57 |
| TT | 80 | 57 |
| SS-cold | 95 | 84 |
| SS-hot | 109 | 230 |

All retained rows belong to native/boundary networks; the worst SS-hot slew is
5.041401 ns BD and 8.072802 ns Click. No capacitance violations are reported in
these pre-placement candidates. This does not supersede the routed violations.

The experiment uses numeric-only Liberty limit views, exact native-role pin
classification, two bounded targeted native-repair passes, and separate ordinary
and native reporting contexts. Each reporting context is repeated in a fresh
process and must reproduce byte-identical reports. Cross-context rows must agree
on measured values. Whole-graph/native-pin proofs and an independent
OpenDB-to-Verilog leaf-graph comparison pass for all four candidates. An actual
loaded-net control proves targeted repair changes the ordinary parent driver;
a no-repair mutation fails with its exact diagnostic. It does not claim every
protected net can be repaired.

Evidence: `build/corner-slew-{bd,click}-{baseline,split}-r6`,
`build/slew-target-controls-r4`, and the compact manifest below. Earlier failed
r1–r5 attempts remain retained. In particular, optimizer-resident and reloaded
STA state once disagreed by 0.000371 ns; no numerical tolerance was introduced.
The accepted check instead requires repeatable fresh-state reports and retains
resident-versus-reloaded differences separately. Twelve policy tests and the
net-classification fixture pass. Physical timing qualification remains open.

## Remaining failures, grouped by actual net

The SS / 125°C / 3.0 V reports contain:

| Variant / density | Slew rows | Unique nets | Locked native nets | Resizer no-progress nets | Other logic/clock nets | Worst slew, ns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BD / 0.60 | 5,563 | 1,244 | 678 | 145 | 421 | 13.907333 |
| BD / 0.70 | 6,011 | 1,563 | 592 | 149 | 822 | 14.116127 |
| Click / 0.60 | 7,054 | 1,571 | 1,044 | 173 | 354 | 16.054615 |
| Click / 0.70 | 7,075 | 1,847 | 930 | 182 | 735 | 15.113087 |

Rows sharing a net are counted once in the net columns. Locked native nets include
primitive-internal nets as well as boundaries; a parent buffer cannot repair every
member of that group. The classifier resolves exact OpenDB pin/net identities,
including escaped CTS names, and rejects ambiguous or unknown report pins. A
no-progress warning counts only when its driver still drives that same final net;
warnings about changed intermediate segments remain explicitly recorded.

BD's worst driver remains the I2C observation register driving `sdaLow`.
Click's new worst driver is an ordinary `oai31_1` in program return on a locked
native-input net; its SDA driver reaches 13.054447 ns at density 0.60. The old
13.9/12.2 ns extrema must not be reused for these new placements. Click / 0.60
also has **one capacitance violation** at slow/hot; all other corner/density
capacitance reports are empty. Every five-corner report is retained, including
violations at fast corners.

Next remedies are explicit parent drivers at legal native boundaries, reviewed
primitive recipes for internal loads, and ordinary-driver sizing for unresolved
repair segments. Preserve graph/native-pin proofs, the 2 ns native envelope and
the 2.5 ns EventRegister capture budget. Successful report classification is not
successful repair.

Evidence: `build/cts-covered-{bd,click}-density{60,70}-r1`, with each run's
`electrical-groups-r2.json`, per-corner reports, graph proofs and checkpoints.
The [compact manifest](repair-efficiency-evidence.json) binds these results.
Reproduce classification after a hash-valid place/global checkpoint:

```text
python tools/report_electrical_groups.py <mapping> <pnr> <new-report.json> --stage global
```
