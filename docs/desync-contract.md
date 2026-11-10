# Multi-bank desynchronized MCU

The clocked RTL is the single source of truth. Generate a four-phase bundled-data
netlist from its `proc; opt` hierarchy; do not copy its implementation or use a
shared generated clock. The single-oscillator prototype is retired. Old BD and
Click remain frozen behavioral oracles. No ABI, reset rule, deadline or test
oracle changes are authorized.

## Banks and storage

The candidate map in `physical/desync/bank-map.json` has ten banks: CPU, Fabric,
Control, program port, RAM port, I2C, ADC, time, power/reset/wake and falling-edge
storage. The last bank contains the 42 opposite-edge bits; it has S as its master
phase and therefore its own S-input matched delay. Assignment is
explicit; actual combinational fan-in supplies the graph edges. The inventory
separates positive, negative and event edges and adds gate-condition dependencies
to each affected register. Generic pre-optimization bits are not mapped state bits.

Default storage is a plain master latch plus a slave with the original reset
semantics. Synchronous resets remain synchronous next-state logic; they must not
silently become asynchronous latch resets. Architectural bits count pairs once.
The existing combinational logic stays untouched and optimizable. No new payload,
bridge, retained copy, per-bit delay or native transaction owner is permitted.

Literal substitution on the pinned reference costs 1.300158x storage, above the
1.25x cap. The user chose investigation of a flop-plus-bubble exception instead
of raising the cap. Retaining the CPU's 591 mapped FFs gives a **calculated**
1.230263x storage ratio and a 1.088401x logic floor, before controllers/joins,
loaded delays, enable trees and hold fixes. It is a candidate, not an adopted
conversion or mapped desync result. No extra architectural state is proposed.

## Controller graph and initial marking

