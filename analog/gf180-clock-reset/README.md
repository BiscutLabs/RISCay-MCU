# GF180 clock and reset schematic candidates

This directory implements the fast service oscillator and the always-on supply
monitor. The existing [LF oscillator](../gf180-lf-osc/README.md) supplies sleep
timing and the watchdog. Both MCU variants use the same circuits and reset
sequencer. These are transistor-level schematic candidates with digital
integration coverage, **not layout-qualified or silicon-qualified macros**.

`circuits.py` generates the checked-in SPICE netlists. Devices are GF180 3.3 V
MOS, vertical PNPs and 3k high-resistance poly. Capacitors are MOS gate devices;
no ideal reference, oscillator, resistor or timing capacitor is hidden inside
either macro. Ideal supplies and the output-load capacitor belong to testbenches.
The proposed device set does not introduce MIM capacitor devices. Final process
options and mask choices still belong to the foundry/layout review.

## Fast oscillator

`riscay_service_osc_gf180(vdd, vss, rst_n, enable, clk)` is a five-stage RC ring
with 240 kOhm nominal poly resistors and MOS loading. A transparent-low enable
latch allows a complete final high pulse before stopping low. `rst_n` is driven
by raw supply qualification, independently of the reset held on the SoC/LF
oscillator. Supply failure may truncate a pulse; logic is asynchronously reset.

The interface envelope remains **8..20 MHz**, startup <=100 us, and a 100 fF
maximum characterized output load. Schematic nominal frequency is about
**12.02 MHz**. The executable default is 12 MHz; legacy 10 MHz test fixtures and
`SocParameters.serviceHz` are reference-cycle configuration values, not a claim
that this untrimmed analog source is exactly 10 MHz. Production elapsed time and
sampling intervals use LF ticks. ADC dividers and the eventual clock receiver
must be qualified against the full fast-frequency envelope.

The 157-case campaign covers five MOS corners, three resistor corners, -40/25/125 C,
3.0/3.3/3.6 V, 20 stop phases, a lighter 20 fF load, and a half-timestep control.

| Measured schematic quantity | Result |
| --- | --- |
| Frequency | 8.6246..17.0478 MHz |
| Enable to first rising edge | 31.31..64.00 ns |
| Shortest high / low pulse | 29.37 / 29.25 ns |
| Active supply current | 27.87..107.60 uA |
| Stopped supply current | 0.019..20.875 nA |

The short startup measurement begins with bias/supply already established. It
does not replace power-up qualification. Current excludes the MCU and clock tree.

## Supply monitor and reset hold

