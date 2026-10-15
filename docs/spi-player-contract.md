# Compact timed SPI player (C1d)

Status: digitally verified, independently reviewed and measured. This
removes duplicate recipe storage at the existing clocked pin boundary. It does
not migrate that boundary or qualify new physical timing.

The separate BD and Click native controllers publish a POR-immutable recipe:
initial CS/SCLK, 32 CS levels, 32 SCLK levels and 32 occupancy bits. At the
original waveform-token acceptance, each player retains slot zero and whether
any slot is occupied. The registered pins load the original initial levels.
The divider, all 32 MISO samples, conversion age, admission, first-frame discard
and native return ownership are unchanged.

On each original divider expiry the pins load the recipe bits at the current
slot and the sample register shifts once. If `recipe.occupied >> slot` equals
one, playback stops and the original completion/sample flags assert. Otherwise
the slot increments. This replaces three 32-bit registers with a five-bit slot
and one active bit. Declared state is not a mapped cost or energy measurement.

The highest occupied bit still determines playback length. Holes do not skip
slots, and an empty recipe starts no playback, matching the old shift registers.
Termination is not hard-coded to slot 31. The production immutable recipe still
selects all 32 observations; exact emitted constant and connection checks remain
mandatory. Watchdog reset does not change the recipe or player lifetime. POR
clears control and registered pins, cancels the partial conversion and reprimes.

The recipe must remain immutable while the player is alive. An arbitrary
changing recipe is outside this implementation's contract: the old player's
acceptance-time copy and a live indexed recipe would not be equivalent. Both
production native outputs are literals; strict validation must prove those
values and their actual pin-player connections. No raw native transaction bus
is substituted for this constant recipe.

`SpiRecipeReplaySpec` checks every slot and divider residue at half-period
counts 2, 3 and 5 for both variants. Stopping the service clock must freeze the
pins, slot, divider and samples; resumption must complete exactly one result.
These artificial pauses prove retention and clock-edge cadence, not a valid
real-time ADC waveform. The original `SpiAdcSpec` wall-clock half-phase,
maximum-delay, age, priming, stalled-reply and POR oracles remain unchanged.
`AsyncSpiAdcSpec` and independent scaling checks remain required.

Actual emitted-RTL controls must cover native recipe constants, initial pin
loads, slot load/advance, occupancy termination, divider qualification and MISO
capture. Each fault must trigger its exact original assertion site; timeouts,
compile failures and unrelated assertions are failures of the campaign. Keep
all four generic strict-export campaigns independently mandatory.

Matched measurement must report periodic and native state, mapped area and
clock-pin load, all five leakage corners and every original wake window. Check
the new index/termination/pin paths across the pinned corners, retaining real
setup, hold, slew and load failures. Schematic or native-model passes do not
establish routed pin timing, reachable standby power or wake energy.

## Matched cost

The same mapper, fixed cells and five pinned leakage corners compare parent
`a8c0300` with this change. All native primitive instances, native guards,
macro instances and external schemas remain unchanged. The table includes
ordinary mapper variation outside SPI; that variation is accounted separately
from the player reduction.

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Logic area excluding SRAM (mm²) | 2.939063 → 2.931040 | 3.710656 → 3.699481 |
| Mapped leaf cells, including three SRAMs | 106,954 → 106,739 | 107,676 → 107,318 |
| TT listed-state leakage including SRAM (µW) | 7.772042–10.062488 → 7.752528–10.033946 | 9.252447–12.399941 → 9.222217–12.361046 |
| Portable periodic RTL bits | 6,000 → 5,910 | 6,001 → 5,911 |
| Physical periodic RTL bits | 6,010 → 5,920 | 6,011 → 5,921 |
| Mapped work-clock storage cells | 4,201 → 4,111 | 4,252 → 4,162 |
| Mapped work-clock pin load (pF) | 14.805705 → 14.514997 | 14.977131 → 14.686423 |

The SPI subtree saves 0.007426 / 0.007538 mm². Ordinary mapper variation outside
SPI contributes another 0.000597 / 0.003637 mm². Total logic falls 0.2730% /
0.3012%; the unchanged native guard area remains 0.569962 / 1.105951 mm².

