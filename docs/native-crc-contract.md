# Native CRC context and completion contract

The corrective A2 implementation replaces four full `ControlToken` CRC stores
with one 32-bit result store in each native Control implementation. The separate
`FourPhaseCrc32` and `ClickCrc32` factories instantiate their respective public
library stage directly; they add no wrapper, periodic clock or payload owner.
The shared `Crc32Command` is a wire schema containing the architectural CRC,
loader word and pending flag. A2a/C2 is digitally verified; this document does
not certify physical timing.

## Arithmetic and architectural ownership

At elaboration, each implementation builds the fixed reflected CRC32 linear
transform for polynomial `0xedb88320`. A word is consumed least-significant byte
first, without final complement. Runtime hardware consists of XOR reductions
and the pending bypass. The result is `crc` when no loader word is pending.

The existing update stage retains the full command result while its unbuffered
fork sends the public reply and supplies the feedback context. Only the CRC
candidate travels through the new arithmetic stage. Every candidate starts
from the architectural CRC, including when other commands execute while a
loader word is pending. Only an accepted `Stored` transition commits that
candidate and advances `received`; duplicate completions remain inert.
Host/MMIO validation, programming lock, image state and watchdog reset semantics
are unchanged. Full-width host fields remain validated before use. Retained
length/entry/count narrowing is a separate change requiring capacity tests.

## Native rendezvous

Two public two-input C-elements preserve context ownership. They are described
in the export contract as `crc_context_request` and `crc_context_return`.

| Boundary | Inputs | Meaning |
| --- | --- | --- |
| State request | Retained context request, CRC result request | The next state can capture the context and its corresponding candidate together. |
| Context acknowledgment | State input acknowledgment, CRC input acknowledgment | Context can retire only after state capture and arithmetic ingress acceptance; BD return also waits for both inputs to return low. |

The state input takes ordinary fields directly from the retained update output
and `pendingCrc` from the CRC result store. State acceptance acknowledges the
CRC output. The context acknowledgment feeds the fork's feedback branch; its
other branch still waits for the public reply consumer. Thus a reply stall
cannot allow the next update to overwrite the context.

For BD, a falling state acknowledgment alone is insufficient to release a
context. The CRC ingress must finish return-to-zero before a new request can
arrive. For Click, each C-element waits for both inputs to match the new phase,
including phase zero. There is no four-phase conversion or iteration parity.

Control, its result store and rendezvous are POR-owned. Watchdog recovery is an
ordered Control command, not a local reset of an in-flight loader operation.
POR discards the in-flight feedback and reinstalls cold state. Tests identify
actual payload capture pins from exported metadata, rather than using a stage
request as a proxy for storage.

## Verification and physical limits

`AsyncCrcSpec` exercises the exact production stage with an independent serial
oracle: zero and every one-bit input basis, full-width random inputs, pending
bypass, held results, earliest legal source reuse and POR. `AsyncControlSpec`
retains its independent Java CRC32 image oracle, queued recovery, repeated
Stored, loader/lock/MMIO checks and cold-state checks after POR. Its former
four-stage POR trigger now targets the sole stage's actual capture before
result publication. `AsyncCrcControlSpec` binds actual capture pins and separately
holds result offer, state acceptance, CRC ingress return and public reply. It
covers queued Stored, duplicate Stored, exact accounting and POR, including both
Click phases and BD's independent falling return. All 15 fixtures and 45 seed
runs pass. The actual rendezvous mutation campaign passes 27 original replays
and rejects 27 C-element input faults at their exact intended fatal sites, with
unchanged testbenches. The composed functional/physical runs cover 230 distinct
ScalaTest cases; 500 Python tests and all four strict SoC exports pass.

Candidate comparison against `7bb7b71` selected the narrow whole-word stage
over both a wide whole-word stage and a narrow four-byte loop. It removes
1,316 duplicated payload bits per variant (four 337-bit stores become one
32-bit store). Mapped Control area changes from 0.332175 to 0.206011 mm² for BD
and 0.398618 to 0.230634 mm² for Click. Fresh production maps match the selected
candidate's complete cell connections exactly; source-location aliases are
excluded from that comparison, not hardware. Total logic area excluding SRAM
falls from 3.102377 to 2.975227 mm² BD and 3.915477 to 3.748168 mm² Click.
Ordinary mapper variation outside Control remains separately accounted.
Portable periodic storage remains 6,000/6,001 bits; enabled-policy physical
exports remain 6,010/6,011 bits. All 27 matched wake windows per variant retain
identical effects, edge counts and duration. Mapped leakage is a listed-state
estimate, not measured reachable standby power. Exact source, export, cost,
activity, controls and independent review are bound by
`build/async-crc-reduction/final-evidence-r1.json`; see the detailed
[measurement record](native-area-reduction.md#a2a-narrow-whole-word-crc-feedback).

The candidate whole-transform paths measure 16.025 ns BD and 16.022 ns Click
across the pinned corners, exceeding the unchanged 10 ns data budget. The old
CRC path also exceeded that budget. Arithmetic and handshake simulation do not
qualify either implementation physically. Complete request/data alignment,
state-capture setup/hold, both rendezvous returns, reset distribution and routed
load/slew still require qualification. No periodic staging or timing waiver is
introduced by this reduction.
