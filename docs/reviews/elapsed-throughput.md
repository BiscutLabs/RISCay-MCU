# Elapsed throughput after guard lengthening

This correction adds verification and a throughput contract; production RTL,
guard targets, firmware ABI and sleep admission are unchanged. Existing native
tick batching already handles arbitrary 32-bit deltas in at most eight
arithmetic turns and coalesces targets that arrive while busy.

The 100 ns requested adapter maps to an 88-cell chain. The pinned five-corner
Liberty experiment, at 0.02/2 ns input slew and 0.003/0.05 pF output load, finds
**644.726257 ns** maximum at SS, 125 C, 3 V, 2 ns slew and 0.05 pF. Both variants
use the same adapter tuple and physical recipe. This is an adapter measurement
without extracted interconnect, not the complete loaded elapsed stage. The
645 ns test override is resolved through the emitted contract's actual
`ca_child_elapsed_scaler.ca_child_native.ca_child_step/request_delay` primitive;
production OwnerTiming and its reset-policy limits are unchanged.

At 645 ns, the original accelerated sleep test fails for **both** variants:
`MAINTENANCE_STARVED_SLEEP entries=0`. Its 2 us tick interval, 100 us observation
window and minimum ten sleep entries are unchanged. The default 100 ns model
still passes. Reproduce the diagnostic in PowerShell with
`$env:RISCAY_ELAPSED_STRESS_NS='645'`, then
`python tools/sbt.py 'verification/testOnly riscay.ScalingSleepSpec -- -z accelerated'`.
Remove the environment variable before the ordinary suite. A failing diagnostic
exits unsuccessfully; it is not an expected-pass test.

`ElapsedThroughputSpec` uses the production tick coefficients and the rounded
645 ns guard at 8 and 20 MHz service rates. Full-width/wrapping deltas, exact
fractional arithmetic, post-admission batching, stopped receipt clocks, held
replies and stale single-tick rejection pass. An independent edge monitor
counts publications. Integrated trials check architectural NOW_MS as well as
final consumedGray, bridge drainage and sleep. LF is manually restarted for
one event, then paused; these are isolated latency trials, not a production
oscillator waveform or a test of permanent Groundlark supervision under load.

| Largest observed interval, across both tested service rates | BD | Click |
|---|---:|---:|
| One full-width batch through receipt and return | 14.938 us | 6.813 us |
| Isolated LF restart through final publication and sleep | 9.125 us | 5.500 us |

The conditional test ceilings are 32 us per batch and 64 us for two batches or
integrated isolated maintenance. Startup and physical-cell/wire envelopes still
need qualification. The [contract](../native-elapsed-contract.md#throughput-and-tick-batching)
compares those allocations with the 83.333 ms fastest production tick interval
and excludes faster generic configurations from that inference.

Evidence remains under `build/`:

- `elapsed-slow-throughput/guard-r1/`: five corner scripts/logs and the exact
  adapter recipe, hashes and 40 bound measurements in `results.json`.
- `elapsed-slow-sleep-stress-r1.log`: both unchanged accelerated failures.
- `elapsed-throughput-r3.log`: all 14 tests pass (eight new, six standing).
- `elapsed-slow-throughput/budget-controls-r2/`: both actual request-delay
  faults (645 ns to 5 us) trigger `ELAPSED_BATCH_BUDGET`. Identical 20 us POR
  baselines pass; this fault exceeds the normal model reset envelope. The first
  attempt with ordinary 2 us POR reached an unrelated startup deadline and is
  retained under `budget-controls-r1/`, excluded from the accepted controls.
- `elapsed-slow-throughput/positive-summary.json`: exact successful fixture
  directories and measured intervals. Each keeps its exported contract,
  resolved override, testbench, executable and simulator log.
- Earlier `elapsed-throughput-r1.log` and `-r2.log` retain fixture defects:
  an assertion incorrectly required sleep to deassert before synchronized wake
  propagation, and a test read Gray-to-binary combinational delta cycles without
  settling. The corrected test distinguishes new sleep entry from wake latency
  and samples the coherent target after 1 ns. No production behavior or existing
  oracle was changed to resolve these test defects.

Independent review caught legacy coefficients in the first integrated fixture
and a counter that counted checker calls instead of real publications. Both
were corrected before the passing run; the reviewer also requested the added
NOW_MS oracle. Guard-only throughput passes do not close setup/hold, capture
distribution, reset release, mismatch, electrical or extracted-RC obligations.
