# Single-writer Telemetry conversion

Implemented and verified in both variants against parent `d0a01c5`. The
[review record](reviews/single-writer-telemetry.md) contains the final evidence and
remaining physical qualification limits.

## Ownership and time contract

The physical ADC owns channel 0 when configured. Other measurement channels are
CPU-published through the existing selector/value/commit MMIO. This distinction
is part of the generic MCU ABI. Each bank has one writer; host snapshots only read.
CPU application/GPIO updates and their ordered recovery remain in Telemetry.
Samples have POR lifetime, including accepted CPU publications whose application
resets before native dispatch. GPIO/application cancellation cannot discard them.

Age uses the conservative upper-time coordinate, **not** nominal MMIO `now`.
Use a shared 64-bit upper-millisecond coordinate and native last-good timestamps;
read age is the saturated 32-bit difference. The supported uninterrupted POR
interval is less than 2^63 upper milliseconds (over 292 million years); timestamp
subtraction is unsigned modular arithmetic within that bound. Never-sampled age
is `0xffffffff`. Failed attempts increment the 32-bit sequence and update
valid/fault/calibration, while preserving the last-good value and timestamp.
ADC timestamps originate at conversion admission, including the existing
coincident-tick convention and subsequent conversion/publication delay. CPU
software samples take the accepted offset-44 edge's upperTimeNext; dispatch
backpressure contributes to age instead of resetting the age at publication.
The implementation computes the low-word difference and checks the high-word
borrow condition directly. Four-bit combinational carry-select modules bound
the mapped carry depth. Both nibble and group-prefix module boundaries prevent
ABC from rebuilding a word-wide ripple chain. The shared counter precomputes its upper increment
and selects it on low-word carry. Both are equivalent to the 64-bit arithmetic;
neither adds a register, pipeline cycle or clock boundary.

Remove time-driven Observe and sample batching from Services. ADC result
publication commits its own closed native sample bank through its existing
retirement handshake. CPU software samples have a separate POR bank and retained
accepted-publication obligation. The application/GPIO bank remains independent.
No native owner contains a periodic clock, and no new native arbitration is used.

Borrow CPU commit operands from the existing POR `mmioCommit` bank, held until
the next successful CPU write. Save the selected application index with offset 52;
reset can clear the live index. Software sample index/value survive reset and host
commands, and CPU admission must prevent their overwrite until complete return.
Pending software publication and its timestamp survive cancellation; stale CPU
responses do not. The optional timestamp tracks the shared time only while all
command pending/outstanding/return flags are idle. Acceptance captures the same
edge's upperTimeNext, then freezes it through the complete loan. This keeps the
wide bank's enable out of the deep admission decode without adding storage.
Reset recovery waits behind that accepted obligation.

Host `readStart` remains the atomic snapshot point. Clocked readers must use a
qualified closed bank; a pending newer publication suppresses fresh-valid without
presenting mixed value/status/sequence. Actual application/reset commits retain
Click's completion synchronizer. Removing time-only bank turns reduces maintenance
from 21 to 18 work edges without bypassing reader qualification.

## Baseline and remaining arbitration

`report_clock_owners.py --registers Services` partitions physical sinks by their
complete local Q-alias set, preserving unnamed state and avoiding alias double
counting. Both parent variants have 1,468 work and 14 service sinks in Services.

| Register family, descending work sinks | BD | Click |
| --- | ---: | ---: |
| Snapshot bank | 269 | 269 |
| Housekeeping ordered command | 211 | 211 |
| Housekeeping state | 194 | 194 |
| Housekeeping queued observations | 136 | 136 |
| Control state projection | 106 | 106 |
| Host sample projection | 100 | 100 |
| Telemetry capture accumulator | 100 | 100 |
| Retained MMIO commit | 71 | 71 |
| Program access boundary | 54 | 54 |
| RAM access boundary | 52 | 52 |
| Telemetry commit | 45 | 45 |
| Telemetry in-flight projection | 33 | 33 |
| Telemetry elapsed accumulator | 32 | 32 |
| Other Services state | 65 | 65 |

The full per-register inventory is retained in
`build/single-writer-telemetry/{bd,click}-baseline-registers.json`.
The parent maps are `build/clocked-events/map-bd` and `map-click-r2`.

The new maps have identical Services inventory in both variants: **1,228 work
+ 14 service sinks**, down 240. Ranked work families are snapshot 269,
Housekeeping ordered 211, Housekeeping state 194, Housekeeping queued 136, Control
106, retained MMIO commit 77, upper-time coordinate 64, program boundary 54, RAM
boundary 52 and remaining state 65. The six added MMIO bits retain the selected
application index while borrowing the commit. Removed sample projection,
capture accumulator, Telemetry commit/in-flight and elapsed families total 310
sinks; 64 time and six index bits give the measured net reduction of 240.
Full results: `build/single-writer-telemetry/{bd,click}-registers-r7.json`.

Events/clear/WAIT, Control dispatch (host, CPU, Stored, reset), and Housekeeping
dispatch (time, CPU timer/cadence actions, reset) retain their documented receiving
clock as arbitration. Telemetry's remaining CPU/recovery dispatch also preserves
that ordering; removing its payload copies does not remove the command boundary.
Qualifying a GF180 MUTEX is not a prerequisite for this
single-writer split. A later native conversion must move the competing producers
and consumer together and separately qualify its arbitration.

## Verification and remaining physical obligations

Both variants pass the age/sequence/freshness, reset, borrowed-payload and host
snapshot oracles, with timestamp rollover/saturation and ADC-versus-CPU independence
cases. Final CI passes 303 Python and 197 Scala/export-policy tests; the focused
run passes 42 tests. Both RDC proofs and five export audits pass. Independent
reviews are closed. Changed BD bank readers and feedback paths pass the local
corner campaigns; Click has functional checks and matched area/sink accounting,
without a physical sizing campaign. The area ledger records the measured results.

Timestamp setup is a separate one-period (50 ns) obligation; the sample bank's
return qualification does not lengthen it. The screen inventories every periodic
launch into the counter, age readers and admission timestamps, including receipt
valid/active gating. The retained elapsed operand prepares the sum while the
receipt settles; validity qualifies the final mux. Invalid payload cannot update
retained timestamps. The [review record](reviews/single-writer-telemetry.md)
preserves failed arithmetic maps and the fixes. No deadline or aperture was relaxed.

The raw elapsed operands have a separate receiver-side max/min screen. From
synchronized request detection, the receipt waits two complete edges before
acceptance: 100 ns at the minimum period. Setup is conditional on source data
having settled by detection, at the sampled 0.02/2 ns source-slew cases.
Hold conservatively permits source reuse immediately on receipt ACK, ignoring
the positive native return delay. Only elapsed-port bindings receive those
bounds; CPU/Control admission qualifiers retain their own crossing obligations.
Elapsed source-Q versus publication/history composition, continuous source/internal
slew coverage, routed RC/skew and electrical signoff remain separate obligations. Receipt settling alone is not
a measured native-launch proof.

A/B slots, an immutable golden recovery image, factory provisioning and measured
full-capacity boot remain ahead of further area/guard tuning. Existing single-image
SPI boot and I2C fallback do not yet provide that resilient boot layout.
