# BD SRAM word loop

BD-first implementation of batch 1 in the [area action plan](native-area-action-plan.md).
Click keeps its independent four-lane implementation. The CPU/loader ABI, fixed
SRAM models, physical macro clocks and application-reset lifetime are unchanged.

## Ownership

Each memory owns one compact request (word address, write, data, mask), one
32-bit assembly bank, two-bit lane and four-bit closed handshake history. A
three-bit sequencing token circulates through a seeded FIFO and step stage.
Only control circulates; the word payload does not. All storage is native.
At reference capacities the declared payload/control latch/FF width is 90 bits
for program and 89 for RAM, excluding C-element keeper state. Verify mapped
storage and area independently; these widths are not a physical area result.

The states are idle, first byte, subsequent byte, capture, advance, last-byte
return, publication and retirement. First captures the request and clears
assembly/lane. Byte issue waits for both request ACK and response REQ. Capture
assembles the byte, withdraws request and acknowledges response. Both external
return levels must fall; advance/last then wait for the actual guarded response
ACK to fall. The lane increments only on the next issue's publication. After the
last return, the word response remains held until acknowledged and fully returned.
Input ACK remains asserted until the input request and word response return.

Each memory reuses one byte receipt/sender pair. The clocked macro controller
keeps falling-edge A/D/CEN/GWEN launch, rising-edge access and full-cycle Q
capture. It performs four completions, including CEN-disabled write lanes.
Production has one port and no lane tag/priority arbitration. The standalone
bank fixture retains the optional four-port interface to preserve its existing
range, pin and reset tests. Click uses the schema's four-port default.

Full-width capacity and discarded-high-bit assertions run on actual word
admission before native address truncation. The macro boundary separately
asserts its admitted byte address is within the configured capacity.

## Reset and return

POR clears native ownership and aborts an interrupted word without replay.
Application/watchdog reset does not reset this owner or the macro contents:
accepted accesses finish, and existing Source/Return owners suppress stale CPU
responses while retaining committed programming effects.

Return retains its own word copy. The word-to-Return channel returns independently
of Return's later publication. Access may require Return idle for new admission,
but `effectsDrained` deliberately excludes Return idle to avoid a circular wait.
Sleep/wake demand continues to include byte, command, capture and word drainage.

## Timing and verification obligations

All four external handshake levels come from closed history. The 32 ns model
guard is a **relative** capture-to-publication/ACK allowance, not a characterized
physical delay. Each request, lane, assembly and history transform has a passive
allowance and explicit capture aperture. Setup/hold must include source launch,
mode decode, self-feedback, actual capture-tree spread and source release.
First-byte request additionally covers request/lane Q and the byte mux; word
publication covers the final assembly capture. Full return precedes reuse.
No periodic clock enters this loop and no per-bit allowance maps to physical cells.
The byte bus itself is ordinary combinational selection from closed storage,
accepted only through the existing receipt/fire-qualified macro boundary. An
experimental passive byte marker was removed because that audit deliberately
admits only native capture sinks. Removing its 10 ns digital model delay removes
no physical cells and is not evidence of a physical latency improvement.

The reusable loop removes storage/crossing copies, not the four physical byte
transactions. Record actual work edges and duration; lost overlap between old
lane return and next issue may offset reduced transport. Keep existing deadlines.
The small loop's controller/delay share can exceed the skill's percentage target;
the justified boundary is one word credit and one reusable byte handshake, not
another payload pipeline. Whole-owner and whole-chip area gates remain decisive.

Use AsyncSramSpec's independent byte oracle, all masks and addresses, random
native delays, held replies and POR at every byte. SramSpec retains actual macro
write counting, pin aperture monitors, watchdog/POR drainage, full capacity and
clock stops. The stopped-clock fixture settles its backpressure input before
reenabling the clock; changing both on a scheduled clock edge was a testbench
sampling race. No functional expectation, stopped interval or deadline changes.

The [area ledger](area-ledger.md#bd-sram-word-loop-rewrite) and
[independent review](reviews/bd-sram-word-loop.md) record mapped/repaired area,
actual activity, verification and measured local setup/hold/return/pulse bounds.
Full-capacity primary and golden boot pass. This contract and the local checks
do not establish routed physical qualification.
