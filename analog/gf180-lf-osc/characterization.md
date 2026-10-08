# Schematic characterization, 2026-10-07

**Selected candidate: approximately 7.7 Hz and 11 nW at 3.3 V, TT, 25°C.**
These are deterministic, pre-layout SPICE results for the complete oscillator
including bias, timing devices, reset circuitry and output buffers at 20 fF load.
They are not measured silicon values or whole-MCU sleep power.
The POR generator, timer, clock tree, pads and other SoC circuitry are excluded.

The selected configuration uses seven current-starved stages, a nominal 300 MOhm
source resistor, eight series transistors per weak-buffer branch, and seven
10 um × 10 um NMOS gate capacitors. The resistor requires the 3k HRES process
option. Area and integration constraints are in the [design README](README.md).

## Results

| Measurement | TT / 3.3 V / 25°C | Range in the 55 checked cases |
| --- | ---: | ---: |
| Frequency | 7.7307 Hz | 5.7815–11.2550 Hz |
| Total VDD current | 3.366 nA | 1.483–15.048 nA |
| Total VDD power | 11.108 nW | 4.449–54.173 nW |
| First clock edge after POR release | 15.969 ms | 11.168–21.072 ms |
| Maximum 10–90% output rise time | 14.85 ns | 164.80 ns worst observed |
| Maximum 90–10% output fall time | 14.64 ns | 24.32 ns worst observed |

The TT clock period is about **129 ms**. The slowest checked period is about
173 ms. Time intervals cannot be interpreted as precise milliseconds without
revising the digital timebase and accounting for frequency variation.

Reset is an active startup state. At TT it draws approximately **63.1 uW**;
startup energy from power ramp through the first clock edge is **317 nJ** with
the specified 100 us ramp and 5 ms POR hold. Do not use reset as a low-power stop
mode. The always-on oscillator runs through retained sleep.

All 27 cases in the final nominal sweep passed. Selected comparisons:

| Source resistor | Ring stages | Buffer stack | Frequency | Power |
| --- | ---: | ---: | ---: | ---: |
| 30 MOhm | 7 | 8 | 80.713 Hz | 33.134 nW |
| 100 MOhm | 7 | 8 | 23.572 Hz | 16.740 nW |
| 300 MOhm | 5 | 8 | 9.771 Hz | 13.592 nW |
| 300 MOhm | 7 | 4 | 8.934 Hz | 13.119 nW |
| **300 MOhm** | **7** | **8** | **7.731 Hz** | **11.107 nW** |

Selection minimizes nominal supply power among this bounded set, followed by
corner checks of the winner. Every alternative has not received the full corner
sweep, so this does not prove minimum worst-case power. The larger resistor saves
about 5.6 nW against the 100 MOhm/seven-stage/eight-stack option but triples its
resistor-body area. No claim of a global minimum or final area optimum is made.

## Executed checks

- **55/55 selected-candidate SPICE cases passed:** all combinations of five MOS
  corners (`typical`, `ss`, `ff`, `fs`, `sf`), 3.0/3.3/3.6 V and −40/25/125°C;
  two additional resistor corners at nominal conditions; 1 us and 100 ms supply
  ramps; reset/restart; 100 fF load; half maximum timestep; reduced `gmin`; and
  two combined MOS/resistor/temperature/supply/load cases.
- The nine independent resistor DC checks passed for each campaign, covering
  three resistor corners and three temperatures against analytical resistance.
- The negative SPICE control was rejected as expected with reset held low.
  Its campaign exits successfully only on the expected no-start rejection.
- Ten Python measurement/generation controls passed, including truncated traces,
  wrong current sign, non-finite samples, startup-only oscillations, reset clock
  activity, a stuck clock, and an unrecognized model transformation.
- All four existing digital oscillator-model tests passed. Digital RTL and its
  4 kHz reference assumption were unchanged; Scala/strict exports were not rerun
  for this analog-only addition.

Changing the maximum timestep from 100 us to 50 us changed nominal frequency
by approximately 0.006% and power by approximately 0.10%. Reducing `gmin` tenfold
changed nominal frequency by approximately 0.011%. These are numerical checks,
not physical accuracy bounds.

Raw decks, waveforms, component checks and logs are retained under:

- `build/lf-osc-final-sweep/report.json`
- `build/lf-osc-final-pvt/report.json`
- `build/lf-osc-final-controls/report.json`

Simulator: **ngspice 42**, WSL Ubuntu. Every run starts normally from the zero
supply ramp, without `.ic`, `uic`, forced oscillation or an ideal bias current.
Power is integrated over complete settled cycles. The output load is an explicit
testbench capacitor; no external timing component is part of the oscillator.

Selected circuit SHA-256:
`bb845861cc9013376ef4a10c91e4f570ae23be495224950f406dbdfbd9994de0`

Prepared GF180 model SHA-256 for these runs:
`93e54011b0d1f75c19fbb80a3f91b6d60a5f43cc1a2cfbee5cb7b5108b1fe6fd`

Upstream revisions and original byte hashes are in [sources.json](sources.json).
The runner records the simulator, generator, characterization script, prepared
model, individual generated netlists and case parameters in its report.

## Failed exploratory approaches and remaining work

Earlier no-added-capacitance candidates failed several hot/fast cases. Adding
real MOS gate capacitors, balancing the ring with seven stages, and reducing
the buffer's input current produced the selected candidate. A very slow clock
alone was not a reliable power optimization.

The raw PDK resistor statement was incorrectly parsed by ngspice 42: an intended
10 MOhm element behaved approximately like its 70 Ohm terminal resistance. The
independent DC test exposed that error. Only the documented compatibility copy
and successful DC checks support the final results. The raw nonlinear MIM view
also caused timestep failures in exploration; the final circuit uses ordinary
MOS devices as capacitors and has no MIM instances. Failed and timed-out runs
were not counted as passes or used to select the winner.

Unverified: layout/extraction, device matching and statistical variation,
low-current leakage accuracy, resistor noise, jitter, supply interference,
brownout/recovery, arbitrary reset pulse widths, POR implementation, receiver
clock requirements, and silicon performance. Passive corners are sampled
separately plus two combined extremes, not a complete joint corner matrix.
Low-current results are especially sensitive to parasitics and leakage omitted
or imperfectly represented by schematic models. The 3.0–3.6 V simulation range
is not a qualified product operating specification.

The current MCU cannot consume this clock directly: its millisecond divider,
Gray-counter units, watchdog counts and measurement-freshness policy must be
revised together before integration. No physical macro binding, runtime trim
or calibration mechanism is claimed by this work.
