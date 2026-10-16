# A2b loader metadata: paused review checkpoint

Historical checkpoint preserved below. The user subsequently authorized
finishing this WIP PR; see [the separate completion report](loader-metadata-a2b-completion.md)
for successor validation and measured scope. The interrupted run and this
checkpoint's incomplete status are not relabeled as passes.

Paused at the user's request on 2026-10-15. **This is an incomplete review
checkpoint, not an accepted migration item or physical qualification.**
The accepted MCU baseline is `64e6211`; this checkpoint adds the loader-width
candidate and this handoff. The broader corrective migration remains unfinished.

## Change for review

Both independent native Control implementations retain image length and received
byte count at the configured program capacity, including the full-capacity value.
Entry offsets use the width of capacity minus one. At 2 KiB these widths are
12/12/11 bits. Full 32-bit host BEGIN length/entry and WRITE offset fields are
validated before any narrowing. Entry MMIO readback explicitly extends the
offset before adding the program base.

Only an accepted outstanding `Stored` commits CRC and advances received bytes;
duplicate completion remains inert. Watchdog recovery preserves accepted loader
accounting, image validity and lock. Command/frame widths, addresses, public ABI,
native handshakes, reset ownership and timing budgets are unchanged. No clock or
protocol adapter is added.

At 2 KiB, state/token/reply widths change from 305/337/376 to 244/276/315.
The expected reduction is 183 native storage bits and 40 periodic bits per
variant. The latter comes from two mirrors; the entry mirror was already
optimized away. **The candidate has not been mapped, so these are not measured
area, leakage or energy savings.**

Review the independent implementations, capacity-derived shared schemas, explicit
MMIO extension, full-width host validation, and updated strict-checker layout
derivation. Checkers derive capacity from the validated SRAM inventory rather
than accepting an observed bus width as its own specification.

## Completed verification

- 536 Scala tests across 36 suites passed: 34 focused loader/CRC tests, 496 affected
  regressions, four physical-policy/export tests and two activity tests.
- 709 Python tests passed.
- Twelve loader cases cover both protocols at 4, 12, 1024, 1028, 2048 and 3072
  bytes. They exercise full-capacity images, every discarded host bit, invalid
  BEGIN preserving an image, maximum entry/offset, reset, lock and duplicate
  completion, with independent literal layouts and Java CRC32 checks.
- CRC rendezvous controls passed 27 original replays and rejected all 27 mutants
  at their intended first fatal assertion. Original testbench oracles are intact.
- Independent review verified the exact 18 implementation/test files, all 436
  source hashes, 481 compiled classes and 595 fresh fixture directories. It also
  independently reviewed the completed CRC campaign.

The four strict export runs were **interrupted at the user's pause request**.
Their retained receipts therefore report `FAIL_OR_INCOMPLETE`, with all four
cases `FAIL` after their owned simulator processes were stopped. This is neither
a strict pass nor evidence of a design assertion failure. No mapping or timing
measurement was started for this candidate.

A build-only wrapper initially confused `vvp.exe` with `vvp.conf` and `vvp.tgt`
because it matched filename stems. The corrected executable selector retains
hash checks on all runtime files and passes 47 controls, including actual-runtime
selection and changed configuration-file faults. The original failure is kept.

## Evidence and resumption

[The compact evidence manifest](loader-metadata-a2b-evidence.json) records local
artifact paths and SHA-256 identities. Full logs, fixtures and prepared scripts
remain under ignored `build/`; they are not included in this Git checkpoint.

| Evidence | Local path |
| --- | --- |
| Fresh regression and generated exports | `build/async-loader-width-production-r1/` |
| Python results | `build/async-loader-width-python-r1/` |
| Independent completed review | `build/async-loader-width-fresh-review-r1/execution-review.json` |
| CRC controls | `build/async-loader-width-verification-r1/crc-controls/execution-r1/` |
| Interrupted strict runs | `build/async-loader-width-verification-r1/strict-r1/` |
| Explicit interruption and original diff | `build/review-pause-2026-10-15/` |
| Reviewed mapping/audit preparation | `build/async-loader-width-measurement-r1/` |
| Reviewed static/timing preparations | `build/async-loader-width-*-aperture-*/`, `build/async-loader-width-transform-preparation-r1/` |

On resumption, inspect the review feedback first. Preserve the interrupted run
and use new output directories. Rebind execution to this checkpoint explicitly:
the old scripts pin the pre-checkpoint parent/source inventory, while this commit
adds review documentation. Do not rewrite old receipts or treat their status as
a pass. Source changes require the affected regression to be rerun.

Remaining A2b acceptance work is strict export completion, graph/held-payload
controls, matched mapping and activity audit, reviewed actual timing inventories
and bounded component screens, final independent review, and current-contract/
checklist updates. Mandatory library campaigns and failure oracles must remain
unchanged. Native source reuse/hold, reset distribution, pulse/electrical limits
and routed min/max timing remain physical obligations even after digital passes.

## Broader handoff

- C1e1 CPU-request payload-copy removal is already committed and pushed in
  `64e6211`. Its accepted mapped logic area is 2.862585 mm² BD / 3.629653 mm² Click,
  excluding SRAM. These are baseline numbers, not A2b measurements or measured
  deep-sleep power.
- Approved Mutex library work is in the separate draft
  [chisel-async PR #4](https://github.com/BiscutLabs/chisel-async/pull/4).
  Its experimental physical binding remains unqualified and is not merged into
  the MCU's pinned library dependency.
- Read-only preparation exists for C1e2's ten smaller receipt payload bits and
  R6's public frame-route primitive replacement. Seven receipt bits have no
  functional mapped consumers; three live role bits need complete retention and
  capture proof. The R6 candidate adds four native control states; no area saving
  is claimed. Neither candidate is applied here.
- A6 feasibility identifies narrower wake/GPIO masks and bounded qualification
  counters. Acquisition statistics retain their existing widths pending a valid
  range proof. These candidates are not implemented or measured.
- Production self-timed SRAM, remaining frame/publication storage, service
  scheduling, guard replacement and reset-tree qualification remain open.
  The separate library `data_delay` mapping proposal still needs approval.

No background migration or measurement should resume until the user requests it.
