# Native overhead investigation review

Scope: independent read-only review of the source, existing matched BD/clocked
maps, local accounting scripts and
[the proposal](../native-overhead-investigation.md), against `da27bc8`.
Reviewer: fresh agent `native_overhead_review`.

No blocking findings. The reviewer independently confirmed the mapped area,
native storage/owner decomposition, 3,103 DLYD cells in the six transport owners,
seventeen 200 ns guards containing 2,907 DLYD cells, and 6,273 buffers in fixed
nine-buffer chains. The SRAM sole-credit protocol supports the proposed
iterative reuse without changing the macro clock boundary.

The report incorporates these review qualifications:

- The 715-bit candidate union contains 602 unconsumed bits and 167 constants,
  overlapping by 54. It is not 715 purely unused bits.
- Trace candidates apply to the physical digital-pad export. Verification
  exports still need trace, and changing lane count needs new distribution and
  timing checks.
- Per-owner native accounting excludes ordinary flattened datapath logic and
  counts C-element keeper state separately from latch/flip-flop bits.
- Guard lengths and short buffer chains are investigation targets, not proven
  redundant delays. The existing BD counts are not a new Click measurement.
- Removing protection attributes cannot safely infer asynchronous stage fusion.
  Keep explicit graph/contract specialization and the existing ABI decision
  priority. The evidence path was expanded to remove ambiguity.

Verification was limited to existing native graph/inventory reconciliation,
ordinary flip-flop source attribution, source inspection and document checks.
No RTL, mapping recipe or test expectation changed. No synthesis, simulation
or P&R was launched, and no new physical qualification is claimed.
