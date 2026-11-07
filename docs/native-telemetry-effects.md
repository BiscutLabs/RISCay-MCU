# BD Telemetry compact effects

Batch 4a, following Control commit `852e93c`. Functional, generation/RDC and
local bank/reader timing checks pass with independent review. Click and shared
reply schemas remain unchanged under the BD-only user override. See the
[review](reviews/bd-telemetry-effects.md) and [area ledger](area-ledger.md).

Telemetry retains one closed application/GPIO EventRegister bank, its optional
closed software-sample bank, the accepted command in the existing Join, and the
seeded feedback credit. The update stage and fork carry only kind (2 bits) and
recovery (1 bit). The bank D inputs compute the existing transition from the old
closed banks and the retained command, through passive whole-transform allowances.
There is no second architectural owner, periodic clock, synchronizer or new crossing.

The reference seven-GPIO/six-word configuration removes the 259-bit candidate-state
reply in favor of three bits: mapped native payload storage is 515 -> 259 bits.
Hierarchical mapped/repaired logic is 1.598560 / 1.767953 mm², excluding SRAM;
periodic sinks remain 3,019. Other configurations
retain their declared words and 111-bit software-sample records; report those
actual inventories separately.

## Capture, reset and atomicity

- Application/GPIO capture remains qualified commitAck from the real work-clock
  receipt. Cancellation can revoke that capture without revoking an accepted
  software sample, which still captures on ordinary reply ACK.
- POR clears all banks and phases. Ordered ResetApplication clears application
  words and preserves the existing GPIO-retention option and SPI-pin release.
  It does not clear last-good software samples. Failed samples increment sequence
  and update status while retaining last-good value/time, exactly as before.
- GPIO pads read only the closed bank. One accepted write produces at most one
  transition per changed pin. Existing raw-reset pad isolation is unchanged.
- The acceptance edge still sees the whole old bank. Existing returning/bankReady
  qualification inhibits moving-bank reads; host readStart snapshots then select
  the whole committed bank. Snapshot storage, event arbitration and ABI are unchanged.

## Operand lifetime and return

Services freezes mmioCommit, its saved application index and software timestamp
through the existing sender/outstanding/draining gates. The Join then owns the
accepted native operand. Its output ACK is C(update input ACK, reply ACK): it rises
only after effect capture and actual receipt acceptance, and falls only after
both ACKs return. The long-hold operand therefore cannot become transparent while
the bank still needs the old command. The existing bank-completion C-element and
feedback guard gate reuse; a later offered command cannot replace the old operand.

The receipt's authorization bit and ordinary ACK are separate registered outputs.
Their physical skew must be included even though both launch at the accepting edge.
The feedback guard does not establish same-event bank-Q -> bank-D hold.

## Required evidence

Measure original command/bank operands to each bank D, actual qualified/ordinary
capture leaves, self/cross-bank hold, source release and bank-settle-to-credit reuse.
The new register_aperture and optional sample_aperture describe their separate
capture events; generic identity-stage timing alone cannot qualify these transforms.
Keep the existing periodic-reader qualifier checks. A production configuration
without software samples cannot qualify the optional sample-bank implementation.

Run AsyncTelemetrySpec explicitly, existing AppRegisters/snapshot/admission,
publication/recovery, sample-age and sleep tests, then the normal CI/export/RDC gate.
Preserve all state oracles and deadlines. Measure mapped/repaired area, guard/DLYD
area, sink inventory and wake activity against the immediate parent. Same-corner
local timing is required; extracted min/max RC remains the separate tape-out gate.

Local composition covers both the production 206-bit application/GPIO bank and
the optional 111-bit software bank at five corners and two slews. Setup is positive
even with zero receipt-cycle credit. Command reuse and capture pulses include
only one guaranteed existing 50 ns work edge; no new timing stage is introduced.
Minimum feedback hold is +1.085 ns in production and +0.838 ns for the optional
software bank. The engineering derate is 20% two-sided; it is not measured mismatch.
The software map retains an unrelated 2.578 ns rebase-Q slew violation against
the default 2 ns electrical target. Local cones are fully in table range;
whole-chip electrical/reset and routed min/max-RC qualification remain open.
