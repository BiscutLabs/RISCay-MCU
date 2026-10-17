# GF180 area, standby and wake-energy estimates

The [matched service comparison](gf180-matched-comparison.md) supersedes the
cross-method comparisons below. Its mapped area/activity and completed P&R runs
are independently audited. The subsequent corrective work targets redundant
storage and clocked coordination while preserving native BD/Click; see the
[migration checklist](async-soc-migration.md). Physical timing remains unqualified.

## Electrical repair area

These are totals over every physical leaf in the accepted electrical-first maps
(`bounded-distribution-bd-r2` and `-click-r2`, RTL at the merged PR #8 tree,
with bounded native trees and three exclusive SRAM clock drivers).
The comparison is the original and repaired graph of **the same mapping**, not
the earlier A2b RTL. Pinned LEF dimensions supply physical cell footprints.
SRAM's three unchanged macros occupy **0.4662406590 mm²**; their distinct
Liberty area fields sum to 0.6282008304 mm². Both totals are reported explicitly.
Standard-cell areas agree between the two views.

| Area metric (mm²) | BD | Click |
|---|---:|---:|
| LEF footprint before repair, including SRAM | 3.3146048574 | 4.0794827838 |
| LEF footprint after repair, including SRAM | 3.5052426110 | 4.2894580542 |
| Liberty area sum before repair, including SRAM | 3.4765650288 | 4.2414429552 |
| Liberty area sum after repair, including SRAM | 3.6672027824 | 4.4514182256 |
| Before repair, excluding SRAM | 2.8483641984 | 3.6132421248 |
| After repair, excluding SRAM | 3.0390019520 | 3.8232173952 |
| Repair increase | **0.1906377536** | **0.2099752704** |
| Added native-reset distribution buffers | 0.0153707904 | 0.0187953024 |
| Three exclusive SRAM clock drivers | 0.0002502528 | 0.0002502528 |
| Added hierarchy-writer feedback buffers | 0.0117223680 | 0.0291873792 |
| Other OpenROAD buffers | 0.1261888768 | 0.1239366016 |
| Added constant ties | 0.0017034752 | 0.0014839552 |
| Net change from equivalent ordinary-cell resizing | 0.0354019904 | 0.0363217792 |

The buffer counts are 1,167/1,427 reset, 890/2,216 writer workaround, and
1,958/1,931 other OpenROAD buffers (BD/Click), plus three SRAM clock drivers each.
The bounded-tree/clock-driver update increases repaired logic area by
0.0067568256 / 0.0063572992 mm² relative to the previous electrical-first maps.
Exact accounting reconciles
`after - before = added cells + net resizing`; no workaround cell is hidden.
Fixing the writer or proving a flat-netlist repair could remove the workaround
cost, at most the currently listed 0.0117/0.0292 mm² before any replacement
distribution. It would not eliminate most of the repair cost. Neither alternative
has yet passed the required graph and roundtrip proof.

Reproduce with `python tools/report_repair_area.py <mapping> <new-output.json>`
and the configured physical-tool environment. The report validates the complete
repair receipt, records hashes and inventories every leaf. Evidence is
`build/bounded-area-bd-r1.json` and `build/bounded-area-click-r1.json`.
The previous electrical-first reports remain in `build/repair-area-{bd,click}-r2.json`.
Independent review caught the original Liberty/LEF naming error; the earlier
`repair-area-*-r1` reports remain as superseded accounting. Seven focused tests cover distinct
SRAM views, hierarchical leaves, resizing/additions, missing areas and overlapping
or empty named inventories.
These are cell totals before placement, excluding routing, fillers, analog and
pads. They do not establish leakage, wake energy or timing closure. The older
activity and leakage tables below do **not** describe these repaired maps.

## Earlier A2b comparison

