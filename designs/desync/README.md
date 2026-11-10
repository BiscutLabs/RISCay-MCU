# Desynchronized RISCay-MCU digital prototype

Independent copy of `designs/clocked`, preserving its flip-flops, FSMs, ABI,
SRAM macros and reset semantics. The copied `Clocked*` class names stay under
`riscay.desync` to keep the comparison reviewable. Old BD/Click remain frozen.

`DesyncSoc` exposes the region's ideal-clock view. `DesyncChip` connects one
`DesyncClock` at the existing service-clock boundary, retaining the work gate,
LF watchdog/timebase and wake logic. Its LF clock and power-good inputs connect
to the existing analog boundary. There is no periodic fast oscillator in this shell.

The digital source is a C-element/matched-delay loop with a behavioral mutex.
Pause requests persist through arbitration; stopping finishes the current pulse.
Digital arbitration resolution is bounded by explicit test assumptions. It does
not demonstrate metastability filtering, physical timing or analog liveness.

```text
python tools/sbt.py "desync/runMain riscay.desync.EmitDesyncSoc build/export/desync"
python tools/sbt.py "verification/testOnly riscay.DesyncClockSpec riscay.DesyncChipSpec riscay.DesyncSocSpec"
```

Select `filelist-simulation.f` to simulate the exported shell. The testbench must
set positive delay/mutex `MIN_NS` and `MAX_NS`; see the [build guide](../../docs/build-and-test.md).
POR cancels pending digital events; physical reset limits remain unqualified.
These models disappear under `SYNTHESIS`. Physical generator recipes and
STA-derived chain counts are still unavailable; physical mapping fails closed.

The copied region maps to **0.5318332992 mm² / 2,977 storage bits**, exactly the
clocked reference. This excludes the unfinished generator and does **not** meet
the complete-chip area gate. See [contract](../../docs/desync-contract.md) and
[ledger](../../docs/desync-ledger.md) for scope and evidence.
