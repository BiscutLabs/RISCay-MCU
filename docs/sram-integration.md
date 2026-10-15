# GF180 SRAM integration

Each variant owns native word sequencing and an explicit clocked byte-access
`SramBank` boundary under its `designs/` directory. Item 6 digital verification
and independent review pass; physical timing remains unqualified. Both use the same fixed physical macro, `gf180mcu_ocd_ip_sram__sram1024x8m8wm1`. Groundlark has
two macros for 2 KiB program storage and one macro for 1 KiB working storage.
The boot ROM, loader, permanent supervisor and architectural registers are
unchanged in purpose. No external memory or new pins are required.

C1b removes the eight duplicate 42-bit clocked byte-request payload banks.
Each native lane issue stage retains its request until the actual macro
controller captures `saved` and `tag`. The receiver still owns request
synchronizers, settling and ACK control. Falling-edge macro input launch and
full-cycle Q capture remain unchanged. See the
[held peripheral capture contract](held-peripheral-capture-contract.md) for the
extended RDC proof and open producer-to-consumer physical timing obligation.

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
The word-drained input excludes the source reservation, grant, decision and
publication receipts, avoiding a circular wait. In 10b2d1 it includes the
independent capture receipt idle condition through effectsDrained.

RAM no longer uses Services' `cpuMemoryPending`; substep 10b2b now removes that
program-read flag and the clocked Stored-pending flag, with digital qualification complete.
That substep retained four RAM ownership crossings and the whole-word round trip.
The digitally verified 10b2d1 integration removes the word reply crossing and RAM
publication bridge: separate native RamReturn owners retain the whole word,
publish directly to RamSource and feed Completion's independent RAM input.
Fresh review and digital qualification pass. Three reservation/grant/decision crossings,
the word-command crossing, synchronized idle/debt qualification, RamAccess.active,
a temporary five-bit capture receipt and synchronous byte boundaries remain.
The receipt clears active independently of publication; effectsDrained excludes
return-owner occupancy while full busy includes it. See
[the working-RAM return contract](ram-return-contract.md). Digitally verified
10b2d2 also removes program/loader's whole-word round trip. Its independent
native return captures retained CPU-role permission and preserves POR Stored
accounting; see [the program return contract](program-return-contract.md).
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
asserts that all 32 address bits of each actual firing lane satisfy the upstream
valid-offset contract before saving only
`log2Ceil(bytes).max(1)` bits. The external request remains 32 bits. Macro address
selection pads to ten bits; bank selection pads to at least eleven before
shifting. Groundlark retains 11 program / 10 working-RAM address bits. One-word
and non-power-of-two logical banks retain their original bounds.
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

## C1f saved-address narrowing

Both production controllers rely on upstream full-width admission validation and
retain full-width assertions on each firing lane before narrowing the saved offset.
These assertions diagnose contract violations in verification; C1f adds no
synthesized range-rejection gate at the byte controller. Saved write/data/enable, lane tag, POR ownership and source
capture remain unchanged. Falling-edge input launch, the following rising macro
access, full-cycle Q capture and response stalls preserve the existing contract.
Full-width firing-lane range assertions cover disabled requests and both
read/write directions, failing on out-of-range addresses in verification. Four-byte banks retain two address bits; non-power-of-two bounds
are checked before compaction and never inferred from retained width alone.

Digital evidence contains 390 distinct Scala tests across 28 suites (24 primary,
362 affected, four physical), plus two repeated PhysicalEstimateSpec cases:
392 executions, not 392 distinct tests. All 587 Python controls pass. Twelve
fresh fixtures cover both variants at 4, 12, 1024, 1028, 2048 and 3072 bytes;
12 positive and 1,304 negative replays bind 48 actual production assertion sites.
Four fresh strict exports retain four generic campaigns each, compiled proof,
RDC and SRAM obligations. All eight held structural/actual-wiring commands pass.

The matched baseline is A5b `67b282cf1a455465c7874a72fcd3dfea0044acfa`.
The same mapper, assets, policy and five Liberty corners are used. Native
primitives, public ABI and three actual SRAM macro topologies are unchanged.

