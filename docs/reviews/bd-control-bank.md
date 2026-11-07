# BD Control bank review

Independent review: no blocking findings remain. This is batch 3 of the
BD-first area redesign; Click RTL and the external ABI are unchanged.

Control now retains 252 architectural bits, 68 effect bits and a three-bit
transaction kind. It removes the full-state FIFO/Join/reply copies and commits
CRC only on Stored using the retained loader word. The closed banks prevent
transparent feedback. Guarded input ACK and publication preserve operand and
reply lifetime; the next capture waits for full reply return.

Review found two ordinary frame-selector FFs and a shared Host decode driving
loads outside their Liberty tables. The default repair now branches only their
data consumers, leaving native control branches and original Q/port aliases
direct. It repairs FF data before resizing and residual combinational data after
resizing. Full-graph, protected-leaf and direct-control checks pass after final
serialization. Negative tests catch forbidden branch rewiring and missing load
metadata. An unnamed-wire serialization collision was caught by graph proof and
fixed with explicit unique names; the rejected output remains in build evidence.

Verification:

- Focused Control/CRC tests: 42 pass, including actual capture, retained-word CRC,
  duplicate Stored, interleaving, held replies and POR at ownership boundaries.
- Fast CI: 387 Python and 225 Scala tests pass. Later repair-tool changes pass
  the current Python gate separately (397 tests); Scala RTL did not change.
- Affected extended chip suites pass. The first activity probe failed to compile
  after the native ACK instance moved; its binding was updated without changing
  its oracle or deadline, and both activity cases pass.
- Generic boot directed tests: seven pass. Full-capacity primary and external
  golden fallback both pass (333.860569 / 953.315969 ms in the digital model).
- Generation audit, RDC, mapping/repair graph proofs and recipe audit pass.

Final local timing uses the production repaired map, five corners and two input
slews. All 320 bank inputs are covered from 1,414 source roots, including CRC.
After 20% two-sided engineering derate and 2 ns residual, source setup is at least
+89.802 ns, capture-to-command-ACK +36.271 ns, publication-after-data +66.234 ns,
and capture high/low +37.704 / +39.951 ns. Same-event feedback hold is +0.958 ns
against the Liberty aperture. All 514,880 sampled arc checks are in table range.
Primitive-local capture latency/spread is at most 2.085 / 0.257 ns; full parent
root latency/spread 3.101 / 0.665 ns is charged in ordering bounds.

Evidence: `build/bd-control-bank/timing-final-r2/summary.json`, `map-r3`,
`area-r3.json`, `clocks-r3.json`, `ordinary-data-production-r3`, the focused and
full-boot logs, `build/bd-control-bank-ci-r1/receipt.json` and
`build/bd-control-bank-python-r3/receipt.json`. Failed and superseded runs remain.

Flat logic is 1.531099 mm²; hierarchical mapped/repaired logic is
1.611951 / 1.787644 mm². Periodic sinks are unchanged from batch 2.
The firmware wake adds one modeled work edge (4,138 to 4,139); it still meets
its original deadline. See the ledger for cumulative costs and guard area.

These results are local zero-wire-RC qualification, not tape-out signoff.
Whole-chip electrical/noise/reset closure, extracted min/max RC, statistical
mismatch and complete primitive-internal transition qualification remain open.
The pre-existing Housekeeping periodic qualifier timing failure remains open.
The owner adapter does not constitute a new per-owner period-invariance campaign;
existing generic negative controls remain separate.
