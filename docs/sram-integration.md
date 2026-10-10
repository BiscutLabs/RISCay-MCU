# GF180 SRAM integration

Each variant owns native word sequencing and an explicit clocked byte-access
`SramBank` boundary under its `designs/` directory. Item 6 digital verification
and independent review pass; physical timing remains unqualified. Both use the same fixed physical macro, `gf180mcu_ocd_ip_sram__sram1024x8m8wm1`. Groundlark has
two macros for 2 KiB program storage and one macro for 1 KiB working storage.
The boot ROM, loader, permanent supervisor and architectural registers are
unchanged in purpose. No external memory or new pins are required.

## Source and physical views

The macro is from [Open Circuit Design / Tim Edwards](https://github.com/RTimothyEdwards/gf180mcu_ocd_ip_sram),
revision `efdbf734d806c2ac3b858d281a5b832625a8e928`, Apache-2.0. It is a
community 3.3 V synchronous single-port macro, separate from the foundry's
original 5 V library. [soc/sram-lock.json](../soc/sram-lock.json) pins hashes for
the GDS, LEF, SPICE, nominal/slow/fast 3.3 V Liberty views, Verilog and license.
The upstream Verilog views and license are vendored verbatim under
`soc/src/main/resources/riscay/sram/`.

Fetch the remaining physical views without changing their content:

```text
python tools/sram_assets.py
python tools/sram_assets.py --verify-only
```

The default destination is ignored `.tools/gf180-sram/`. The fetcher verifies
every file against its pinned SHA-256 and rejects changed cached files. Use
the pinned GDS/LEF/Liberty macro definition in the physical flow. Bind its VDD
and VSS to the retained supply; the portable RTL follows upstream's implicit
power-pin view. Physical netlist power connection, PDN, placement, extraction,
DRC/LVS and timing/power qualification remain required.

One LEF rectangle is 301.300 by 515.810 micrometers, or 0.155413553 mm2.
Three rectangles total **0.466240659 mm2**. This is macro area, not whole-chip
area: controller cells, routing channels, supply straps and placement margins
must be included. The historical flip-flop estimates are not estimates for
this revision.

## Native RAM source reservation (10b2a; digitally verified)

Each variant now reserves a POR-owned native slot before a CPU RAM request can
commit. The grant carries the held write bit. CPU acceptance, grant consumption,
word-command acceptance and the committed-decision receipt occur on the same
service edge. A queued or held grant from an old application lifetime is consumed
as cancellation; it cannot issue a word. A committed slot waits for the actual
whole-word publication receipt and complete word/byte/receipt drainage before
reuse. BD waits for return to zero; Click retains independent native parities.
Click qualifies the decision phase before its phase comparator, allowing the
cancel/commit selection cone to settle before retirement is enabled. Its
221.200001 ns digital guard exceeds the conservative 111.2 ns selection bound;
retirement feedback bypasses that input guard and settles within 121.2 ns before
the outward acknowledgment permits reuse. A publication-only skew test exposed
the original race; its unchanged oracle also rejects a guard-bypass RTL mutation.

Only reply eligibility resets with the application; POR phase identity and accepted
memory effects persist. Eligibility is a retained cancellation attribute, not a
response-valid signal: CPU completion requires an actual SRAM response publication
and cleared reset debt. Every reset pulse restarts the coordinated application
reset hold. Debt and its release history reset asynchronously, and fresh admission
waits for the owner, all four source bridges and the existing SRAM paths to drain.
The word-drained input excludes the new receipt bridges, avoiding a circular wait.

RAM no longer uses Services' `cpuMemoryPending`; substep 10b2b now removes that
program-read flag and the clocked Stored-pending flag, with digital qualification complete.
Four RAM ownership crossings, synchronized idle/debt qualification,
`SramAccess.active`, word crossings and the synchronous macro boundary remain.
Later checklist items remove those round trips under this ownership contract.
No reset, bundled-path, CDC or physical macro timing closure is claimed.

## Native program source reservation (10b2b; digitally verified)

Each variant reserves one tagged CPU-read or loader-write slot. A late Control
winner cancels an uncommitted CPU reservation; a winning BEGIN invalidates the
image and the pending read faults after revalidation. CPU/grant/decision/word
acceptance agree. Loader reserve, grant, decision, publication and native Stored
delivery bypass CPU reset debt, retaining accepted writes and accounting.

Actual word publication feeds the source receipt before word drainage can finish.
It creates one Stored token for a committed loader; CPU reads and cancellations
do not create Stored. The token carries the retained reservation tag, which stays
stable through its full return. Stored acceptance means its Control command fired;
native `ControlState.loaderPending` retains CRC/received obligations until that
command, and clocked status retains busy history through reply publication.

BD retains Stored acceptance separately from full return: it permits the main
reservation ACK to rise, while Stored RTZ gates that ACK falling and slot reuse.
Click captures an immutable next-Stored target at reservation arm and retains
an independent issued phase. Only committed loader slots wait for that target;
CPU publications and cancellations leave Stored history unchanged. Decisions
must follow grant/word acceptance. Its 241.200001 ns guards exceed conservative
111.2 ns selection, 91.2 ns Stored feedback and 121.2 ns retirement-feedback
digital bounds. Actual-pin monitors cover all six custom Click registers across
127 positive replays and reject ten setup/hold/pulse/distribution defects. The
model envelope remains uncharacterized physically.

Five POR bridges, synchronized drainage/reset debt, whole-word crossings,
`SramAccess.active` and physical byte access remain for subsequent checklist
items. Source wordDrained excludes source receipt bridges to avoid circular waits.

## Access and arbitration

The native `FourPhaseSram`/`ClickSram` controller executes one word at a time. Program addressing
selects macro 0 for byte offsets 0..1023 and macro 1 for 1024..2047. Working
addresses cover 0..1023 in a separate macro. All aligned 32-bit words fit inside
one macro. Little-endian reads return four assembled bytes. Masked stores issue
one write for each enabled lane; masked-off bytes never assert chip enable.
Logical capacities remain build parameters, rounded up to 1 KiB physical
instances; smaller verification profiles still use the real macro model.

The fabric validates the full byte address before native admission. Each native
lane transform substitutes its literal low address bits; the macro boundary
checks the full byte offset before selecting a macro and its ten-bit address.
One-word and non-power-of-two logical banks retain their original bounds.
Native loader metadata retains full 32-bit byte lengths, entry offsets and received
counts. Capacity/alignment/entry checks happen before any macro index conversion;
the byte-based ABI and full-capacity/non-power-of-two checks remain unchanged.
The `receivedWords` observation is derived from the committed byte count for the
existing reset/physical-write oracle; it is no longer the accounting register.

Address, data, write-enable and chip-enable launch from falling-edge registers.
The following rising edge accesses the macro. A subsequent rising edge captures
the read byte, allowing a full clock period for clock-to-Q; the intervening
falling edge disables chip enable. Four ordered native lane rendezvous form one word,
followed by one held response. Dedicated request/completion crossings surround
each byte. Latency includes these crossings and native transforms; the former
eight-cycle word bound no longer applies. Native execution credit returns only
on final response acceptance. No subsequent word can issue byte effects earlier.

The POR-only native Control loop receives a separate completion command after
all bytes finish. BUSY remains asserted until that command's state update returns
through the explicit snapshot bridge. Reset cannot lose an accepted completion,
and an upload command captured while busy cannot become a deferred write/VERIFY.
Word sequencing and read assembly are native; only the individual synchronous
macro access/capture remains on the service clock.

CLK connects to the qualified service clock, not to a request pulse. At the
fast-source 20 MHz upper bound there is nominally 25 ns for each input half-cycle
and 50 ns for output capture. Physical STA must include clock skew, duty cycle,
macro setup/hold, controller paths and clock-to-Q across the required corners;
RTL timing margins are not signoff. Only the selected byte's macro asserts CEN.
During retained sleep, CEN is inactive and the service clock stops while SRAM
remains powered. Static SRAM needs no refresh, but still leaks.

The CPU and loader share the program controller with loader priority for a
simultaneous admissible request. CPU requests wait while either bank is busy or
a CPU response is pending. Range and permission checks occur before any SRAM
request; the CPU cannot write program storage or fetch from working RAM.

An accepted I2C WRITE sets loader BUSY. RECEIVED_BYTES and CRC advance only after
all four bytes finish. BEGIN, WRITE, VERIFY, LOCK and START commands reject
with busy error 3 while program memory is occupied. Status selection/read and
independent WAKE/SAMPLE_PERIOD commands remain available. There is no unbounded command queue. At the supported I2C rates, the
normal interval between complete wire frames exceeds a memory transaction.
Host software must still follow BUSY, LAST_ERROR and RECEIVED_BYTES rather than
assuming ACK means completion. Lock/verify cannot overtake an unfinished write.

## Stored receipt crossing

The ProgramSource's native Stored buffer retains its one-bit payload throughout
backpressure. A separate `FourPhaseStoredReceipt` or `ClickStoredReceipt` observes
the request through two service-clock synchronizers, presents that held payload,
and acknowledges only when Control accepts the Stored command. BD acknowledgment
returns only after synchronized request return; Click retains the accepted phase.
There is no duplicate clocked payload register or capture FSM in this crossing.

The native buffer must meet its complete output-bundling contract before request
publication. Two synchronizer stages and the subsequent consumer edge add at
least two service periods of settling (100 ns at the 20 MHz digital ceiling).
After acceptance, the native buffer retains the payload through BD return or
until a subsequent Click reservation reaches a new Stored capture. The return
and source-reuse paths must preserve the consumer's hold aperture as well.
Physical data-path delay, metastability, placement, clock uncertainty, clock-to-Q,
fork skew, consumer hold and reset release still need qualification. This is a narrowly qualified held-token
boundary, not a replacement policy for generic data-bus crossings.

## Reset and sleep

SRAM contents have no reset clear. Full POR/manual/brownout reset cancels the
controller state, pending replies and loader accounting, and invalidates the
image. If reset interrupts a store, already-written bytes may remain and later
bytes are not replayed. Application startup initializes data/BSS/stack as before.
Complete supply loss requires a fresh Pi upload.

Application watchdog reset cancels CPU replies but does not reset the SRAM
controllers. An accepted working-memory store finishes all enabled bytes; a
loader write finishes and advances its accounting. Image validity, lock and
permanent supervision retain their existing reset scope. Synchronized reset
observation prevents an old memory completion from reaching the restarted CPU.
Pending transactions keep the service island awake until they finish. Responses
remain stable under downstream backpressure.

## Simulation and synthesis

`Gf180Sram1KiB` emits both views behind `SYNTHESIS`. Synthesis sees only the
upstream empty macro declaration and must retain three physical instances;
it must not convert the simulation array into standard cells. Event simulation
uses upstream's behavior, including its internal delayed-clock access logic.
The only local model transformation changes its zero-filled power-on array to
unknown bits. The vendored file is unchanged; the transformation is explicit
and checked at elaboration in `Sram.scala`.

The Icarus harness does not enable `specify` checks: its vector path handling
rejects this upstream model with `-gspecify`, and its setup/hold checking is not
a substitute for STA. `SramSpec` independently checks at least 5 ns of stable
macro inputs before/after active clock edges, including all address bits, at
20 MHz. This checks the digital launch scheme, not transistor timing or PVT.
The upstream model itself notes unresolved timing-table inconsistencies; use
the pinned physical views and review characterization before tapeout.

Directed tests cover every program/data word, both sides of the program-bank
boundary, every byte mask, out-of-range/protected accesses, response stalls,
physical macro write counts, and reset at tested macro-lane, held-response and
loader-completion checkpoints. Native tests also cover byte stalls, early next
requests and POR at each lane; old service-cycle offsets are not exhaustive
native-phase coverage. Firmware tests upload compiler-built images through I2C into both native
SoCs, checking startup, stack, retention, sleep and programming lock. The strict
async export checks cover CPU contracts separately from macro physical timing.
