# Clocked comparison MCU

`designs/clocked/` implements the current generic MCU as a synchronous chip,
including its CPU. It is a third implementation, not the historical async CPU
with a clocked service island. BD remains the selected physical target; Click
and BD retain their independent native implementations.

## Ownership and interfaces

| Block | Implementation |
| --- | --- |
| CPU | RV32E, one outstanding ready/valid transaction, one register file, rising-edge writeback |
| Fabric | Ordered CPU requests; one held response; host and memory-completion priority on the work edge |
| Control | One clocked loader/image/lock state bank; combinational CRC32 word update |
| Memory | Fixed GF180 SRAM macros; four byte accesses per word; falling-edge pin preparation and rising-edge access/capture |
| Application/GPIO | One clocked copy of declared application words and configured GPIO bits; registered pad data |
| Events | Six-bit pending register and arrival-cutoff protection mask, with set winning over clear |
| Measurements | One sample bank; timestamp captured at acquisition admission; saturating age at read |
| Housekeeping | One bank for time, deadline, lease, wake mask and acquisition schedule |
| Host | Sampled I²C framed loader; one complete snapshot captured at read-address acceptance |
| SPI | Existing ADC wire protocol; generic ROM bit-bangs flash through the same GPIO ABI |

ISA transforms, schemas, image validation format, boot-ROM generation, profile
metadata, fixed macro models and verification oracles are shared. No BD/Click
owner, native transport, C-element, delay chain or phase adapter is instantiated.
The clocked implementation does not contain Groundlark application behavior.

The current ABI is retained, including sparse application words, absent-word
`0xffffffff`, full-word MMIO validation, RAM byte masks, protected program SRAM,
CRC/compatibility checks, programming lock and A/B/golden external boot. Host
reads capture all selected bank words on one work edge. Later CPU writes cannot
alter that snapshot.

## Clocks and sleep

The fast service clock samples I²C pins and runs reset/wake coordination. A
falling-edge gate supplies complete work-clock pulses to the CPU, fabric, SRAM,
GPIO sampler, ADC player and arithmetic. The independent LF clock runs the
watchdog and Gray-coded timebase. SDA START retains the existing asynchronous
wake-event frontier so a stopped fast oscillator can restart.

I²C sampling remains ungated: otherwise SCL could rise while the work domain
sleeps and START would be missed. `busy` opens the work gate before the complete
address byte. The supported minimum 8× oversampling leaves enough edges for
reopening; an assertion requires the consumer clock to be live for every frame
and snapshot commit. Service and work clocks are related, not asynchronous
domains. This boundary needs no payload mailbox.

WAIT withholds CPU acceptance until the existing wake predicate is true. Pending
events, leases, ADC activity, SRAM work and outstanding replies prevent unsafe
sleep. Missed LF ticks are accumulated exactly with fractional remainders and
published as one bounded arithmetic batch. The CPU performs no polling while
parked. Stopping the work clock does not stop the watchdog.

## Reset and retained effects

POR clears control, GPIO output-enable and application state. It does not promise
zero SRAM contents; the existing simulation model poisons initial memory.

Raw watchdog assertion immediately isolates pads and trace and wakes the service
clock. A two-edge synchronized cancellation closes the fabric and synchronously
resets the CPU on the same work edge. It never asynchronously changes a CPU
payload under an open retained receiver. CPU release waits for fabric cleanup.
An already accepted SRAM word finishes; its old CPU reply is discarded.

Image, lock, loader ownership, sample records, wall time and crash accounting
survive application reset. Application words, events, deadline and lease clear.
GPIO clears unless the generic retention option is enabled; even then SPI boot
outputs 3–5 release and require a fresh bus claim. POR disables all GPIO outputs.
Neither application reset nor the lock stops acquisition or the independent LF
clock. ENTER_LOADER suppresses application kicks until watchdog recovery, then
normal bootloader maintenance resumes.

## Verification and physical scope

The shared core programs and interpreter, serial-host tests, event oracle,
fabric, sleep, deep-sleep, firmware and complete generic-boot scenarios run on
this implementation. Expected values and simulated deadlines are shared with
BD/Click. Additional tests interrupt accepted SRAM stores across reset phases,
check both GPIO-retention settings and pin transitions, and suspend an ADC
conversion while LF time continues.

`ClockedExport` emits ordinary RTL, `ports.json`, `sram.json` and `clocked.json`.
It does not emit an async contract or claim the native StructureAudit. The
clocked mapper rejects async primitive references and unresolved cells, verifies
the macro inventory and accounts for every storage clock pin.

Mapped area is not physical qualification. Electrical repair, clock-tree design,
service/work related-clock constraints, LF CDC and SDA event recovery/removal,
SRAM pin setup/hold/pulse widths, reset distribution and routed setup/hold remain
required before this variant can be considered for manufacture. No BD timing
margin or P&R result transfers to it.
