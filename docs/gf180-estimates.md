# GF180 area, standby and wake-energy estimates

**Historical flip-flop baseline only.** The current RTL uses 2 KiB program SRAM
and 1 KiB working SRAM. The area, leakage and wake-energy results below must be
remeasured with the three pinned macros and their controllers; they are not
current SRAM estimates. The old estimator rejects unmapped SRAM rather than
silently omitting its area or power. See [SRAM integration](sram-integration.md).

2026-10-07, RTL baseline `4b5d105`. **Planning estimates, not physical signoff.**
These results precede the second review fixes (reset synchronizers, crash counter,
writeback guard, public selection cells and wider execute timing budget). They
are retained as baseline evidence; current RTL requires a fresh mapping/activity
run. In particular, wake cycle counts and protocol differences can change.
Both variants use [GF180's 7-track `mcu7t5v0` cells][cells] at 3.3 V, the full **2 KiB
program / 256-byte working flip-flop memories**, the Groundlark supervisor,
SPI ADC interface, and the existing clock/reset circuits. SRAM is not substituted.

The whole-MCU differences are small: four-phase has approximately 0.4% less
estimated cell area, while these representative wakes take the same number of
service cycles. That difference is below the uncertainty from unmapped async
cells, clock distribution, placement and switching activity. **These estimates
do not establish a power winner between BD and Click.**

## Results

| Quantity | Four-phase BD | Two-phase Click |
| --- | ---: | ---: |
| Mapped ordinary digital cell area, including reset sequencer | 2.491 mm² | 2.486 mm² |
| Async storage/control equivalent allowance | 0.091–0.104 mm² | 0.107–0.122 mm² |
| Total digital cell area before placement | **2.581–2.595 mm²** | **2.593–2.607 mm²** |
| Planning core footprint including analog, whitespace and implementation allowance | **4.97–7.59 mm²** | **4.99–7.62 mm²** |
| Illustrative die with a 350 µm peripheral pad band | 9.17–12.63 mm² | 9.20–12.68 mm² |
| Digital retention leakage, TT / 25°C / 3.3 V, before implementation allowance | 6.30–8.93 µW | 6.33–9.01 µW |
| Retained standby including analog and implementation allowance, excluding pads | **14.28–18.51 µW** | **14.31–18.61 µW** |
| Corresponding nominal standby current | **4.33–5.61 µA** | **4.34–5.64 µA** |
| Maintenance wake energy | **0.050–0.103 µJ** | **0.050–0.103 µJ** |
| One battery-sampling wake energy | **1.069–2.263 µJ** | **1.069–2.262 µJ** |
| Defined 43-instruction firmware wake energy | **2.769–5.859 µJ** | **2.775–5.864 µJ** |

The core footprint is not a placed result; the die number is a pad-ring geometry
scenario, not an assigned package or tapeout outline. Nominal power and energy
rows use TT / 25°C / 3.3 V. Wake energy is incremental dynamic energy; steady
leakage and analog bias are accounted separately in standby.

Standby here means both memories retained, the fast source stopped, and the LF
source/watchdog/supply monitor alive, **between maintenance or sampling bursts**.
Pad/ESD leakage, the external ADC, battery divider, board regulators, I2C pull-ups,
external pin loading and the Pi are excluded. There is not yet a complete-chip
standby guarantee. Internal trace/commit logic is conservatively retained for
sizing; those wide simulation outputs are not proposed package pins.

### Temperature matters more than the protocol

| Digital leakage scenario, same cell inventory | Four-phase BD | Click |
| --- | ---: | ---: |
| SS / −40°C / 3.0 V | 5.07–6.26 µW | 5.09–6.33 µW |
| TT / 25°C / 3.3 V | 6.30–8.93 µW | 6.33–9.01 µW |
| FF / 125°C / 3.6 V | **253–571 µW** | **256–580 µW** |

Including implementation allowance and a conservative 14.98 µW analog corner
budget gives **0.293–0.729 mW BD** and **0.296–0.740 mW Click** at the hot/fast
planning point: approximately 81–203 µA and 82–206 µA at 3.6 V. The analog budget
combines separate campaign extrema; it is not a jointly simulated full-chip
corner. Do not extrapolate the room-temperature microamp result to 125°C.

### Average power with periodic wakes

The default 1000 nominal-ms sample period rounds to eight LF ticks: approximately
1.035 s at 7.7307 Hz, or 0.966 samples/s. Every intervening LF tick still wakes
the service island briefly for timekeeping and permanent supervision.

| Nominal workload, excluding pads and external devices | Four-phase BD | Click |
| --- | ---: | ---: |
| Permanent supervisor, no application, default periodic battery sampling | 15.65–21.39 µW | 15.68–21.50 µW |
| Same, plus the defined firmware burst every eight ticks | 18.28–26.96 µW | 18.31–27.06 µW |

For a different schedule, use `Pavg = Pstandby + sum(wake_rate × wake_energy)`.
Count a sampling/firmware wake in place of its maintenance wake, not in addition
to another maintenance wake at the same instant. These examples use separate
sample and firmware bursts, as in the fixture. Coincident work needs a combined
activity measurement. Finite sleep leases and watchdog policy still apply.

## How the estimate was made

### Ordinary logic and memory

`PhysicalEstimateSpec` emits and runs both native SoCs with full memory capacities
and the same **enabled estimate-only** `PowerPolicy`. The default shipping
emitters remain disabled. Enabled policy values are an area/activity fixture,
not qualified board/battery settings. Sizing a disabled policy would allow
constant propagation to remove useful permanent-supervisor logic.

sv2v 0.0.13 converts the emitted packed SystemVerilog arrays. Yosys 0.33 and ABC
map combinational logic and ordinary sequential cells to the actual GF180 TT
Liberty library. The production 100,000-cycle reset sequencer is mapped separately
and included. The model checks that all **16,384 program and 2,048 RAM bits**
remain distinct flip-flop outputs; unidentified digital cells or clock domains
fail estimation. There are 19,922 mapped work-clock flip-flops in either variant,
616/618 fast-frontier/reset flip-flops, 78 LF flip-flops, and one SDA event flop.

No placement, routing, CTS, extracted parasitics or timing closure was run.
ABC's area-oriented mapping has no assertion of a 12 MHz timing guarantee.

### Async boundaries

Atomic chisel-async primitives remain **black boxes** during ordinary synthesis;
their simulation delays are not synthesized into gates. The estimator then adds
explicit equivalent costs:

- Closing latches: `latrnq_1` per bit, plus reset/enable polarity inverters.
- Event/phase registers: `dffrnq_1` or `dffsnq_1` per bit, reset polarity, and
  phase feedback inversion. The architectural register bank is counted once.
- Logic/reset gates: corresponding ordinary gate equivalents, counted separately.
- Unimplemented C-elements: **6–12 NAND2 equivalents each**, plus input polarity
  equivalents. There are 21 in BD and two in Click. This is a budgeting assumption,
  not an implementation or a characterized size range.
- Scalar guard/delay paths: **0–64 buffer equivalents per path**, across 14 BD
  and 17 Click paths. This is sensitivity analysis, not conversion of model fs
  into physical delay. Wide modeled data-delay paths do not receive duplicate
  buffer chains on top of their mapped data logic.

Unknown primitives fail instead of receiving zero area. Passive timing markers
and simulation guards have no physical area. These allowances do not resolve
C-element implementation, hazards, pulse widths, reset recovery, bundled-data
constraints, or delay matching. Even 64 buffers may be insufficient for a
particular path; the chosen interval is not a qualification bound.

### Analog and floorplan allowances

Existing passing schematic campaigns provide nominal currents:

| Shared circuit | Nominal standby contribution |
| --- | ---: |
| Supply monitor | 2.2244 µA / 7.3406 µW |
| LF oscillator | 3.366 nA / 11.108 nW |
| Stopped fast oscillator | 0.0746 nA / 0.246 nW |

Their sum is **7.3519 µW**. The fast oscillator's nominal active current is
57.2905 µA at the characterized 100 fF load. Its incremental burst energy is
included; the digital clock load is charged separately. The LF digital counter's
clock contribution is only approximately 0.18 nW at 7.7307 Hz and is below the
report's rounded planning allowance. No analog circuit was changed or re-simulated.

Resistor bodies in the checked netlists occupy 0.09544 mm² (LF), 0.03754 mm²
(monitor) and 0.000381 mm² (fast source). At 1 µm width plus 0.4 µm spacing, ideal
packed strip areas are 0.13361, 0.05256 and 0.000533 mm². Turns, terminals, large
resistor segmentation, wells/guard rings, MOS capacitors, PNPs and routing still
need layout. Planning macro allowances are **0.16–0.25 / 0.07–0.12 / 0.003–0.01
mm²**, respectively. These are engineering allowances, not extracted areas.
The design retains its [HRES process-option requirement][hres].

Core footprint is `(cell area × 1.10..1.25) / 0.60..0.45 + analog area`.
The 10–25% allowance is for physical implementation overhead; utilization covers
placement whitespace. Neither establishes routability. Nominal digital leakage
uses the same 10–25% extra-cell allowance. The die example wraps a square core
with 50 µm core-to-pad clearance plus 350 µm pad depth on each side. The installed
GF180 `bi_t` pad LEF is 75 × 350 µm. Package/test/power pad choices, seal ring and
scribe margin remain unresolved; changing the pad architecture changes this number.

### Leakage and wake-energy calculation

The three [GF180 library corners][corners] use explicit **µW** leakage units.
The estimator sums per-cell state minima and maxima. These are conservative
independent state envelopes, not a measured RAM image distribution or a
statistical yield interval. The optional state-mean result in the JSON is a
uniform mean over listed conditions, not a measured standby state.

The activity fixture runs at 12 MHz service frequency and nominal LF timing,
using the native executable primitive models. Measurement begins after initial
boot; reset-hold/startup are accelerated only before measurement. The supervisor
remains in OFF/restart qualification during the observation interval. RUN,
SHUTDOWN transitions, uploads and real host telemetry traffic are not measured.

| Measured wake | Fast edges | Work-clock edges | Retired application instructions |
| --- | ---: | ---: | ---: |
| Maintenance | 20 | 8 | 0 |
| SPI battery acquisition and serial scaling | 183 | 181 | 0 |
| Firmware deadline wake | 470 | 468 | 43 |

Both variants give the same counts. The firmware acknowledges consumed events,
reads GPIO, executes 32 integer additions, stores a RAM word, programs its next
deadline, renews its lease, issues the keyed watchdog kick and blocks on WAIT.
Observers also count native storage bit-events: per firmware burst BD has 1,184
event-register captures and 37,944 latch reopenings; Click has 39,128 event-register
captures and 306 phase toggles. These are bit-events, not instructions.

For each mapped clock domain, a cycle costs the sum of Liberty clock-pin
`rise_power + fall_power` at 0.1 ns slew, plus **Cpin × V²**. Units are
`mW × ns = pJ`, and `pF × V² = pJ`. Conditional internal energies are averaged
over listed conditions. Extra data-dependent energy is kept in a separate
allowance, using 0.01 pF representative output load. The work domain costs
**4.964 nJ per cycle** before allowances, of which the two memory banks alone
account for approximately **4.546 nJ (92%)**. Clock stopping retains the flops;
their existing write-enable muxes do not stop their clocks during an active wake.

The wake range applies **1.10–1.50×** to clock/storage energy for distribution,
slew and physical uncertainty, plus a **1–20% full-cycle activity** scenario for
data/combinational internal energy and input-capacitance loading. This activity
includes conservative reset/data-arc budgeting; it is not measured gate-level
toggle coverage. Negative internal-energy entries are clamped to zero for the
allowance. The resulting range is an engineering scenario, **not a proven upper
or lower bound**. Routing glitches, actual loads and slow paths can fall outside it.

The source model uses 64 ns startup, the largest previously observed schematic
startup. A 100 µs startup at nominal active current adds approximately **19 nJ
per wake**. Cold power-up and firmware upload are separate workloads. The LF
oscillator is not reset on these wakes, so its cold-start energy is not charged
again. The native model counts do not establish real silicon throughput.

## Evidence, reproduction and next decision

Commands and pinned input hashes are in [build and test](build-and-test.md#gf180-estimation)
and [gf180-estimate-inputs.json](../tools/gf180-estimate-inputs.json). Raw exports,
mapping logs/netlists, observer logs and `report.json` remain in ignored
`build/gf180-estimate/`. Both full-capacity simulation tests and ten independent
estimator controls passed. The controls include unit conversions/interpolation,
nested Liberty pins, empty libraries, missing/zero activity, changed instruction
counts, unknown primitives, unmapped cells and changed input hashes. Earlier header-only-library and
testbench observer attempts failed; only the complete passing runs support these
numbers. Existing functional regressions and strict exports from `4b5d105` remain
the RTL baseline; this work changes no production RTL or analog netlist.

The largest actionable energy reduction is **write-qualified clock gating of the
flip-flop memory banks**, preserving the selected memory technology/capacity.
It can avoid clocking 18,432 retained bits on reads and maintenance. The area
tradeoff and gating timing need their own implementation and tests. Supply-monitor
bias is the next shared standby-power target. Neither change is included here.
Protocol selection should wait for characterized async cells and a matched
placed/extracted workload comparison; the present small BD/Click difference is
not enough to justify choosing one.

[cells]: https://github.com/google/globalfoundries-pdk-libs-gf180mcu_fd_sc_mcu7t5v0
[corners]: https://gf180mcu-pdk.readthedocs.io/en/latest/digital/standard_cells/gf180mcu_fd_sc_mcu7t5v0/spec/corners.html
[hres]: https://gf180mcu-pdk.readthedocs.io/en/latest/physical_verification/design_manual/drm_10_03.html
