# Resetless transient payload and compact command transport

This is a BD-first follow-up to `2c1e3d2`. It preserves the MCU ABI, native
control/reset state, retained architectural banks, and independent Click and
clocked references. The separately reviewed library addition is implemented in
[chisel-async `856fc75`](https://github.com/BiscutLabs/chisel-async/commit/856fc757517e0ff0c1c8fea9f6d7e61ec32d1172)
and pinned by source commit. The MCU adoption is limited to the four POR-owned
I²C frame-bank payloads (4 × 337 bits).

## Library boundary

The opt-in `ResetlessClosingLatch` payload primitive in chisel-async has a
new model identity. Its pins are `closed`, `d` and `q`; it has no reset pin.
It is transparent while open and retains data while closed. Before first capture
and whenever the owning channel is invalid, payload may be unknown or stale.
Unknown enable/data behavior must remain conservative in four-state simulation.
No masking, validity flop, clock or implicit zero initialization is added.

Existing resettable primitives and default constructors retain their behavior.
`PayloadStorage.Resetless` selects the new primitive in BD Stage/LongHold. Seeded
feedback tokens, initialized architectural state, GPIO output banks, reset/phase
state and independent-reset crossings remain resettable. The frame banks are
transient, unseeded payload. Their route, eligibility, busy and handshake state
retain reset; no meaningful reset value is removed.

The generation audit and export/model catalogs register its distinct identity
and native storage enable. Library tests cover unknown startup, transparent and
closed behavior, conservative unknown enables, occupied-owner reset and fresh
post-reset delivery, against the resettable token oracle. MCU tests drive unknown
frame input during idle/reset and retain exact frame, ordering and aperture checks.

Every frame fanout was reviewed: head receipts qualify consumption with the
synchronized request; Services requires a valid descriptor and valid head;
Control masks frame data for non-host commands. The native completion join keeps
the frame until both receipt and native command return. No consumer treats idle
payload as initialized state. POR may discard a frame; application/watchdog reset
does not reset these POR-owned banks. The RDC checker explicitly rejects adopting
resetless storage in an application-lifetime owner until a separate lifetime proof
exists. This batch is not a general reset exemption.

The MCU binding uses GF180 `latq_1` and its own enable tree, without a
payload reset tree. Check real load, setup/hold and capture/ACK composition;
never substitute this cell under an existing resettable model identity. Count
storage-cell, reset-tree and repair-area changes separately. The per-bit saving
is modest; this does not promise to eliminate the full mapped-area gap.

## Work-clock transport

Services stores an accepted MMIO commit as word offset (5 bits), data (32),
application index (6) and application-writable (1). Kind, operation, full-word
mask and fixed address base are reconstructed. Capture requires a successful
aligned full-word store. The index is retained only for offset 52; using it for
other offsets would change Control's later revalidation semantics.

The Control sender stores only the seven variable address bits. Its prevalidation
header still retains operation, mask and alignment bits, so malformed accesses
fault unchanged. A fire-qualified assertion checks the discarded address prefix.
Control's full-width interface and all non-MMIO commands remain unchanged.
Accepted payload persists through application cancellation and full native return;
event clear keeps the same arrival cutoff. This needs no library extension.

Do not delete the Control command sender's payload simply because the CPU still
has a request: independent application reset can revoke that source while the
POR-owned command is in flight. Borrowing requires a complete retention and
reset-coordinator proof. Likewise, removing the memory decision bridge invalidates
the existing one-work-period publication-mask hold credit. Those larger ownership
changes are separate batches, not optimistic substitutions in this one.

Extended verification exposed an existing SRAM byte-receipt latency regression
on the exact parent. The fix reuses the already-reviewed minimal Stored receiver
for the BD byte crossings. No macro cycle, native guard, synchronizer or full
return is removed. Its precise settling/capture obligations and unchanged host
deadline are recorded in [the SRAM word-loop contract](native-sram-word-loop.md).

## Acceptance and remaining obligations

Run affected command/telemetry/reset/boot/firmware and shared regression oracles,
fast CI, all generation audits and both production RDC checks. Obtain independent
review. Map against the parent with identical tools and profile; record flat and
repaired area, native storage, guard/reset distribution, periodic and Services
sinks, and unchanged-or-explained wake/boot activity. Do not count a proposal as a
measured saving or local timing as routed item-17 qualification. The
[area ledger](area-ledger.md) records the measured batch; the
[review record](reviews/bd-payload-transport.md) records tests and actual failures.
Keep routed min/max RC, reset distribution, coupling, mismatch and keeper pulse
retention open. No guard recipe is shortened by this batch.
