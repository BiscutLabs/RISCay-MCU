# BD Control architectural bank

Status: implemented and independently reviewed. Functional, generation/RDC and
local five-corner electrical/timing checks pass. [Evidence and limits](reviews/bd-control-bank.md)
and the [area ledger](area-ledger.md) distinguish this from routed qualification.

Control retains one closed architectural state bank and one closed effects bank.
A three-bit native transaction stage serializes commands. The command sender and
host frame store retain their operands through the bank capture and guarded input
ACK; the next command cannot capture until the previous reply fully returns.
The existing sender captures header and frame selection before raising request
on its following work edge. The frame-head completion join preserves the bank
through actual native command return. The physical source composition charges
source propagation rather than treating a held payload as a zero-delay wire.
The architectural bank is 252 bits at the reference 2 KiB capacity, effects 68
bits, and transaction kind three bits. Capacities continue to determine loader
length/address fields after full-width validation.

POR resets the bank to the existing cold state (CRC all ones). Application reset
remains an ordered command: it does not abort accepted programming work, lose the
image or clear the programming lock. Services retains its existing Control view
and receiving-edge commit. No host ABI, command admission or event cutoff changes.

The [compact transport](resetless-payload-plan.md) retains only accepted-write
fields in Services and variable MMIO address bits in the sender. It preserves
the source lifetime and receiving-edge commit; it does not borrow independently
reset CPU data. Frame payloads use explicitly resetless latches, while their
POR-owned controls and qualified-consumer lifetime remain unchanged. The measured
source composition must use the actual `latq_1` arcs for those frame roots.

Only Stored with loaderPending advances received, CRC and pending together. The
CRC transform uses the old architectural CRC and retained loaderWord, never the
incoming Stored payload. Permitted interleaved commands cannot change that pair;
a duplicate Stored is inert. The old speculative CRC stage, pending CRC token,
state FIFO, Join operand copies and full-state reply latch are removed.

State and effects use public EventRegister storage and passive whole-transform
allowances. Their common capture is the transaction stage's input ACK. A separate
both-edge input ACK guard retains command data after capture; a publication guard
orders reply visibility after the latest bank capture. Neither guard proves
same-event self/cross-bank hold: that is a separate min-path obligation. The
transaction matched request must cover the full Stored CRC/decode cone, not just
the three identity bits in the transaction stage.

Required local evidence: original operand-to-bank setup, self/cross-bank hold,
actual latest capture-to-ACK/publication, source release, single capture and full
rearm, and complete capture-tree distribution at all five corners. Timing
parameters are digital models until the corresponding physical binding is measured.
Routed min/max RC, mismatch characterization and full reset distribution remain
item 17. Tests retain independent CRC/state oracles and original deadlines.

## Source electrical preparation

The frame selector has both data and native frame-completion consumers. The
post-map repair helper buffers only its ordinary data sinks. Original Q nets,
port aliases and control/protected branches remain directly connected. Trees
have at most 16 loads per branch; actual remaining FF loads and buffer slews must
also remain inside the Liberty tables. Fanout count alone proves no timing bound.
The whole-graph proof and a separate direct-control/alias check run after repair.
No register, clock or native primitive is added or altered by this preparation.

The initial map exposed two selector loads outside the source FF table range;
those paths cannot be qualified by extrapolated delay. Single-buffer and
whole-output-tree experiments are retained as rejected candidates. The adopted
preparation splits data fanout only, including mixed data/control roots, and
reports its added area separately. Whole-chip electrical violations, routed RC,
CTS and reset distribution remain independent obligations.

Frame data remains masked for non-host commands: that keeps the complete command
bus stable while a different frame bank may be reused. Removing that mask would
need a different payload-lifetime contract. Its Host-kind decode also drives a
native frame-ACK branch, which the data-only repair deliberately leaves direct.
Ordinary logic is resized first; only residual combinational drivers outside a
same-corner load table receive additional data trees. Reports and graph checks
run on the final serialized netlist. New post-resize wires have explicit unique
names so a later Yosys import cannot collide with its earlier automatic names.

The final local composition covers all 320 bank inputs, including Stored CRC,
from 1,414 real source roots at five corners and two input slews. After the 20%
two-sided engineering derate and 2 ns ordering residual, minimum source setup is
+89.802 ns, capture-to-command-ACK +36.271 ns and publication-after-data +66.234 ns.
Same-event feedback hold is separately +0.958 ns against the Liberty aperture.
No sampled source or feedback arc is outside its load/slew table. These are
zero-wire-RC results; statistical mismatch, routed RC, full reset/noise and
complete primitive-internal transition qualification remain open.