The A2b retained-loader-metadata comparison against accepted C1e1 `64e6211`
uses the same pinned mapper, macros, native bindings and five-corner cost
method. Acceptance: **digitally verified; matched cost recorded; physical timing open**. Logic area excluding SRAM is
**2.8309672384 / 3.5965234816 mm²** (BD / Click); the measured area
changes are **-1.1045% / -0.9128%**.
The mapped work-clock inventory falls from 4,068 to 4,009 storage-cell inputs in BD and from 4,119 to 4,060 in Click. Pin-only clock capacitance falls from 14.378128 to 14.183811 pF and from 14.549554 to 14.355237 pF, respectively. The complete fanout inventory reports 43 to 43 BD and 46 to 42 Click nets exceeding a listed pin-capacitance limit; wire RC, slew and the full capture/hold aperture remain unqualified. All 27 ordinal wake windows per variant remain unchanged; the 43-instruction firmware wakes still use 3,255 BD / 3,160 Click work-clock edges.

| A2b listed-state leakage, including SRAM | BD (µW) | Click (µW) |
| --- | ---: | ---: |
| TT / 25°C / 3.3 V | 7.496075–9.710117 | 8.961381–11.964312 |
| SS / -40°C / 3.0 V | 6.102031–7.702081 | 7.294739–9.488268 |
| SS / 125°C / 3.0 V | 44.400154–48.592716 | 48.659267–54.434697 |
| FF / -40°C / 3.6 V | 8.881997–11.142658 | 10.608502–13.548919 |
| FF / 125°C / 3.6 V | 250.992944–557.391048 | 320.157194–653.981167 |

These per-cell listed-state envelopes are not reachable deep-sleep
measurements or complete silicon power bounds. Analog, pads, clock/reset
distribution and routed overhead remain excluded. All observed increases
and timing failures are retained; see [the A2b report](reviews/loader-metadata-a2b-completion.md).

