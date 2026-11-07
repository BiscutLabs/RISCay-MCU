# Native CRC and loader completion

Both independent implementations use reflected CRC32 polynomial `0xedb88320`,
least-significant byte first, with no final complement until image validation.
The fixed GF(2) XOR transform is constructed at elaboration. The architectural
result and `received` advance only when an accepted `Stored` completes a pending
word. Duplicate Stored commands are inert. Full-width host validation, image
compatibility, lock, memory masks and watchdog retention are unchanged.

## BD: committed CRC in the architectural bank

The BD area rewrite uses [one closed Control bank](native-control-bank.md).
`loaderWord` and architectural `crc` remain there while programming is pending.
Stored computes the next CRC from that pair and captures CRC, received count
and cleared pending together. Other admitted commands cannot replace the pair.
Neither the Stored command's incoming frame nor a later host selector supplies
the operand. POR aborts the operation; ordered application reset preserves
accepted programming effects and the lock/image.

There is no BD speculative candidate register, CRC stage, feedback FIFO or CRC
rendezvous. One native transaction controller captures the state/effects banks,
then acknowledges the retained command and publishes the closed result. Full
reply return precedes the next capture. At the reference 2 KiB capacity this is
252 state bits, 68 effects and three kind bits. Counts/entry fields remain sized
from capacity after full-width validation. The independent `FourPhaseCrc32.stage`
is retained for arithmetic/protocol verification; production Control uses its
pure `compute` transform directly.

The bank's Stored setup path includes the complete CRC/decode cone. Same-event
state/effects feedback hold, latest capture versus source ACK/publication, pulse
width and full rearm are separate obligations. An identity-only timing check on
the three kind bits cannot qualify the bank. See the Control contract for the
current local evidence and routed/reset obligations.

## Click: retained candidate and native phase rendezvous

Click retains its independent whole-word CRC stage. Its update result holds
context while the unbuffered fork supplies the public reply and feedback.
Each candidate starts from architectural CRC, including commands interleaved
while a loader word is pending. Only Stored commits the candidate.

Two public two-input C-elements join retained context with CRC result request,
and state input acknowledgment with CRC input acknowledgment. They wait for
both inputs to match the new phase, including phase zero. The state captures
ordinary fields from the held update result and `pendingCrc` from the CRC result
store. A public reply stall cannot permit context overwrite. No four-phase
adapter or periodic clock is introduced. Control, candidate and rendezvous are
POR-owned; watchdog recovery remains an ordered command.

## Verification

`AsyncCrcSpec` compares the production transform with an independent serial
oracle over the complete linear basis and random full-width inputs, bypass,
held results, earliest source reuse and POR. `AsyncControlSpec` uses independent
Java CRC32 expectations for multiword images, every committed word, full-capacity
accounting, discarded host bits, lock, interleaved commands, duplicate Stored
and reset. Capacity cases include non-powers of two.

`AsyncCrcControlSpec` retains Click's original capture/rendezvous tests in both
phases. BD monitors the actual state/effect/kind captures, overwrites the source
frame only after input return, offers a next command during a held reply, and
stalls the surviving request/publication/ACK-return boundaries. Five POR points
span pre-capture, kind closure, bank capture, publication and return. The old
BD CRC-rendezvous-specific observations are replaced by the corresponding
retention and exactly-once bank obligations; those deleted gates are not
recreated in production. Existing oracles, delays and deadlines are retained.

The earlier A2/A2b stage reduction, historical widths, maps and mutation evidence
remain in [the area study](native-area-reduction.md#a2a-narrow-whole-word-crc-feedback)
and [A2b review](reviews/loader-metadata-a2b-completion.md). They do not qualify
the current BD bank. Current measurements belong in the [area ledger](area-ledger.md).