Each bank normally has semi-decoupled master/slave controllers, predecessor
C-element joins and one matched delay. Slaves initially contain valid state;
masters supply bubbles. Fig. 11 of
[Cortadella et al., TCAD 2006](https://iris.polito.it/retrieve/handle/11583/1643397/48109/paper.pdf)
is the positive-edge marked-graph template. Every data and gating dependency
needs an implemented handshake relation; timing delays do not replace causality.

`desync_graph.py --phase-aware --reachable-stop` screens data, gate and SRAM
dependencies, checking tokenless cycles, one-token safety cycles and reachable
markings. Its CPU-only contraction combines
M-close/S-open into the FF rising event and S-close/M-open into the falling event.
Only those two zero-mark local relations may contract; they become explicit FF
setup/hold/pulse obligations. Two adjacent FF banks (CPU plus Fabric) are rejected
because they create a tokenless cycle. The ten-bank abstract graph has 25,293
reachable markings; disabling `power.m-` drains every marking to one terminal
within 51 firings. All latch enables are low except power.M. This proves neither
handshake-wire rest nor correspondence with physical controllers. The screen
still reports incomplete and exits nonzero.

The standard-cell controller candidate restores the original causal condition
noted beside Fig. 12: with A=Ai, B=Ro and R=delayed Ri,
`A_next = (R & !B) | (A & (R | !B | !Ao))`. A rising request cannot advance A
until the previous B returns. The simplified `A_next = R | ...` failed under
loaded composition; an extra guessed wait is not the remedy. A and B are the
two keeper bits. M resets to (A,B)=(0,0), S to (1,0); their master/slave roles swap
in the falling bank. The CPU's two added joins reset to zero with both inputs
zero; other joins follow their graph marking. Primitive samples retain every feedback path;
listed local keeper arcs are **not** a complete STA cut set.

The CPU candidate uses that controller pair plus two ordinary C-element joins:
its master request joins upstream requests with consumer closure; its slave
acknowledge joins consumer closure with master.A. CPU FFs capture on master.A
rising. Self-dependencies become the FF aperture, not inputs to external joins.
The independent gate-return edge `cpu.fall -> falling.M+` must still be connected.
This candidate has no payload copies; gate-level correspondence is not yet proved.

The review identified obligations still outside that template:

- The falling bank's 42 bits originate in program (21), RAM (20) and power (1).
  Its local storage relation is S-to-M. SRAM capture is S, after the ordinary
  master's closure; macro access time belongs in each receiving bank's delay.
  Same-phase transparent cones and actual macro apertures remain timing checks.
- Negative slaves can be open at reset release. Resettable CEN/GWEN and `enabled`
  need defined masters or another proved release order; do not overwrite their
  reset values with undefined data. Additional master reset needs are permitted
  by the reset analysis and must be included in area.
- Work gating applies per register, including work-owned `coreReset` in the
  otherwise service-owned power bank. Controllers continue handshaking; only
  architectural slave enables are suppressed; masters keep tracking. The condition
  must remain stable across every receiving leaf's complete open phase.
  On a gate transition, falling-edge consumers use the previous enable: using
  its new value inserts a falling capture on start and drops one on stop.
  The existing `previous` register supplies that qualifier. Partitioning checks
  its actual D=enabled.Q connection, source clock, reset and opposite phases.
  Graph edges close the qualifier before use and the receiver before reuse;
  leaf-level gate timing remains open. No new copy register is authorized.
- CPU capture distribution, source-release hold, high/low pulse widths, gate
  return and output clock-to-Q bundling need checks on the real controller circuit.

## Stop, reset and external boundaries

One stop point in the power bank withholds requests during deep sleep. A persistent
stop competes with asynchronous wake through one metastability-filtered mutex.
The mutex must not be reset to terminate an active operational grant. POR, LF,
GPIO and SDA wake, including wake during stop, require explicit recovery tests.

| Remaining clock/input | Obligation |
|---|---|
| LF watchdog/timebase | Independent time and recovery while the controller graph stops; existing Gray crossing and skew bound |
| SDA event FF | Retain the pin-clocked START frontier and its SCL aperture; synchronize its result through the existing stages |
| SRAM CLK | Local port controller only; preserve falling launch/rising access order and datasheet apertures/access/pulse widths |
| GPIO and I2C synchronizers | Original stages become latch pairs; report slow-corner sampling interval and MTBF assumptions; active bus keeps sampling live |
| SPI MISO | Existing source-synchronous sampling; constrain the external ADC's data aperture |

There is no periodic service/work clock. Architectural resets and asynchronous
wake-set state still require their existing lifetimes and recovery/removal
analysis. The physical POR qualifier currently counts service cycles for 5 ms;
the generated implementation must preserve that absolute minimum.

## Timing and throughput

Relative delays: one loaded, mixed-cell matched delay per bank, sized using
`max_c(1.2 * requirement_c / cell_delay_c)` at the same corner and actual slew/load.
The 20% factor is a user allowance, not measured mismatch. Include join/controller
cost, latch setup, enable-tree spread and both phase obligations. Missing or stale
STA entries fail; simulation constants cannot determine physical counts.

Absolute checks: SRAM setup/hold/access and high/low pulses, latch/controller
minimum pulses, POR hold, mutex filter and reset recovery. Hold repair is limited
to paths STA flags. Simulation-only delays come from each bank's measured
[fastest, slowest * 1.2] envelope. No such bank envelope is published yet.

For boot, I2C, ADC and LF service require
`events/window * worst firings/event * slow-corner cycle < window`.
I2C is **400 kHz SCL**, with unchanged earliest-status tests at 3.2 and 20 MHz
reference service clocks. Cycle time is a graph property after characterization;
none is claimed from the topology screen. Zero-wire margins below 100 ps are
flagged; electrical repair precedes accepted timing and routed min/max RC follows.

## Acceptance and current boundary

The pinned clocked reference is 0.5318332992 mm² mapped, 0.5915383488 mm² after
repair/placement/CTS, 2,977 architectural bits and 0.2041777472 mm² storage.
The deterministic export fix produces 0.5315501184 mm²; refresh its physical
reference before claiming a comparison against that newer netlist.
Budgets are mapped 1.15x, repaired plus trees 1.20x, architectural bits exactly
1.00x, storage area 1.25x and control/join/delay/mutex share 5%. Only the storage
metric replacement was approved; other ceilings have not changed.

The mutex allowance is at most 0.001 mm². The experimental 28 × 35.28 µm
layout occupies 0.00098784 mm² and passes two LVS tools plus foundry geometry
checks. This is cell evidence, not a whole-chip map or accepted binding.
Top-metal access and scenario-only timing views are experimental. Distributed
min/max-RC, unresolved-reset recovery, variation and noise remain part of
qualification; see the ledger. The user-set stop/wake reliability target is
**at most 1 FIT per MCU** (one failure per billion device-hours). Qualification
must combine a justified failure model with the worst admitted arbitration rate;
finite SPICE samples do not establish it. Scenario `when` conditions
cannot prove prior quiescence or bound contention.
Registry recipes and delay policy remain unavailable until measured. Reference
CI and graph unit tests are distinct from desync acceptance. Transformation,
flow equivalence, folded next-state equivalence, full-chip area, all-corner
phase/reset timing and routed checks remain open. Do not turn a reference
self-comparison or the CPU substitution estimate into an implementation pass.
