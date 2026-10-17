# Area budget for asynchronous designs

## Cost model per stage

For a bundled-data stage of width W bits:

```
area_stage ≈ W × (storage_cell + per_bit_overhead)
           + capture_tree(W)              # ≈ W/12 buffers for ≤16 loads/branch
           + controller                   # a few C-elements / gates
           + matched_delay                # one chain, sized per timing-closure.md
           + hold_fix                     # only on STA-reported paths
```

`per_bit_overhead` should be **zero** in bundled data. If your library or generator
adds a gate or buffer per bit (a "data allowance", reset gate, isolation gate),
that is usually the largest avoidable cost in the design. At 13,000+ lanes,
an AND2 plus a buffer per bit came to ~0.46 mm² in GF180, more than every SRAM
macro on the chip.

For every new stage, compute `area_stage` before writing it, and compare it with
the work the stage does. A stage that only copies data pays the whole cost for no
function.

## Reference cell footprints (GF180MCU 7-track, 5 V, from LEF)

| Cell | µm² | Use |
|---|---:|---|
| `latq_1` | 43.9 | Transparent latch: BD payload storage |
| `latrnq_1` | 48.3 | Latch with reset: control state only |
| `dffq_1` | 63.7 | Flip-flop |
| `dffrnq_1` | 74.6 | Flip-flop with reset: avoid for payload |
| `buf_1` | 13.2 | |
| `and2_1` | 17.6 | |
| `inv_1` | 8.8 | |
| `aoi222_1` | 30.7 | Common C-element building block |
| `dlya_1` / `dlyb_1` / `dlyd_1` | 24.1 / 35.1 / 74.6 | Delay cells |

Other libraries differ, so look up your own LEF `SIZE`. The ratios
(latch ≈ 0.6 × reset flop) are typical.

## Budget gates

Apply to every block and every PR:

- **Fixed overhead ratio**: (controllers + matched delays + allowances + hold fixes)
  ÷ block area. Target ≤ 15–20%. Above 30%, the architecture is too fine-grained
  or delays are mis-sized.
- **Copies**: the number of storage bits that hold a value also held elsewhere.
  Target: zero, unless each copy is justified by a named obligation.
- **Clocked storage bits**: by clock domain. These must not increase in an async
  migration step.
- **Versus a synchronous reference**: if a clocked implementation of the same
  function exists, async logic area should be within ~10–30% of it. Desynchronized
  designs reach a few percent. At 2× or more, stop and find the cause before
  adding features.
- **Physical overhead**: track the buffers added by electrical repair and CTS
  separately from mapped logic. Large repair overhead points to weak drivers,
  long nets, unbounded fanout or a sparse floorplan.

## Area levers, in typical order of payoff

1. Remove per-bit allowances and use one matched delay per stage.
2. Size matched delays per corner as a ratio (relative constraints).
3. Remove pass-through stages and clocked mirrors; merge producer/consumer.
4. Use latches without reset for payload.
5. Narrow widths to proven ranges.
6. Move bulk state to SRAM; make low-throughput datapaths serial or iterative.
7. Move rarely-executed arithmetic to firmware.
8. Physical: compact floorplan, macros near their users, adequate drive strengths.

Measure each lever with a matched comparison: same tools, same corners, same
workload, same physical settings, only one change.
