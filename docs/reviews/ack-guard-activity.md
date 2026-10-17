# Native ACK guard activity

The current native-model workload includes the longer elapsed/execute policies
and BD Control's 32 ns parent ACK guard on both edges. Its 43-instruction firmware
wake executes 11 complete ACK cycles: 11 rising and 11 falling edges, totaling
704 ns of accumulated guard wait. A diagnostic 1 ps override of that guard leaves
all 27 ordinal wake windows unchanged in duration and fast/work clock counts.
The wait overlaps other work in this workload; it must not be added again to the
measured wake duration. This comparison does **not** authorize removing the guard.

| Native-model wake | BD work edges | Click work edges | BD duration, µs | Click duration, µs |
|---|---:|---:|---:|---:|
| Maintenance | 24 | 19 | 3.147 | 3.064 |
| ADC sample | 217 | 214 | 18.439 | 18.189 |
| Firmware, 43 instructions | 3,257 | 3,212 | 271.775 | 268.024 |

The mapped parent guard contains 28 DLYD cells, one AND and one reset inverter.
At representative TT 3.3 V, 0.1 ns input slew and 0.01 pF table load, its active
input-capacitance plus cell-internal energy is about **17.05 pJ per rise/fall pair**,
or **188 pJ per firmware wake**. Its listed-state TT leakage sums to
3.205–3.254 nW. These are explicit component estimates: wires, upstream driver
internal energy, actual distributed slews, oscillator activity and whole-chip
power are not measured. The static reset inverter contributes leakage but no
switching energy during these wake windows. A mapped 32 ns model guard does not
have a constant physical 32 ns delay across PVT.

`PhysicalEstimateSpec` observes both the actual guard source and output edges,
checks their exact modeled separation, rejects overwritten/pending source edges,
and requires complete matching returns before oscillator shutdown. The reporter
compares generated RTL, models, chip files, contract and file lists; only the
reviewed override and corresponding monitor expectations may differ. Negative
controls reject changed firmware/RTL/harness, unmatched windows, absent evidence,
lost edges and one-edge-only delay accounting.

The first bypass attempt failed `ACK_ACTIVITY_RISE_DELAY`: the general test
harness emitted a `dut` override while the on-chip fixture requires `dut.soc`.
That failed evidence remains in `build/ack-activity-bypass-r1.log`. The corrected
harness applies the exact targeted override; production RTL is unchanged.
Final normal tests pass 2/2 in `build/ack-activity-current-r2.log`, diagnostic BD
passes 1/1 in `build/ack-activity-bypass-r3.log`, and four Python reporter controls
pass. `build/ack-activity-report-r2.json` hashes the compared exports and inputs.
Fresh independent review verified the 352 export files and requested stronger
source-edge completeness and matching checks; both were implemented and rerun.

## Click ordering

Click already has a native 32 ns `acknowledge_guard` in its standard update
stage. A common fire event drives the payload and input-phase registers; the
phase register's Q then traverses that ACK guard. There is no four-phase adapter
and no additional parent guard is required merely for symmetry with BD.

The physical obligation is earliest phase capture plus phase CLK-to-Q plus
ACK/return propagation **after** latest payload capture plus hold, measured from
the same fire event for both ACK polarities. A common source wire alone does not
prove the ordering. The conditional retention tools measure this local inequality
on their specific graph; new bounded trees need fresh per-corner measurements.
Payload/phase pulse widths, retrigger/self-feedback, upstream source reuse,
reset, mismatch and extracted wire RC remain separate qualification gates.
