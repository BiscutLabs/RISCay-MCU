# Native storage and delay area investigation

Status: **proposal only**, against `da27bc8`. No RTL, mapping recipes, timing
constraints or test expectations changed. This investigation recounts existing
mapped netlists; it does not run synthesis, P&R or simulations. BD is the physical
target. Functional architectural changes would also need an independent Click
implementation, without starting a Click physical campaign.

The main causes are repeated transaction storage and conservative, protected
control recipes. Synthesis is preserving structures that the design explicitly
requires. There are also demonstrably unused payload fields. Removing all
visible dead fields alone will not close the area gap.

## Matched baseline and accounting

The [area ledger](area-ledger.md#clocked-comparison-implementation) establishes
the comparison: identical mapper/library, ordinary flat synthesis, 4,224-byte
generic ROM, 2 KiB program SRAM, 1 KiB working SRAM, GPIO and ADC configuration.
All numbers below exclude the unchanged three SRAM macros, repair, CTS and
routing. Neither map is timing-closed. **The ratio is 3.56x mapped logic area,
not a measured die-area ratio.**

| Cell class | BD, mm² | Clocked, mm² | BD excess, mm² |
| --- | ---: | ---: | ---: |
| Latch/flip-flop storage | 0.714794 | 0.204178 | 0.510617 |
| DLYD delay cells | 0.394455 | 0 | 0.394455 |
| Buffers and inverters | 0.185402 | 0.007868 | 0.177535 |
| Other logic, including native keeper gates | 0.599048 | 0.319788 | 0.279260 |
| **Total** | **1.893700** | **0.531833** | **1.361867** |

Storage explains 37.5% of the difference; DLYD explains 29.0%; buffers/inverters
13.0%; other logic 20.5%. These are disjoint cell classes. Buffer area includes
intentional capture/reset distribution and isolation as well as delay chains;
it is not all removable. Passive data allowances already map to **zero cells**.
BD already uses latches for its pipeline payloads.

BD has 7,473 latch bits and 4,823 flip-flop bits, versus 2,977 flip-flop bits in
the clocked chip. Of BD's storage, 9,229 bits are inside protected native
recipes: 7,473 latches and 1,756 event-triggered flip-flops. The other 3,067 are
ordinary flip-flops. These counts exclude C-element keeper state, accounted
in other logic. Periodic clock sinks remain the ledger's 3,069 versus 2,979,
including SRAM clocks and excluding the separate SDA event.

## Native storage and delay by owner

These are **native recipe costs**, not complete module areas: ordinary
combinational datapaths are flattened across module boundaries. Each native
cell has an exact owner through the retained primitive binding.

| Owner | Stored bits | Storage, mm² | DLYD cells | DLYD, mm² |
| --- | ---: | ---: | ---: | ---: |
| I²C protocol, publication and frame banks | 2,224 | 0.123906 | 563 | 0.042021 |
| Program SRAM word access | 1,079 | 0.052110 | 352 | 0.026272 |
| Working SRAM word access | 1,079 | 0.052110 | 352 | 0.026272 |
| CPU and register file | 1,203 | 0.070743 | 186 | 0.013882 |
| Control / loader / CRC | 1,302 | 0.062879 | 128 | 0.009554 |
| Housekeeping | 676 | 0.039579 | 91 | 0.006792 |
| Telemetry application/GPIO bank | 515 | 0.030298 | 91 | 0.006792 |
| SPI ADC / sample scaling | 546 | 0.029293 | 253 | 0.018883 |
| Elapsed scaling | 458 | 0.022172 | 64 | 0.004777 |
| Program publication source | 3 | 0.000171 | 549 | 0.040976 |
| RAM publication source | 2 | 0.000123 | 370 | 0.027616 |
| Program return | 33 | 0.002463 | 380 | 0.028362 |
| RAM return | 33 | 0.002463 | 380 | 0.028362 |
| Telemetry publication source | 4 | 0.000250 | 712 | 0.053141 |
| Housekeeping publication source | 4 | 0.000250 | 712 | 0.053141 |
| Admission, transaction and completion transport | 68 | 0.003284 | 102 | 0.007613 |
| **Total** | **9,229** | **0.492094** | **5,285** | **0.394455** |

All protected recipes together occupy **1.073352 mm²**: the storage and DLYD
above, plus 0.148936 mm² of buffers/inverters and 0.037867 mm² of other gates.
Ordinary BD logic occupies another **0.820348 mm²**, already more than the
entire clocked map. The gap cannot be solved by delay mapping alone; stage
fusion also needs to remove the associated muxing, transforms and transport.
This is accounting, not a prediction of the area after removing any structure.

The ordinary flip-flops also have recoverable source ownership. Their Q cells
are attributed to the generated `always` block, rather than to a consuming
module's input alias:

| Ordinary source owner | Flip-flop bits | Storage, mm² |
| --- | ---: | ---: |
| I2cTarget sampled front end / edge ring | 942 | 0.070334 |
| FourPhaseServices, including its inlined children | 927 | 0.062763 |
| Clocked bridge / receipt module families | 723 | 0.053980 |
| FourPhaseSoc coordination | 209 | 0.015740 |
| SPI ADC pin player | 95 | 0.007095 |
| LF timebase and watchdog | 78 | 0.005830 |
| ElapsedTicks | 35 | 0.002612 |
| Reset boundary and reset hold | 32 | 0.002406 |
| ProgramAccess / RamAccess | 26 | 0.001941 |
| **Total** | **3,067** | **0.222701** |

Services' 927 bits include the 269-bit host snapshot, 146-bit ordered
Housekeeping command and 71-bit queued Housekeeping command. These are live
storage, not unused synthesis debris. The snapshot implements an observable
readStart snapshot; command queues preserve ordering and immutability while
native consumers stall. Removing them requires changing ownership/transport
without changing those behaviors. Event pending/clear arbitration, physical
sampling, watchdog and reset qualification remain intentional clocked state.

## Necessary storage versus removable duplication

### SRAM: strongest architectural candidate

In [FourPhaseSram](../designs/four-phase-bd/src/main/scala/riscay/bd/FourPhaseSram.scala),
each word takes four unrolled byte lanes. Each lane has a 101-bit `SramWork`
Join operand and a 101-bit capture output: **eight copies, 808 bits per memory
owner**. Four 42-bit byte-issue banks, four 8-bit byte-reply operands, the
69-bit original request and two credit bits bring the total to 1,079.

The sole execution credit returns after the final response is accepted.
Consequently these lanes do **not** provide concurrent word throughput.
The accepted request, byte progress, read assembly and retained final response
are necessary; eight full copies of the evolving word are an implementation
choice. Use one retained request, a native two-bit lane index, one assembly
bank and a reusable byte handshake. Preserve accepted effects across recovery
and full return before reuse.

This proposal **keeps the existing clocked SRAM pin boundary**. Folding the
native word loop does not require a request-derived macro clock. It could also
replace four sets of byte crossings with one reused set. Its net area and
latency need measurement; the current 0.104219 mm² of SRAM native storage is
the addressable storage cost, not a promised saving. The separate return
owners' 32-bit held results must remain until their actual consumers release
them, unless a composed lifetime proof lets them borrow the assembly bank.

### Control: state travels through too many owners

[FourPhaseControl](../designs/four-phase-bd/src/main/scala/riscay/bd/FourPhaseControl.scala)
holds a 284-bit state/CRC token in a FIFO, another 284-bit copy in the Join,
a 379-bit command operand, a 323-bit update/reply and a 32-bit CRC result.
Image/lock/loader state and an accepted command's immutable operands are
necessary. Carrying the complete state through FIFO → Join → update → FIFO
is a coarse-grain banking opportunity, not a requirement of four-phase logic.

Propose one closed architectural bank and an exclusive command credit, with
only the pending effect/result retained separately. Decode/retain the command
fields actually needed instead of a whole host frame at every boundary.
Prove CRC commit at Stored, application cancellation, lock retention and reply
backpressure before removing any intermediate copy. Do not interpret
`1,302 minus architectural-state-width` as automatically removable storage.

### I²C: substantial capacity, substantial copying

Native storage includes four 337-bit frame banks (1,348 bits), a 337-bit
publication bank and a 264-bit receive-byte bank, plus protocol state/update,
closed observation, route and snapshot bits. Queued frames and stable serial
read data are necessary under the current framed ABI. The receive → publication
→ frame-bank copies are candidates for direct receive into a reserved bank.

Keep reservation, frame-boundary validation, reset attribution and publisher
ACK ownership explicit. Do not drop frame capacity or assume backpressure is
free on the wire. The planned register-pointer host ABI may eliminate much of
this structure; decide that interface before investing in a second framed
loader architecture. The separate 942 clocked front-end/ring bits are another
cost, but sampling and queueing cannot simply disappear.

### CPU: retain architectural state, strip physical trace payload

The native core contains the necessary 480-bit RV32E register file, two
171-bit state copies, a 70-bit address/request bank, a 33-bit memory reply
operand and a 278-bit execute result. The execute result includes **107 trace
bits with no consumer in the digital-pad export**. Another **37 writeback bits**
in the Join's state operand have already served their purpose.

Use an export-specific payload projection, keeping complete traces in the
verification/core export. After this small cleanup, investigate a coarser
single-outstanding core with one committed state bank and retained memory
request. That is an architectural change, not permission to weaken the RF
writeback guard or remove the RF. The plain-latch recommendation already
applies to BD's pipeline; it does not turn the edge-triggered RF into a safe
transparent latch array without a new read/write protocol.

### Telemetry and Housekeeping: closed banks have a reason

Telemetry has a 206-bit closed architectural bank (six application words and
seven output/OE bits each), plus a 259-bit update reply, command storage and
credit. Its update still pads GPIO output and enable to 32 bits: **50 stored
zeros** survive mapping. Narrow this internal payload while preserving
32-bit MMIO readback. GPIO pads must continue to come from closed storage.

Housekeeping has a 259-bit closed bank, 268-bit update reply, 147-bit command
and two credit bits. Its old bank and pending update have distinct lifetimes
until commit. A direct bank-write design could reduce the copies, but only
with unchanged commit atomicity and explicit reader qualification. The latest
bank-to-clocked-reader timing proof must be regenerated for any such change.

### Arithmetic owners: bounded reuse before more pipelining

Elapsed holds the same 228-bit iterative record in a FIFO and step output,
plus two history bits. Fractional remainders, overflow behavior and batched
elapsed time are necessary. A single work bank with a native update/commit
cycle is worth comparing, but its feedback hazard and throughput proof must
replace the existing two-store protocol.

ADC scaling carries raw/quotient/remainder through preparation and three
unrolled radix stages. The final 111-bit retained sample bank is architectural;
the full intermediate records are candidates for an iterative datapath or a
smaller combinational scaling cone. Preserve sequence, validity, timestamp,
saturation and suspend/resume semantics. No move into application-specific
firmware or change to the measurement ABI is proposed.

## Direct lane screen: a small, concrete cleanup

A conservative existing-netlist screen found **715 candidate storage bits,
0.034636 mm² of storage cells**:

| Owner | Candidate bits |
| --- | ---: |
| Working SRAM / program SRAM | 193 / 189 |
| CPU | 144 |
| SPI ADC / scaling | 109 |
| Telemetry | 51 |
| I²C | 12 |
| Control | 8 |
| Housekeeping | 3 |
| Admission and publication credit payloads | 6 |

There are 602 bits with no functional sink after following buffer/inverter
chains, and 167 whose D input is constant at the reset value; 54 meet both
conditions. The union is 711 reset latches and four reset flip-flops. Primary
outputs and every non-buffer input count as live. This is not Boolean
equivalence checking or a proof that an entire controller is dead.

Examples beyond trace/padding are high SRAM address bits above physical
capacity, the initial all-zero read assembly, discarded request fields at the
last byte, and unused ADC intermediates. Constant D alone is insufficient:
eligibility D=1/reset=0 and recovery-debt D=0/reset=1 encode meaningful history
and are explicitly excluded. A dead credit **payload bit** does not make its
handshake/credit controller dead.

The number is an optimization screen, not a guaranteed net saving. Regenerating
capture/reset trees changes loads, minimum delays and leaf skew. Any reduction
must retain proof endpoints for surviving lanes and rerun affected setup, hold,
ACK, reset and invalid-data checks. Standalone verification trace ports remain
live in their own exports.

## Why delay area remains high

Six publication/return owners hold just **79 bits** but contain **3,103 DLYD
cells**, 58.7% of the total, occupying **0.231598 mm²**. Seventeen 200 ns guards
inside them account for 2,907 cells / **0.216969 mm²**:

| Owner | 200 ns guards | Current DLYD cells in those guards |
| --- | ---: | ---: |
| Program return / RAM return | 2 / 2 | 342 / 342 |
| Program source / RAM source | 3 / 2 | 513 / 342 |
| Telemetry source / Housekeeping source | 4 / 4 | 684 / 684 |

These guards protect eligibility capture, decisions, returned ownership and
recovery cleanup. Those obligations are necessary. **Their present lengths
are not demonstrated minimum requirements.** The fallback recipe converts a
model ns number into a chain using an all-corner minimum plus headroom. The
measured publication/elapsed overrides do not cover these custom guards.

First target the reused PublicationSource/RecoveryReturn family. Identify each
guard's source, latest destination, reset pulse and full return path; compose
existing completion signals where possible. Size remaining relative-ordering
chains against the same corner, with the current engineering derate and
residual margin. Keep absolute pulse/aperture requirements separate. This is
the largest concentrated delay opportunity, but **no shortening is approved
by this area inventory**.

There is also **0.082623 mm² in 6,273 fixed `buf_1` cells**: nine buffers per
output chain on 411 C-elements, 24 AND primitives and 262 short ControlGate
output lanes. This cost is already in the buffer column, not the DLYD column.
The recipe uses these chains to implement short control-delay assumptions.
Review the minimum-delay contract and actual load before replacing them with
smaller characterized recipes. A keeper's first isolation buffer and its
exclusive repairable parent driver still have distinct electrical purposes.

## What the mapping rules prevent

[`gf180_physical.py`](../tools/gf180_physical.py) gives every recipe leaf `keep`
and `dont_touch`, retains its hierarchy, and instantiates every declared storage
lane. The subsequent graph audit requires exact cell identities and pin
connections. This deliberately prevents:

- deleting constant or unobserved payload lanes, or reducing their capture/reset
  trees after ordinary logic has proved them unnecessary;
- propagating constants through a protected storage boundary to simplify later
  muxes and arithmetic;
- merging equivalent state copies, changing reset-flops to non-reset storage,
  or retiming/fusing payload banks across a handshake;
- collapsing the nine-buffer chains, shortening long guards, resizing protected
  weak drivers or restructuring keeper gates.

Protection of keeper feedback, handshake logic and qualified delay topology is
necessary. Applying exactly the same rule to every payload lane retains costs
that the clocked mapper can optimize. Removing protection would not make an
ordinary synchronous optimizer safely infer asynchronous stage fusion or
retiming: those need explicit architectural and protocol changes. Ordinary BD datapath logic is already
flattened and optimized, so ordinary hierarchy alone is not the main cause:
the matched retained-hierarchy penalty was 0.077763 mm², not the 1.361867 mm²
architectural gap.

Propose **explicit physical specializations**, not globally removing
`dont_touch`: project live payload fields before protected storage, preserve
typed endpoint/lane mappings, regenerate the bounded distribution tree and
audit the new declared graph exactly. For generic library support, propose
control-only tokens and optional physical trace payloads to chisel-async
separately. Resetless transient payload is a later opt-in contract, with
invalid-data and reset-observability proof; architectural GPIO, retained banks
and meaningful reset values are not candidates by default.

## Concrete redesign proposal

The subsequent [action plan](native-area-action-plan.md) supersedes the original
opportunity ranking. It specifies replacement storage, commit/return lifetimes,
files, verification and engineering budgets. The first structural batches are
SRAM lane reuse, deletion of Telemetry/Housekeeping's reservation detour at the
existing receiving-edge arbitration, compact Control/committed CRC, and removal
of full-state Telemetry/Housekeeping result copies. Size only surviving guards.

In particular, the two PublicationSource owners can be removed before spending
a campaign on their eight long guards. Memory source/return owners have different
asynchronous eligibility and drainage obligations and remain in the first batch.
The replacement host ABI still needs a decision before rebuilding frame storage.
These are proposals, not implemented or timing-qualified savings. Existing cost
pools overlap; fresh whole-chip measurements must decide each accepted batch.

## Evidence and review

Recount inputs are `build/hierarchical-floorplan/flat-map-r3/netlist.json`,
`build/hierarchical-floorplan/map-r4/mapping.json`, the frozen native audit, the matching TT Liberty and
`build/clocked-comparison/map-r2/netlist.json`. The existing native graph checker
revalidated all 1,137 primitive instances and reconciled every mapped cell.
The ordinary attribution resolves every one of the 3,067 ordinary flip-flops.

Local analysis scripts, complete per-primitive/per-lane inventories and run
receipts are retained in `build/native-overhead/`. They are exploratory
accounting, not new production checkers or a new mandatory test campaign.
The source-referenced explanations above are part of the report; the generated
evidence remains outside Git. Independent review is recorded separately in
[the review note](reviews/native-overhead-investigation.md).
