# Experimental native SRAM byte owners

The separate experimental BD and Click owners drive one fixed GF180 1 KiB macro
through a native byte transaction. No production SoC or service instantiates
them. This is an isolated digital experiment; the production SRAM controller,
word loops, loader, reset coordination and physical catalogues remain unchanged.

BD and Click own their separate control state. They share only request/pin
schemas, explicit digital model parameters and verification. The Click data
path uses native phase histories and public event captures; a raw public Mutex
arbitrates persistent launch and stop requests without a four-phase payload
wrapper. The grant commits one byte. Source ACK follows actual pin capture and
its declared hold interval. A committed macro cycle completes before result
publication, and held replies leave CLK low/CEN inactive. BD retains its result
taken state through publication return and waits for independent request/result
returns. Click keeps independent accepted-input and published-output histories.

Stop is persistent until coordinated rebase. A stop winner permits no new byte;
a prior launch winner completes its byte and result drainage. Ordinary idle and
disabled bytes cannot lower actual CEN. Source payload/history and the native
owner must remain powered until joined source/electrical quiescence. A parked
unaccepted offer can cancel during coordinated reset without a fabricated ACK.
Old contenders and channel phases must clear before reset release/rearm, and
grant low must be observed before contender reuse. The fixture's inherited
`reset` is bootstrap or joined-quiescent reset, not valid-rail raw POR or watchdog.

The maintained `AsyncMacroByteOwnerSpec` emits fresh fixtures and runs all 76
cases through `tools/check_macro_byte_owner.py`. The cohort contains 20 positive
cases, 54 exact-fatal controls and two deliberate A[9]-monitor omission witnesses.
The witnesses validate the checker and are not owner passes. Each full positive
profile drives 601 offers: 599 commits, 597 enabled macro edges, two disabled
operations and two parked offers. It checks all byte values, every A/D polarity,
CEN/GWEN polarities, 0/512/1023, both Click phases, independent BD returns, held
results, earliest permitted source reuse, ten actual-event stop offsets, four
finite arbitration policies, opposing delay choices and a 1 us unresolved sample.

Actual macro/capture pins remain monitored during valid-rail stop. Exact controls
cover setup/hold, macro high/low/period, early read capture, capture pulse widths,
source/pin reset, stale rearm, post-stop admission, CEN idle/disabled glitches,
consumer-visible held-result corruption, BD RTZ payload retention and the former
duplicate-publication return bug. Result data are checked continuously through
delivery and at actual ACK; BD also retains the obligation through full RTZ.
WEN is checked as the constant byte mask; impossible dynamic coverage is not
invented. SRAM contents retain the existing uninitialized simulation behavior.

## Running the experiment

Use Python 3.10 or later and Icarus Verilog on PATH. `PYTHON`, `IVERILOG`, `VVP`
and `IVERILOG_BACKEND` can select installed tools. The backend directory must
contain the active Icarus `ivl` compiler components; the runner passes it with
`-B` and hashes those files. Missing or ambiguous tools fail the test.

```text
python tools/test_macro_byte_source_binding.py -v
sbt "verification/testOnly riscay.AsyncMacroByteOwnerSpec"
```

Every run gets a fresh ignored directory under `build/experimental-macro-byte-tests`.
The emitter captures all required sources, resolved runtime class-file identity
and the resolved library JAR before generation; it checks them again afterwards.
These are classloader resource files, not an attestation of already-loaded JVM
bytecode or a cryptographic proof of compilation. A fresh serialized compile and
emission are required. The used SRAM class families explicitly include
`SramByteRequest`, `Gf180Sram1KiB` and its anonymous IO Bundle, and the
`SramInventory` object/module pair; extra family members fail closed. Source
timestamps must precede generation and their compiled classes. Both exact
export manifests bind the runtime cohort. The Python runner verifies this
identity before simulation and again at completion, including fixed SRAM asset
hashes, model bytes, emitted RTL, ABI and probe hashes. Rebuilding or editing the
inputs invalidates old evidence; it does not silently rebind an old export.

For a standalone fresh export and replay:

```text
sbt "verification/Test/runMain riscay.EmitMacroByteFixtures build/native-byte-EXPLICIT/exports"
python tools/check_macro_byte_owner.py build/native-byte-EXPLICIT/exports build/native-byte-EXPLICIT/campaign
```

The output directories must not exist. `--case` and `--variant` are debugging
subsets and cannot produce complete-campaign status. Each case records the
actual source, command, binary and output hashes; controls must fail at the named
assertion source line. Unknown owner roots, extra/missing primitive IDs, empty
cohorts, changed source/model/RTL, unrelated failures and failed controls are
errors. The dedicated inventory parses the actual owner and fixture roots, requiring
exact instance names and types: every owner instance matches a declared public
primitive, and each fixture has exactly its declared owner and fixed macro.
Both roots reject ordinary procedural storage. Compiled file/module sets and
public resource types must match, including no extra undeclared child. Only the
known uncompiled `ref_<top>.sv` reference is excluded. The parser accepts the
current firtool wire/assign/direct-instance dialect and fails closed on other
syntax; a changed dialect requires review. The resolved JAR and pinned macro
asset checks independently bind the allowed public cell/model bodies. It grants no production inventory or
physical mapper exemption.

## Limits before production use

Scalar macro timing constraints are conservative maxima over the five pinned
Liberty tables. Receiver apertures and guard parameters are finite digital
choices; they are not measured physical cell/route bounds. The public Mutex
model neither bounds physical contention nor implements a qualified analog
arbiter. A schematic/circuit proposal elsewhere does not qualify this owner's
complete pulse, capture, reset, slew or load paths.
The approved library work is available in [chisel-async draft PR #4](https://github.com/BiscutLabs/chisel-async/pull/4).
It remains unqualified and does not change this experiment's pinned dependency.

Before production integration, reconcile byte-grant commitment with interrupted
POR semantics; prove retained source/reset coordination and no extra word lanes;
add two-macro bank and native word fixtures; run SRAM, loader, watchdog, sleep,
firmware and strict exports; measure all complete paths over the required
physical corners; and obtain a fresh independent review. No area, leakage,
wake-energy or timing-closure claim follows from the isolated digital tests.

## Integration evidence

The maintained cohort at
`build/experimental-macro-byte-tests/native-byte-12304756663162904872/`
passes all 76 cases, with source/runtime/export identity checked before and after
execution. Its ScalaTest wrapper passes, and all 47 binding helper tests pass.
Evidence and fresh closing review are retained in
`build/async-sram-byte-integration-r2/`.

The first maintained wrapper run failed before emission because ujson encoded
Scala Long timestamps as strings. The corrected wrapper writes explicit numeric
millisecond values after checking exact JSON-number range. Source freshness and
runtime checks are unchanged. Both the failed log and the successful fresh run
remain available as `maintained-campaign-r1.log` and `maintained-campaign-r2.log`.
The earlier prototype compilation, ownership and control failures also remain
under `build/async-sram-byte-prototype/`; their repaired cases are in this cohort.
