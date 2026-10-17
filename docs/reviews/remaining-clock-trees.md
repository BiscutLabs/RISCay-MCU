# Remaining clock ownership and CTS coverage

Read-only audit of merged PR9 (`d72ee39`), 2026-10-17. No RTL was changed and
no clock was removed. This audit does not qualify electrical timing.

The explicit CTS roots are `serviceClock`, `soc/gate_io_clockOut` and
`watchdogClock`. In `build/bounded-pnr-bd-r11/clock.log` and
`build/bounded-pnr-click-r2/clock.log`, CTS skips the work root because its
immediate sink is one ordinary repair buffer (`soc/gain1700` / `soc/gain1668`).
Traversal of the final `global-repair-after.tsv` graphs reaches 4,009 BD and
4,060 Click clock pins through 66/67 buffers, including all three SRAM CLK
pins. Reported CTS totals of 1,332/1,336 sinks do not establish balanced work
clock coverage. This finding does not establish that propagated STA omits
those sinks; CTS construction and STA clock reachability are different checks.

The correction must retain the generated-clock relationship, inventory all
periodic sinks before and after CTS, resolve existing legal buffer/inverter
paths, and preserve the three exclusive SRAM parent drivers. Verify positive
and negative edges, skew, duty cycle and pulse width. Do not add native capture
events or the external SDA event to periodic CTS.

| Clock or event | Current owners | Obligation and remaining migration |
| --- | --- | --- |
| LF/watchdog | `Watchdog`, `SleepTimebase` | Independent time and fault recovery must progress while service/native logic stalls. Retain POR ownership and the existing counter-width decision until observation bounds are proved. |
| Ungated service | Reset qualifier/coordinator, I2C sampler, GPIO synchronizers, gate/wake frontier | Qualified time, metastability handling and recovery are required today. Adjacent policy/history registers are not automatically necessary. |
| Gated work | Services scheduler, command/reply and reservation/drain receipts, elapsed ingress, SPI player, SRAM boundary | Most scheduler/transport state remains migration debt. Move producer and consumer ownership together before deleting crossings. |
| SRAM CLK | Three macros, currently driven from work clock | Legal pulse, address/data/control setup/hold and access timing are necessary. Periodic service operation is not intrinsic to SRAM. Production self-timed replacement remains gated on the complete macro, arbitration and POR-quiescence envelope. |
| SPI SCLK output | Work-clock waveform player | Bounded pin timing and MISO capture remain necessary. There is no separate gated-I/O CTS root. Coordination/history may migrate independently. |
| SDA falling event | START wake history while service is stopped | External event trigger, not periodic staging. Qualify input filtering and pulse/hold requirements; retain onward synchronization. |
| Chip reset-hold clock | Wrapper's continuous-good qualifier | At least 5 ms qualification and asynchronous assertion, independent of held SoC reset. It is outside the portable-SoC clock inventory. |

Both Services implementations still retain `boardResult`, `controlState`,
`housekeepingState`, application output copies, observation/command queues,
mailbox dispatch and coherent host-read snapshot state. These are checklist
11b–14 work, not physical reasons to retain a clock. I2C also retains 64-bit
reset epochs, the sampled-edge ring and descriptor ordinal around its wire
sampler. Preserve accepted-effect ordering, immutable snapshots, reset lifetime
separation and permanent supervisor progress when removing them.

Relevant sources are each variant's `Platform`, `Services`, `SleepTiming`,
`ClockedPeripherals`, `I2cTarget`, `SramBank` and native `Sram` implementation;
the wrapper is `soc/src/main/scala/riscay/soc/ChipWrapper.scala`. Functional
removal requires the affected native/service, reset-boundary, sleep, firmware,
stopped-consumer and strict-export suites. The existing 76-case experimental
byte-owner campaign is digital evidence, not production macro qualification.