| Quantity | BD before → after | Click before → after |
| --- | ---: | ---: |
| Portable periodic RTL bits | 5910 → 5867 | 5911 → 5868 |
| Physical-export periodic RTL bits | 5920 → 5877 | 5921 → 5878 |
| Mapped work-clock storage pins (including 3 SRAM CLK pins) | 4111 → 4068 | 4162 → 4119 |
| Native payload bits after | 11454 | 11607 |
| Whole mapped area including SRAM (mm²) | 3.503083 → 3.497685 | 4.271623 → 4.268773 |
| Mapped logic area excluding SRAM (mm²) | 2.874882 → 2.869484 | 3.643422 → 3.640572 |
| Logic area change | -0.1878% | -0.0782% |
| TT listed-state leakage including SRAM (µW) | 7.607764–9.867172 → 7.595104–9.845576 | 9.079021–12.144499 → 9.071659–12.132237 |
| Total periodic storage clock-pin load (pF) | 19.207195 → 19.070326 | 19.392035 → 19.255166 |


Click's FF 125 °C / 3.60 V listed-state high envelope **increases by
0.231845076 µW**, although its low envelope changes by
-0.277877088 µW. This is entirely ordinary-logic cell composition:
more XOR3/NOR4/OR2/MUX2 cells outweigh reductions including 43 DFFQ cells in the
sum of per-cell maximum leakage states. Native guards, other native cells and
SRAM are unchanged. This sum does not prove jointly reachable worst-case states;
no improvement across every corner or reachable standby-power claim is made.

Exact workload/observer identity and all 27 ordinal wake windows are compared.
Changed windows: 0 BD / 0 Click;
all individual values and changes remain in the matched receipt. Native-model
activity and clock load do not measure wake energy. Listed-state leakage does
not establish reachable standby leakage. Area excludes placement/routing,
clock/reset trees, analog and pads.

The bounded controller timing campaign records 20 baseline/candidate cases,
both variants at five matching corners. Complete coverage: 0
cases; cases with violations: 20; cases with missing
checks/paths: 20. Every raw result, signed setup/hold
value, minimum-capacitance violation and native-ingress limitation is retained.
The full hierarchy is bound by local pin/term inventories. Applicable local API
checks and supplemental direct estimates remain distinct: direct capacitance/
fanout reports can be finite and failing even when the API excludes an ideal
clock or constant pin. Direct slew uses its own internal exclusions. Hierarchical
API findings and top-level terms retain explicit classifications.

Across the 20 cases, 1167270 electrical requests produce
148705 finite applicable local reports and
40 supplemental direct estimates, with
76089 applicable and
20 supplemental violations.
314345 reports have unavailable/inapplicable API results;
704180 are explicitly inapplicable non-driver checks.
There are 0 hierarchical API findings
(0 violations) and
0 top-level-term reports outside local API
enumeration. Pulse coverage records 5220 of
5220 requested edge checks, including
0 violations. Missing path requests total
0. These totals count reports across cases, not unique
physical pins. Optional library-limit absence is a coverage classification,
not a process error or a passing physical check. Of the unavailable reports,
37000 use the exact pinned binary32
`1e30` numeric fanout initializer; its encoding is preserved separately from
unit-formatted `INF`, and it is never treated as a finite measured value.

**Measured setup timing worsens after C1f.** The worst recorded setup slack
changes from -142.4398 to -152.7541 ns for BD at TT and
-303.6563 to -318.8663 ns at SS125; Click changes
from -172.3115 to -184.9705 ns at TT and
-358.1870 to -377.1508 ns at SS125.
The worst candidate paths run from `resetHold` Q to `fabric_ram_state[0]` D;
baseline case minima instead end at `fabric_program_state[0]` D. These are
case minima, not a claim that the same endpoint is worst before and after.
The largest matched endpoint setup-slack changes are
-17.39656 ns BD (`fabric_ram_saved_address[0]`)
and -21.38074 ns Click
(`fabric_ram_state[0]`), both at SS125. Hold minima are
unchanged in all five corners for both variants, but individual hold margins
also decline. At SS125, the saved-address path to program macro 1's falling-edge
`CEN_REG` has hold slack 32.261597 → 28.479730 ns
in BD (-3.781867 ns), and
32.261597 → 28.479740 ns in Click
(-3.781857 ns). These individual margins remain positive.
Fewer violation records do not imply improved timing; these measured regressions remain explicit and
physical qualification stays open.

