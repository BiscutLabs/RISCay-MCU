# Clocked RISCay-MCU

Independent synchronous RV32E implementation alongside four-phase BD and Click.
The target is the current generic MCU ABI, boot firmware, memory macros and
reset/retention behavior. No application policy belongs in RTL or ROM.

## Implementation status

- Independent clocked CPU, fabric, loader, GPIO, event, measurement and timer state.
- Shared generic SPI/A-B boot firmware, fixed SRAM macros and I²C fallback.
- Gated work clock with independent LF watchdog, retained sleep and coordinated reset.
- Ordinary synchronous export; physical timing qualification remains separate.

The core uses one outstanding ready/valid memory transaction. Request and
response acceptance occur on distinct rising edges. Writeback updates the one
register file on response acceptance; no payload moves around an async token
ring. x0 is constant; x1â€“x15 and control state clear on reset. A halt notification
is accepted once and receives no response. Reset cancels the transaction epoch;
the fabric must discard stale replies without undoing already committed stores.
Retirement is a one-cycle observation after response acceptance.

ISA semantics, payload schemas, boot-ROM generation, fixed SRAM models and
independent verification utilities are shared. Sequencing and storage are owned
by this design. The core tests use the same programs and independent interpreter
as BD/Click, including stalls, faults, reset and a deliberately incorrect oracle.

```sh
python tools/sbt.py "clocked/runMain riscay.clocked.EmitClockedCore build/clocked-core"
python tools/sbt.py "clocked/runMain riscay.clocked.EmitClockedSoc build/export/clocked"
python tools/sbt.py "verification/testOnly riscay.ClockedCoreSpec riscay.ClockedSocSpec riscay.ClockedFabricSpec riscay.ClockedBoundarySpec riscay.ClockedSleepSpec riscay.ClockedDeepSleepSpec riscay.ClockedGenericBootSpec riscay.ClockedFirmwareSpec"
```

See the [clocked design contract](../../docs/clocked-design.md) for ownership,
clock and reset rules, shared verification and remaining physical obligations.
BD remains the selected physical target; this variant changes neither async
implementation. Area comparisons belong in the [ledger](../../docs/area-ledger.md).