Every ordinal of all 27 matched wake windows per variant retains its class,
effects, clock-edge counts and duration. Firmware wakes still retire 43
instructions in 3,255 BD / 3,160 Click work-clock edges, taking 271,607.839 /
263,691.109 ns in the native timing model. Reduced clock capacitance alone is
not a wake-energy measurement. Five-corner listed-state leakage envelopes are
preserved in the evidence; TT values are not reachable deep-sleep power.

## Measured local timing

The matched old/new mapped players have five-corner STA evidence under
`build/async-spi-recipe-reduction/timing-comparison-r1.json`. The analysis uses
the actual player register pins, a 50 ns service-clock period, 0.5 ns uncertainty
and 0.05 pF pin loads. All eight selected path groups have min/max coverage;
no path is cut or allowed to escape the player. This is a local mapped analysis,
without clock-tree or routed parasitics.

| Selected quantity | Prior player | Compact BD | Compact Click |
| --- | ---: | ---: | ---: |
| Worst setup slack (ns) | -69.464851 | 24.641670 | 25.372740 |
| Worst hold slack (ns) | 0.228433 | 0.383142 | 0.432764 |
| Worst local slew (ns; 2 ns limit) | 66.59 | 15.75 | 16.52 |

The selected compact-player setup/hold paths pass, but **slew and capacitance
violations remain**. Every report retains `MEASURED_WITH_VIOLATIONS`; improved
slack does not close those electrical failures. Registered pin arrival also
does not prove the external ADC's board timing. Native crossings, reset
distribution, clock gating, pad/board loads and complete routed timing remain
separate qualification obligations. The reader's 24 rejection controls check
coverage and evidence binding; they are not physical fault simulations.

## Verification and evidence

The focused SPI/scaling run passes 24 tests, including six indexed-player
fixtures covering 320 stopped-clock positions per variant. The affected SoC,
sleep, firmware, independent core/reference and physical-export regressions
pass another 143 tests: 167 distinct ScalaTest cases across 22 suites. All 519
Python controls pass. Existing wall-clock SPI and arithmetic oracles are unchanged.

All four strict SoC exports pass with sleep-clock background and three SRAMs:
BD 685,485,856 portable / 685,695,536 physical mapping checks, Click 588,506,120 /
588,694,920. Every export retains all four mandatory generic campaigns. The
lower check totals follow the narrower periodic-player observation footprint;
the native contracts and dynamic-polarity obligations are unchanged. The final
actual-wiring campaign passes all four baselines and 30 isolated faults. Each
fault fails at its exact original assertion site with an unchanged oracle.

Evidence lives in `build/async-spi-recipe-reduction/`. The matched cost,
`state-r2.json`, `exports-r1.json`, timing comparison and all 27 activity windows
are bound by `measurement-seal-r1.json`. Its reader controls pass two baselines
and 34 exact rejection cases. Independent collector checks reject 29 omissions,
duplicate variant groups and reduced test/coverage inventories; 25 further
controls check orchestration isolation, mutation binding and evidence identity.
Fresh independent acceptance is recorded in `review-final-r1.json`; the complete
source, test and measurement inventory is bound by `final-evidence-r1.json`.

The first four strict attempts exceeded a 600-second host allowance; their
logs and full export snapshots remain under `strict-failed-r1/`. The same RTL
then passes with the established 3,600-second host allowance. No simulated
deadline, guard, testbench or assertion was relaxed. The export reader's initial
failure to resolve nested assertion resources is also retained: its correction
resolves unique entries in the actual compiled file list, with missing/duplicate
resource rejection controls. Superseded state evidence remains available.

The sequential wiring attempt in `wiring-controls-r2/` stopped without a recorded
exit reason. Its partial receipt and eleven completed BD wire results remain
hash-verified evidence, not a completed campaign. The completed r3 attempt runs the
unchanged group engine in four independent directories, with identical probes,
faults and host allowances. Its orchestration is reviewed separately; it does
not claim that the interrupted command-line run completed.