`riscay_supply_monitor_gf180(vdd, vss, good)` uses a self-starting bandgap topology:
a 1:8 PNP pair, PTAT resistor, mirrored reference branch, compensated servo and
hysteretic comparator. It does not depend on firmware or either oscillator.
The schematic is an original implementation of standard bandgap/comparator
topologies; it is not a copied or qualified Tim Edwards POR macro. His
[GF180 POR project](https://github.com/RTimothyEdwards/gf180mcu_ocd_sram_test/tree/6d4f6099546c0540911007e7eebde9e61f1fcf8b/ip/simple_por_3v3_regulated)
was reviewed, but its documented slow-ramp behavior does not alone establish
the required supply threshold/brownout function here. The separate LF oscillator
retains its existing Tim Edwards attribution.

The 137-case monitor campaign crosses five MOS, three resistor and three BJT
corners at -40/25/125 C, plus 0.1 s and 1 s ramp checks. With 2 ms supply ramps,
the established-reference recovery threshold is 3.1179..3.2391 V and the falling
threshold is 3.0202..3.1383 V. Measured hysteresis is 65.76..134.00 mV.
These are dynamic schematic measurements, not guaranteed DC trip limits or
statistical yield bounds.

Reference startup can make the **raw `good` output chatter**. It must never
drive the SoC reset release directly. The digital sequencer:

1. Asserts reset asynchronously on `!powerGood` or the manual reset input.
2. Forces the fast source on while reset is held; no LF clock is needed.
3. Synchronizes qualification, then counts 100,000 consecutive fast cycles.
4. Releases LF reset and the inner SoC reset after **at least 5 ms** at 20 MHz
   (about 8.32 ms at the measured nominal frequency). The inner SoC additionally
   synchronizes its reset release. Any new supply fault starts the hold again.

Watchdog-generated resets remain inside the SoC and do not reset the LF source
or its supply monitor. Manual reset and brownout invalidate the image and clear
the programming lock. Retained sleep preserves both. There is no new clock or
power-good package input; the existing reset input is a manual override.

An additional 52 cases test 10 us/2 ms/100 ms/1 s ramps to 2.7/3.0/3.3 V at four
selected corners, and 1 us dips from 3.3 to 2.7 V. All low plateaus remain reset
after settling; 3.3 V plateaus recover. The largest observed startup-high interval
below 3.0 V (measured above 0.5 V) is 1.030 ms, rejected by the 5 ms hold; the
checker allows at most 2 ms for margin. Outputs below 0.5 V are not treated as
valid digital logic. Real reset-cell behavior during power ramps remains a
physical qualification requirement.

Dip detection takes **39.84..62.02 us** in those four tests; the integration
budget is 100 us. This is not instantaneous protection. A fast collapse can
cross the valid digital rail before reset asserts. Rail hold-up, reset-path
timing and passive safe power-switch controls must be checked at board/physical
integration; this circuit does not promise orderly Pi shutdown after total loss.

Monitor current is approximately **2.224 uA at 3.3 V, typical/25 C**, and
1.535..4.125 uA over the 3.6 V monitor corner sweep. This always-on circuit is a
significant sleep-power contributor. It is not a proven minimum-power design;
physical estimates should include it explicitly before further optimization.

## Reproduction and evidence

Use the pinned models from `../gf180-lf-osc/sources.json`; provision them using
that directory's documented fetch command. ngspice 42 is used in WSL Ubuntu.
The same documented resistor compatibility transformation is used, with nine
independent DC checks before every campaign. Model preparation now writes
atomically so simultaneous campaigns cannot read an incomplete library.

```sh
python3 analog/gf180-clock-reset/circuits.py
python3 analog/gf180-clock-reset/characterize.py --suite clock --output build/clock-campaign
python3 analog/gf180-clock-reset/characterize.py --suite monitor --output build/monitor-campaign
python3 analog/gf180-clock-reset/characterize.py --suite supply-events --output build/supply-events
python3 analog/gf180-clock-reset/characterize.py --suite controls --output build/clock-reset-controls
python -m unittest tools.test_clock_reset_measurement tools.test_reset_circuit
```

Each output directory must be fresh. Reports retain model and netlist hashes,
simulator version, test parameters and measurements; decks, logs and waveforms
remain under ignored `build/`. The disabled-oscillator and removed-hysteresis
controls must fail for their intended measurement reasons, not simulator errors.
`probe.py` is exploratory only and never produces qualification evidence.

This turn's passing evidence is `build/clock-reset-clock-01`,
`build/clock-reset-monitor-05`, `build/clock-reset-events-03` and
`build/clock-reset-controls-final`. Earlier experiments include failed startup,
threshold and compensation attempts. One concurrent run read a partially
rewritten model; it failed, the file preparation was repaired, and the campaign
was rerun. The first supply-event run was canceled because unnecessarily small
steps made plateau simulations expensive; it is not a pass.

Still required: analog review including loop stability, mismatch/Monte Carlo,
noise and jitter, resistor/capacitor layout and extraction, DRC/LVS, reset-cell
power-ramp behavior, receiver/fanout/clock-tree loading, synchronizer placement,
rail collapse/hold-up limits and complete-chip standby/active energy. Do not
substitute the digital `_model.sv` views for any of those checks.
