# Reusable Mutex contract and experimental GF180 cell

The missing piece is a physical implementation contract and GF180 binding for
the library's **existing public two-request Mutex**. The input/output API already
fits this use. A new MCU-specific reset sequencer, byte owner or payload channel
does not belong in the library for this first addition.

The Mutex resolves two independent persistent requests into mutually exclusive
grants. Here those requests represent launching a byte and closing admission for
reset. The SRAM pins remain controlled by the MCU's separate native owners.
Using this raw control primitive does not convert Click's payload/phase path to
four-phase. The existing `TwoPhaseArbiter` wrapper does perform that conversion
and is unsuitable for this native Click owner.

The proposed reusable work has three parts:

1. **Complete the public primitive's physical-use contract and tests.** Specify
   persistent requests, grant retention, request release followed by observed
   grant release before reuse, safe local-reset/rearm preconditions, output
   electrical limits and unresolved-state behavior. Keep `RESOLVE_FS`,
   `RESOLVE_MAX_FS`, policy and seed explicitly simulation-only. They are neither
   physical delay targets nor fairness/priority/maximum-resolution guarantees.
   The primitive does not track epochs: owners clear/rebase old requests before
   reset release. Add tests that make these obligations clear.
2. **Provide an explicit technology implementation and evidence behind that
   same interface.** A GF180 arbitration core needs metastability containment
   before its outputs become usable grants, characterized input/output loading,
   release behavior and reset behavior. Preserve it as a recognized physical
   cell/recipe, not synthesized priority logic or an uncharacterized Boolean
   feedback replacement. Record schematic/layout/model hashes and separate
   uncontended/release timing from unbounded contention resolution. A finite
   SPICE sweep is evidence within a declared reliability envelope, not proof of
   zero metastability risk.
3. **Integrate the reviewed binding into the MCU tooling separately.** Its
   current GF180 mapper lacks a Mutex recipe, and its native-state checker does
   not classify Mutex. Add exact binding/classification tests when the physical
   recipe exists. Keep ordinary clocked state rejection and unsupported physical
   cases intact. The library supplies the generic contract/collateral; MCU-specific
   owner IDs, macro timing and reset coordination remain in RISCay-MCU.

No new Scala I/O is required initially. If circuit review proves an extra pin or
semantic distinction necessary, propose that specific API change before making
it. Do not silently reinterpret the current `reset` port or insert a private
primitive.

Meanwhile, separate BD and native Click byte owners can be developed and tested
in ignored build fixtures using the unchanged public finite Mutex model. The
experiment must hold pins inactive during unresolved arbitration, retain source
payload and phases, survive stop through joined quiescence and check actual macro
and capture pins. Those tests can expose logical errors now. They cannot qualify
the missing physical cell, and they do not authorize replacing production SRAM
controllers before the measured pulse/reset envelopes pass.

The approved library work is implemented in [draft chisel-async PR #4](https://github.com/BiscutLabs/chisel-async/pull/4), at commit
[`ff128841`](https://github.com/BiscutLabs/chisel-async/commit/ff128841315d6fe83d57881b092702c431a50da6).
It adds the ownership/reset contract, digital tests and an experimental GF180
schematic cell. The public API and digital model remain unchanged. Independent
review and bounded digital/SPICE campaigns completed; the earlier asymmetric-load
circuit failure is retained in its evidence.

This is **not a qualified physical binding**. Layout, extracted parasitics,
Liberty characterization, noise/mismatch/aging, reliability/MTBF and routed
integration remain open. The draft is not merged. The MCU dependency and generic
GF180 mapper remain unchanged, and production self-timed SRAM access is not
accepted by this library result. The MCU integration described in item 3 remains
a separate step after physical qualification.
