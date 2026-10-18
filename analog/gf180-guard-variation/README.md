# GF180 guard/logic variation screen

This experiment compares four series `dlyd_1` cells with a sensitized twelve-gate
logic path (three NAND2/NOR2/AOI21/inverter groups). It uses the actual pinned
GF180 7-track transistor cell netlists and PDK statistical models, without
inventing a transistor sigma or perturbing Liberty delays. The logic path has
5 fF per stage; both endpoints have an explicit 20 fF load and share a 1 ns input
edge. These are representative schematic loads, not extracted MCU loads.

Five PVT contexts use local mismatch: TT 3.3 V/25 C, FF 3.6 V/-40 and 125 C,
SS 3.0 V/-40 and 125 C. A sixth uses the PDK's statistical global-process model
plus local mismatch at 3.3 V/25 C. Global draws are shared between the paths;
individual transistors retain their own mismatch draws. The PDK's `mc_skew=3`
is left unchanged. The static corners do not add a second global process draw.

For each context, normalize the logic/guard delay ratio against a run of that
same model with variation disabled. Check both rising and falling transitions
and both tails: `max(max(ratio), 1/min(ratio)) <= 1.2/0.8`. This screens the
project's 20% two-sided engineering derate; the independent 2 ns stage residual
is not part of this ratio experiment. Measure only using ngspice `meas` commands.

```text
python analog/gf180-guard-variation/characterize.py --samples 32 --output build/guard-mismatch
```

Run where Python and ngspice are available; `--ngspice` and `--pdk` override their
locations. No WSL distribution is hard-coded. The PDK cell/model hashes must
match `physical/gf180/pdk-lock.json`. Generated decks, full logs and summary stay
in the output directory; one receipt hashes the models, tool and results.

Controls require disabled variation to be seed-independent, enabled variation
to vary, and a repeated seed to reproduce. Each context repeats seed 1 at half
the 20 ps timestep; every delay must agree within 1%. Missing, nonfinite or
nonpositive measurements fail. Python controls also reject either ratio tail
outside the proposed derate. The first 100 ps pilot failed convergence and is
retained as `build/guard-mismatch-pilot-r1`.

## Recorded screen

`build/guard-mismatch-r3/receipt.json` passes with ngspice 42: 32 seeds in each
of six contexts, 192 statistical runs, plus six baselines and eight controls.
Every context passes the 20/10 ps comparison; the largest delay change is
0.1741%. The earlier r2 run used one-tail acceptance and is superseded by r3.

| Context | Minimum normalized logic/guard ratio | Maximum ratio |
| --- | ---: | ---: |
| TT, local mismatch | 0.988861 | 1.012161 |
| FF cold, local mismatch | 0.988281 | 1.011322 |
| FF hot, local mismatch | 0.989145 | 1.011869 |
| SS cold, local mismatch | 0.988095 | 1.014198 |
| SS hot, local mismatch | 0.988264 | 1.013540 |
| Statistical global + local, 3.3 V/25 C | 0.952570 | 1.046010 |

The worst observed ratio in either direction is **1.049791**, inside the
**1.5** two-sided envelope. Its algebraic symmetric derate is 2.4291%, but that
is only a maximum over this small sample and representative circuit. **Keep the
20% policy and 2 ns residual.** This screen provides a model-based sanity check,
not evidence that a 2.43% production derate would be safe.

This is a small schematic screen. It is not a statistical yield bound, foundry
OCV recommendation, validation of every MCU cone, or a replacement for routed
hold/setup. It omits layout gradients, supply noise and wire RC. Passing it does
not authorize reducing the 20% derate or skipping any stage's physical check.
The circuit and model files remain external PDK assets with their original
licenses; this repository stores only the experiment and source lock.
