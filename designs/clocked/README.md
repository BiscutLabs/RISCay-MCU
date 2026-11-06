# Clocked RISCay-MCU

Independent synchronous RV32E implementation alongside four-phase BD and Click.
The target is the current generic MCU ABI, boot firmware, memory macros and
reset/retention behavior. No application policy belongs in RTL or ROM.

## Implementation status

- Clocked core and ordinary SystemVerilog export implemented.
- SoC memory, host loader, boot, peripherals and low-power integration in progress.
- Physical area, clock-tree and timing comparison pending the complete chip.

The core uses one outstanding ready/valid memory transaction. Request and
response acceptance occur on distinct rising edges. Writeback updates the one
register file on response acceptance; no payload moves around an async token
ring. x0 is constant; x1–x15 and control state clear on reset. A halt notification
is accepted once and receives no response. Reset cancels the transaction epoch;
the fabric must discard stale replies without undoing already committed stores.
Retirement is a one-cycle observation after response acceptance.

ISA semantics, payload schemas, boot-ROM generation, fixed SRAM models and
independent verification utilities are shared. Sequencing and storage are owned
by this design. The core tests use the same programs and independent interpreter
as BD/Click, including stalls, faults, reset and a deliberately incorrect oracle.

```sh
python tools/sbt.py "clocked/runMain riscay.clocked.EmitClockedCore build/clocked-core"
python tools/sbt.py "verification/testOnly riscay.ClockedCoreSpec riscay.CoreSpec"
```

The approved implementation order is core, SRAM/fabric/boot, services, reset and
sleep integration, then whole-chip compatibility and a matched area comparison.
Each verified batch receives independent review. BD remains the selected
physical target; the clocked variant does not qualify or change either async
implementation.