The prior [C1e1 request-receipt measurement](application-reset-boundary.md#c1e1-retained-cpu-request-receipt)
compares against the accepted C1f maps using the same mapper, assets, policies
and five-corner accounting. Logic area falls **0.2404% BD / 0.2999% Click** to
**2.862584704 / 3.629653440 mm²**, excluding SRAM. The complete mapped hierarchy
contains **103,349 / 105,247** leaves, including the unchanged three SRAMs and
**56,276 / 61,661** preserved native cells. The four deleted request payload
objects total 70 periodic bits per variant; all nine receipt control/reset bits and
all native storage remain. Service storage clock-pin load falls **0.234220 pF**
per variant, to **4.193681 / 4.207095 pF**. Work-clock load stays **14.378128 /
14.549554 pF**. All 27 ordinal wake windows are unchanged, including both
43-instruction firmware wakes at **3,255 / 3,160 work edges**.

| C1e1 listed-state leakage, including SRAM | BD (µW) | Click (µW) |
| --- | ---: | ---: |
| TT / 25°C / 3.3 V | 7.577419–9.818140 | 9.043886–12.090826 |
| SS / -40°C / 3.0 V | 6.168063–7.787103 | 7.361771–9.587289 |
| SS / 125°C / 3.0 V | 44.951562–49.193714 | 49.161935–55.008372 |
| FF / -40°C / 3.6 V | 8.978283–11.266171 | 10.706138–13.690175 |
| FF / 125°C / 3.6 V | 253.568210–563.763014 | 323.102086–660.434374 |

Both ends decrease at every corner. These independent per-cell listed-state
envelopes are not reachable deep-sleep measurements or complete silicon bounds.
Analog, pads, clock/reset distribution and routed implementation overhead are
not included. The receiving-aperture results and unproved native/mask/clock/RC
obligations remain explicit in the request contract; no timing or energy
qualification follows from these cost reductions. Evidence is retained under
`build/async-quiescing-receipt-measurement-r3/`.

The prior [C1f saved-address measurement](sram-integration.md#c1f-saved-address-narrowing)
uses A5b `67b282cf` and the same mapper/assets/policies and five-corner accounting.
Logic area changes **-0.1878% BD / -0.0782% Click**, to
**2.869484 / 3.640572 mm²** excluding SRAM. TT listed-state
leakage including SRAM becomes **7.595104–9.845576 / 9.071659–12.132237 µW**.
Click FF125 high listed-state leakage increases **0.231845076 µW**
from ordinary-logic cell composition (low changes -0.277877088 µW).
Periodic RTL loses 43 bits per variant; native storage, ABI and macro topology
remain unchanged. Of 27 ordinal windows per variant, **0 BD /
0 Click** change; all values remain recorded. Bounded
controller timing reports violations in **20/20**
cases and missing coverage in **20/20**. Real native
aperture, clock/reset distribution, route RC, SRAM and A7 qualification remain
open. Setup timing worsens: largest matched endpoint slack changes are
**-17.39656 ns BD / -21.38074 ns Click**
at SS125; hold minima remain unchanged. These are unplaced estimates, not
physical timing acceptance, deep-sleep power or wake energy.

The prior [A5b addressed-byte measurement](native-i2c-byte-store-contract.md#matched-cost)
uses the same mapper and five-corner accounting as C1d. Logic area falls
**1.9160% BD / 1.5153% Click**, to **2.874882 / 3.643422 mm²** excluding SRAM.
TT listed-state leakage including SRAM becomes **7.607764–9.867172 /
9.079021–12.144499 µW**. Native payload storage loses 513 bits per variant;
periodic state, periodic clock-pin loads and all 27 matched wake windows remain unchanged.
Functional, frame-control and strict export checks pass. The byte-write
transform exceeds its 10 ns allowance at slow corners, and the changed upstream
transform fails at TT and both SS corners. Relative setup/hold screens remain
conditional. These are pre-layout estimates, not measured deep-sleep power
or wake energy.

The prior [C1d SPI comparison](spi-player-contract.md#matched-cost)
uses the same mapper and five-corner accounting against `a8c0300`. Logic area
falls **0.2730% BD / 0.3012% Click**, to **2.931040 / 3.699481 mm²** excluding
SRAM. TT listed-state leakage including SRAM becomes **7.752528–10.033946 /
9.222217–12.361046 µW**. Each variant loses 90 periodic bits and 0.290708 pF
of mapped storage clock-pin load. All 27 matched wake windows remain unchanged.
Functional, actual-wiring and strict export checks pass. Local selected
setup/hold paths pass, while slew and capacitance failures remain explicit.
These figures do not update P&R or measure reachable deep-sleep power or wake energy.

The prior [A5a observation comparison](native-area-reduction.md#a5a-native-i2c-observation-projection)
uses the same mapper and five-corner accounting against `5e1406b`. Logic area
falls **1.2155% BD / 1.0008% Click**, to **2.939063 / 3.710656 mm²** excluding
SRAM. TT listed-state leakage including SRAM becomes **7.772042–10.062488 /
9.252447–12.399941 µW**. Periodic storage and clock-pin loads are unchanged.
All 27 matched wake windows per variant are unchanged, including 43-instruction
firmware wakes at **3,255 / 3,160 work-clock edges**. Functional, strict export
and actual-pin mutation controls pass. Complete publication/capture/reset
timing remains unqualified. These figures do not
update P&R or measure reachable deep-sleep power or wake energy.

The prior [A2a CRC comparison](native-area-reduction.md#a2a-narrow-whole-word-crc-feedback)
uses the same mapper and five-corner accounting against `7bb7b71`. Logic area
falls **4.0985% BD / 4.2730% Click**, to **2.975227 / 3.748168 mm²** excluding
SRAM. TT listed-state leakage including SRAM becomes **7.864666–10.202253 /
9.346913–12.543369 µW**. Periodic storage, clock-pin loads and all 27 matched
wake windows per variant remain unchanged; firmware wakes retire 43 instructions
in **3,255 / 3,160 work-clock edges**. Functional, mutation and strict export
checks pass. Measured CRC transform timing still fails its data allowance;
complete capture/reset and routed qualification remain open. These figures do
not update P&R or measure reachable deep-sleep power or wake energy.

The prior [A1b elapsed-loop comparison](native-area-reduction.md#a1b-bounded-native-elapsed-loop)
uses the same mapper and five-corner accounting against `0f6e26f`. Logic area
falls **5.5516% BD / 5.4050% Click**, to **3.102377 / 3.915477 mm²** excluding
SRAM. TT listed-state leakage including SRAM becomes **8.176051–10.596532 /
9.763012–13.152871 µW**. Periodic state and its clock-pin load are unchanged.
All 27 matched wake windows per variant retain their classes and effects and
lose one fast/work edge; firmware wakes retire 43 instructions in **3,255 /
3,160 work-clock edges**. Functional and strict export checks pass. Arithmetic
data-budget failures remain explicit; these numbers do not update P&R, qualify
physical timing or measure reachable deep-sleep power or wake energy.

The [C1b retained peripheral/SRAM cleanup](held-peripheral-capture-contract.md#matched-cost)
is digitally verified. Against `2676845`, the same mapper and five-corner
Liberty accounting show logic area falling **1.78% BD / 1.41% Click**, to
**3.291909 / 4.147977 mm²** excluding SRAM. TT listed-state leakage including
SRAM falls to **8.603006–11.223379 / 10.293397–13.952939 µW**. Portable periodic
RTL totals become **6,000 BD / 6,001 Click**, excluding the unchanged SDA-edge
bit; enabled-policy physical SoC exports contain ten more bits each. Native
storage, delay chains, SRAMs and public ports are unchanged. Fresh activity
matches all 27 baseline windows per variant, including 3,256 / 3,161 firmware
work-clock edges and 43 retired instructions. These results do not update P&R,
qualify the direct capture paths or measure reachable standby/wake energy.

The digitally verified [R3b native-frame-routing comparison](gf180-matched-comparison.md#r3b-native-frame-routing)
uses the same mapper/library inputs as R3. Logic area changes **−0.05977% BD /
+0.02656% Click**, to **3.351460 / 4.207351 mm²** excluding SRAM. Both variants
remove four periodic-clock storage bits; Click adds two native route bits. TT
listed-state leakage including SRAM is **8.760285–11.451153 /
10.452129–14.179303 µW**. Each front/work storage clock load falls 0.006692 pF.
Compiled portable periodic totals are **6,538 BD / 6,539 Click**; enabled-policy
physical SoC exports contain ten more bits each, excluding the chip wrapper.
No payload bank or timing exemption is added. Fresh activity matches R3 in all
27 windows per variant: firmware wakes use 3,256 / 3,161 work-clock edges and
retire 43 instructions, with unchanged measured durations. Affected functional and
strict checks pass; independent review receipts bind the evidence. These measurements exclude
loader transfer latency and do not establish physical timing or power/energy savings.

The digitally verified [R3 frame-completion comparison](gf180-matched-comparison.md#r3-incremental-frame-completion-comparison)
uses final exports and the same C1 mapper/library inputs. Logic area increases
0.04833% BD / 0.00423% Click to **3.353464 / 4.206234 mm²** excluding SRAM.
The completion join and four clocked control bits add no payload bank; existing
native storage and guard area are unchanged. TT listed-state leakage including
SRAM is **8.765842–11.459462 / 10.450277–14.177046 µW**. Fresh activity retains
3,256 / 3,161 work-clock edges and 43 retired instructions per firmware wake;
all 27 measured windows per variant match C1. Storage clock-input capacitance
increases 0.006692 pF on each front/work domain. Affected functional checks, strict
exports and fresh independent review pass; these results do not measure loader transfer latency,
establish physical timing or measure standby/wake energy.

The [C1 service-reply accounting](service-reply-capture-contract.md#matched-cost-of-this-correction)
uses the same mapping inputs and flow against the matched candidate. It removes
duplicate clocked payload banks and reduces mapped logic area to 3.351844 mm²
BD / 4.206056 mm² Click. These mapped results do not update the historical P&R
or establish energy savings.

## Historical mapped candidate and activity, 2026-10-12

This refresh covers controller RTL at `c4b7f44`, the supported physical export
under review in 17a2a, and the enabled Groundlark evaluation policy. It precedes
the corrective reset-domain and frame-copy changes requested in the independent
review. **These candidates are not timing-qualified.** The actual mapped native
adapters include the overlong guard chains; counting them does not authorize
their use in silicon. Repeat the accounting after those repairs.

| Quantity | Four-phase BD | Native Click |
| --- | ---: | ---: |
| Audited mapped leaves, including three SRAMs | 125,834 | 127,956 |
| Sum of Liberty cell/macro areas | 4.1115 mm² | 4.9692 mm² |
| Sum of LEF cell/macro footprints | 3.9495 mm² | 4.8073 mm² |
| Matched-control guards within those sums | 0.5941 mm² | 1.1463 mm² |
| TT / 25°C / 3.3 V listed-state leakage estimate | 9.10–11.95 µW | 10.80–14.68 µW |
| FF / 125°C / 3.6 V listed-state leakage estimate | 301.86–689.90 µW | 383.47–804.20 µW |

Every cell is counted once from the audited synthesized hierarchy, including
native storage/control, ordinary logic, all three pinned SRAM macros and the
production 100,000-edge POR reset sequencer (117 mapped leaves per variant).
The pinned SRAM Liberty area is 209,400.2768 µm² per macro; its pinned LEF is
301.300 × 515.810 µm, or 155,413.553 µm². Standard-cell areas agree between views.
The three macros therefore explain the entire difference between the two area
rows. Neither sum includes placement whitespace, routing/clock-tree overhead,
analog layout or pads, and neither is a core or die-area result.

Leakage sums use standard-cell conditional minima/maxima plus one aggregate SRAM
datum per corner, with the SRAM's mW units converted to µW. These are listed-state
library estimates, not measured standby power or complete silicon bounds. The
macro has no state-dependent min/max table. Correlated reachable standby state,
analog, pads and physical implementation overhead remain unmeasured. All five
pinned corners are retained in the evidence; the table shows nominal and hot-fast.

The unchanged native-model activity fixture ran at 12 MHz and retained all its
functional assertions. Both variants produced 22 maintenance, three sampling
and two firmware wake observations. Each firmware wake retired exactly 43
instructions. POR startup is accelerated before measurement; mapped area uses
the real reset sequencer. These are digital-model activity counts, not
mapped-netlist timing or energy measurements.

| Observed wake | BD service / work edges | Click service / work edges |
| --- | ---: | ---: |
| Maintenance | 37 / 22 | 37 / 19 |
| ADC acquisition and scaling | 220 / 216 | 218 / 214 |
| 43-instruction firmware workload | 3,260 / 3,256 | 3,165 / 3,161 |

Evidence lives under `build/review-c4b7f44/`: original test XML/logs, native
observer logs, `mapped-cost-preview.json` and its script. Fresh independent
review used a separate Liberty parser, Decimal accounting and recursive netlist
walk; observer-only simulations independently reproduced every wake window.
Its complete report and failures are in `independent-cost-review/`. Native
storage-enable counts are retained there; they are not changed-bit counts or
dynamic energy. The historical baseline below uses different memory and async
cell approximations. No matched baseline comparison was run, so these numbers
do not establish an area or power improvement from the migration.

## Historical flip-flop baseline

The results below predate the current 2 KiB program / 1 KiB working SRAM
implementation. They are not current SRAM or wake-energy estimates. The old
estimator rejects unmapped SRAM rather than silently omitting it; the refresh
above instead counts the actual audited physical candidate. See
[SRAM integration](sram-integration.md).

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
