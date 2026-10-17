# BD hold: internal feedback versus guarded source release

Status: **conditional analysis of retained measurements; physical qualification
remains open**. No RTL, delay, timing budget or measurement tool changes here.

The approximately 1 ns Control hold number ends at the earliest **internal
feedback receiver** of the update stage. It does not include Control's existing
32 ns parent ACK guard. That local number must remain in the stage report, but
it is not the complete source-release boundary.

The fresh repaired Control Join campaign already measures the guarded ACK at
the actual operand receivers, and every update capture, from the same incoming
request event. Across both operand arrivals, five corners and two input slews:

```text
earliest guarded source-return arrival
  - latest update capture
  - Liberty hold requirement
  >= 52.094408 ns
```

The limiting case is the right operand at FF / -40 C / 3.6 V and 2 ns request
slew: 147.107148 ns return, 94.818740 ns capture and 0.194 ns hold. This grants
**zero** data-path contamination, source CLK-to-Q or latch-reopening credit.
The existing native ACK guard therefore needs no duplicate guard on the
strength of the approximately 1 ns internal-feedback number alone.

Every measured return path traverses the actual parent guard. The existing
checker inventories the physical ACK receivers and observes their unique live
drivers because the receivers themselves are held in their initial pre-ACK
state for this forward-admission context. Feedback suppressed by that condition
can only begin after the first ACK arrives. Driver arrival represents receiver
arrival only in this zero-wire model. This does not establish the earliest next
Q change, pending admission, either return sequence, source recovery or reset.

## How much the data path contributes

The retained standard-stage reports also contain minimum data delays; no new
STA sweep is needed to inspect them. For each dynamic lane and each case:

```text
conditional data-path credit = min(root-to-D rising, root-to-D falling)
conditional hold = unchanged local zero-credit hold + this credit
```

The roots are the declared live input drivers. They are storage Q pins for
Control, but some other boundaries use combinational outputs. The table does
not claim source-register launch or retention has been composed.

| BD stage | Minimum local zero-credit hold, ns | Minimum root-to-D delay, ns | Minimum conditional hold, ns |
| --- | ---: | ---: | ---: |
| CPU execute | 1.097177 | 0.536466 | 1.633644 |
| Elapsed step | 1.153910 | 0.511220 | 1.665130 |
| RAM prepare | 1.285952 | 0.356755 | 1.642707 |
| RAM issue | 1.247953 | 0.356755 | 1.604708 |
| RAM capture | 1.285952 | 0.356755 | 1.642707 |
| I2C protocol update | 1.187175 | 0.356755 | 1.543930 |
| Control update | 0.987104 | 0.356755 | 1.389183 |

Each column is minimized independently; the last column is computed per lane
and case before minimization. It is not the sum of the first two minima.
These small credits do not settle the other owners' hold requirements.
Several limiting paths consist only of the current data-allowance gate and
buffer; removing those cells would invalidate their measured credit.

The conditional addition assumes **every influencing root stays stable until
the measured earliest stage ACK**, with the case's annotated source slew and
controller/reset conditions. The 0.02/2 ns samples do not prove a minimum for
every possible reuse slew. Source hold, RF/FIFO composition, electrical
extrapolation, mismatch and extracted min/max wire RC remain open. No clock or
guard is removed, and no qualified hold result is inferred from this table.

## Evidence and decision

Inputs are `build/capture-drive-bd-stages-r1` (70 stage cases) and
`build/capture-drive-bd-join-r1` (20 operand contexts). Their complete artifact
and input hashes were checked before extraction. The extraction retains the
limiting minimum-data path, source and destination, and the guarded ACK
receiver/capture pair; it checks both data transitions and min/max ordering.
The retained calculation is `build/summarize_bd_hold_credit.py`, with output
`build/bd-hold-credit-r1.json` and the
[compact evidence](bd-hold-credit-evidence.json).

Keep Control's existing ACK guard. Measure the other owners' actual source
release and retention paths before deciding which need a native outward ACK
guard. Full source-retention and routed closure remain separate acceptance
gates; the existing zero-credit reports are unchanged.