| Implementation / variant / corner | Minimum hold slack (ns) | Minimum setup slack (ns) | Violation report groups | Missing-coverage entries |
| --- | ---: | ---: | ---: | ---: |
| baseline/bd/tt_025C_3v30 | 0.7279879682906972 | -142.43983462561448 | 411 | 16634 |
| baseline/bd/ss_n40C_3v00 | 1.2313761470130726 | -207.64563278772903 | 409 | 16634 |
| baseline/bd/ss_125C_3v00 | 1.986479037489901 | -303.65627316549796 | 691 | 16634 |
| baseline/bd/ff_n40C_3v60 | 0.19925744951343918 | -70.68576679609276 | 226 | 16634 |
| baseline/bd/ff_125C_3v60 | 0.48541144699922806 | -126.52343530991155 | 485 | 16634 |
| baseline/click/tt_025C_3v30 | 0.7279879682906972 | -172.31153525085878 | 411 | 17182 |
| baseline/click/ss_n40C_3v00 | 1.2313761470130726 | -247.73161290207977 | 409 | 17182 |
| baseline/click/ss_125C_3v00 | 1.986479037489901 | -358.18701907218883 | 679 | 17182 |
| baseline/click/ff_n40C_3v60 | 0.19925744951343918 | -89.51329530967396 | 228 | 17182 |
| baseline/click/ff_125C_3v60 | 0.48541144699922806 | -154.2077158503992 | 485 | 17182 |
| candidate/bd/tt_025C_3v30 | 0.7279879682906972 | -152.7540874804698 | 142 | 14229 |
| candidate/bd/ss_n40C_3v00 | 1.2313761470130726 | -211.08825507241485 | 144 | 14229 |
| candidate/bd/ss_125C_3v00 | 1.986479037489901 | -318.8662935058946 | 245 | 14229 |
| candidate/bd/ff_n40C_3v60 | 0.19925744951343918 | -78.70942875804121 | 124 | 14229 |
| candidate/bd/ff_125C_3v60 | 0.48541144699922806 | -137.44349691840938 | 175 | 14229 |
| candidate/click/tt_025C_3v30 | 0.7279879682906972 | -184.97047972405184 | 190 | 14824 |
| candidate/click/ss_n40C_3v00 | 1.2313761470130726 | -252.5950222705194 | 148 | 14824 |
| candidate/click/ss_125C_3v00 | 1.986479037489901 | -377.1508083700604 | 241 | 14824 |
| candidate/click/ff_n40C_3v60 | 0.19925744951343918 | -99.27091607501954 | 129 | 14824 |
| candidate/click/ff_125C_3v60 | 0.48541144699922806 | -167.50484140519157 | 181 | 14824 |

These are ideal-clock, unplaced controller observations. Native held-bus aperture,
real setup/hold/access and clock/reset distribution, minimum pulse/return,
POR abort/recovery/removal, route RC, transistor models and A7 remain open.
This evidence does not qualify the complete chip or authorize self-timed SRAM.

Evidence: `build/async-sram-address-production-r2/execution.json` and its frozen
417-source archive; `async-sram-address-validation-r1/` strict and saved/held
receipts; `async-sram-address-measurement-r3/audit-receipt.json`; and
`build/async-sram-address-timing-r5/execution-r1/receipt.json`. The failed timing-r2 execution remains at
`build/async-sram-address-timing-r2/execution-r1/receipt.json`: its first STA
process completed but parsing failed; 19 cases were not run. The sealed
`build/async-sram-address-timing-diagnosis-r2/` preserves the raw-format diagnosis.
Timing-r3 was rejected before execution for local API scope/applicability gaps;
`build/async-sram-address-timing-review-r3/REPORT.md` remains separate from the
accepted r4 preparation review. Timing-r4 subsequently stopped after its first
baseline BD/TT process exited zero and the parser rejected the numeric fanout
no-check initializer (`C1F_MEASUREMENT_NONFINITE_OR_SENTINEL_VALUE`); its receipt
and complete raw log remain under `build/async-sram-address-timing-r4/execution-r1/`,
with the other 19 cases marked `NOT_RUN`. Timing-r5 recognizes only the exact
pinned initializer encoding; constraints, runtime assets and physical limits
remain unchanged. The complete r4 log replay is a pure parser control, not a
completed r5 case. No prior case was reused as completed r5 evidence.
The original successful activity run stays at measurement-r2. Measurement-r3 records exactly two
historical pointer reconstructions, with original hashes and A5 receipt recipes;
the other 7,898 baseline references remain exact live hashes. Final documentation
is separately bound to the executed archive by the C1f final collector.
