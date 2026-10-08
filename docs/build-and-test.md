# Build and test

The build consumes the chisel-async RC1 JAR; it does not compile a second copy of
the library in this repository. Required versions are Scala 2.13.18, Chisel/plugin
7.16.0, firtool 1.160.0, sbt 1.12.4, JDK 21 and Icarus Verilog 13.

Install RC1 into the local Ivy cache by running `sbt publishLocal` from a pinned
chisel-async RC1 checkout, or add the resolver for its released Maven ZIP using
the [library installation guide](https://github.com/BiscutLabs/chisel-async/blob/main/docs/getting-started.md).
Maven Central does not currently host that RC. Point `JAVA_HOME` at JDK 21 and
`CHISEL_FIRTOOL_PATH` at the directory containing firtool; put `iverilog` and `vvp`
on PATH. There is no required sibling-checkout path in this build.

From the repository root:

```text
python tools/build_firmware.py --bootstrap
python tools/sbt.py --bootstrap test
python tools/sbt.py "fourPhaseBd/runMain riscay.bd.EmitFourPhase build/four-phase-bd"
python tools/sbt.py "twoPhaseClick/runMain riscay.click.EmitClick build/two-phase-click"
python tools/sbt.py "fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/four-phase-soc"
python tools/sbt.py "twoPhaseClick/runMain riscay.click.EmitClickSoc build/click-soc"
python -m unittest discover -s tools -p "test_*.py" -v
```

The sbt bootstrap fetches and checksum-verifies only the pinned sbt launcher. It does
not install Java, the compiler, the library or a simulator. With sbt already
installed, the same task strings work directly with `sbt`.

The separate firmware bootstrap extracts pinned RV32E-capable GCC 13.2.0 and
binutils 2.42 packages under `.tools/`; on Windows it uses Ubuntu WSL. See the
[firmware guide](../firmware/README.md) for platform prerequisites and budgets.
FirmwareSpec and the Python linker controls require that compiler; missing tools
are failures. Subsequent firmware builds do not need `--bootstrap`.

Generated RTL/manifests and simulation evidence remain in ignored `build/`.
Each SoC emitter also produces `chip/` with internal LF, stoppable fast-source
and supply-monitor boundaries, a synthesizable reset sequencer, synthesis black
boxes and separately selected simulation models. See
[sleep and clocks](sleep-and-clock.md). The parent export's strict contract
checks cover the digital SoC; they do not validate the analog black box.
`CoreSpec` covers arithmetic, signedness, x0, memory widths/lanes, branches/jumps,
faults, reset during an outstanding fetch and a deliberately wrong expectation
that must fail its retirement checker. Both designs consume the same independent
reference traces. `NativeRoutingSpec` tests native phase fork/join under skewed
arrival, stalls, repeated values and reset with one unmatched operand.

`HostSchemaSpec` verifies the logical host catalog with Groundlark and an unrelated
counter fixture, including absent/unknown resource rejection and invalid profile
bindings. This checks schema/configuration separately from the RTL suites.

`SocSpec` drives both complete designs through modeled open-drain I2C and SPI ADC
pins. It covers bounded uploads, wrong ABI/range/incomplete/corrupt images,
validation/start/lock, RAM byte lanes, code-store rejection, bus/full resets,
independent watchdog recovery (including a stopped service clock), unprogrammed
Groundlark boot, protected control outputs, shutdown acknowledgement, minimum-off
timing and the three-timeout latch. CRC expectations come from Java's CRC32;
firmware is hand-encoded using test-only assembly helpers.

`FirmwareSpec` adds real compiler-built C images at the full 2 KiB/256-byte
capacities. Both native SoCs receive each binary through the I2C loader and
CRC/START_AND_LOCK flow, then execute startup/data/BSS initialization, arithmetic,
stack frames and retained sleep. Retirement SP writes, a RAM watermark and a
guard check independently corroborate GCC's stack bounds. These finite generic
fixtures are not deployment firmware. `test_firmware.py` checks rejection of
unknown/dynamic/recursive stacks, unsupported ISA and real undersized links.
It also compiles the actual event helper against mapped MMIO storage on Linux
(Ubuntu WSL on Windows), requiring native `gcc`, to verify that WAIT preserves
events arriving during processing and acknowledges only consumed bits.
Full-capacity compiled-image simulations have a bounded 300-second process
allowance; other clocked harness tests retain their 90-second default.

`FabricSpec` drives the shared service bus independently of the CPU to check
response stability under backpressure, exactly-once acceptance, ROM/unmapped
errors, event/clear races, deadlines, failed/stale samples, interrupted upload,
reset cancellation and zero-channel/zero-GPIO configurations. Groundlark tests
accelerate the millisecond divider and ADC cadence together; their enabled
fixture is not a deployment policy. Test watchdog clocks are accelerated too.
Additional fabric cases cover queued watchdog kicks, lease writes with no kick,
sparse application-register holes and reads spanning concurrent word updates.
`ScalingSpec` exhaustively checks all 4096 ADC codes against independent integer
division, plus fractional tick accumulation, large missed-tick deltas, counter
wrap, updates during catch-up and reset during serial calculation.

`SleepSpec` covers both CPUs parked through masked millisecond ticks, timed and
host wake, finite watchdog-serviced leases, RAM/image-lock retention, runtime
ADC cadence, invalid period rejection, repeated updates without starving sensing,
and full reset with a closed clock gate. Both native variants also execute
through the chip wrapper's behavioral on-die oscillator. Independent service-bus
tests cover GPIO/entry races, held responses/exactly-once effects, pending wake
and wall-time/sample-age advancement after a short service-clock interruption.
The permanent Groundlark controller cold-starts without a program and performs
shutdown/ACK with a sleeping service island. That long-duration fixture uses
small RAM capacities to avoid unnecessary simulator cost; production-capacity
emission and strict exports remain separate checks.

`DeepSleepSpec` adds both native CPUs with the service oscillator actually
stopped/restarted, the address-only I2C wake protocol, 0/15/100 us startup cases,
8/10/20 MHz service-model frequencies, slow Gray tick transitions, nominal-time
fraction carry, conservative sample aging, board minimum-off/ACK behavior,
retained RAM/lock and watchdog recovery. LF clocks are accelerated in the SoC
fixtures; the LF model's actual nominal period is checked separately.
The Groundlark case retains the production 32-edge watchdog ratio and deliberately
traps locked firmware in RUN and SHUTDOWN, checking uninterrupted Pi power,
shutdown state, live sensing and lock preservation. Host timeout cases abandon
write/read transactions, hold SDA low, continue foreign-address data clocks and
then recover a normal read. None may keep the fast oscillator enabled indefinitely.

`test_oscillator_model.py` runs Icarus checks of POR startup/restart, nominal slow
frequency, error response, bounded period jitter and invalid-frequency
rejection. `test_service_oscillator.py` checks cancelled startup, complete final
high pulses, stopped-clock silence, restart, and rejection of invalid bounds.
These tests establish the models' behavior, not analog feasibility,
PVT accuracy, energy, metastability or physical clock-gate timing.

The clocked harness uses `ExportDesign` and the library's actual primitive models;
`AsyncTest` continues to cover the clockless cores and native routing with seeded
delay variation. Every SoC simulation has a deadline, process timeout and required
completion/assertion checks. No skipped/missing simulator is treated as success.

These are initial directed/generated tests, not complete RISC-V architectural
qualification, complete reset-phase coverage, real Pi validation or silicon
timing/metastability qualification. Deployment firmware and real Pi/analog
validation remain subsequent qualification work.

For strict export validation, use the matching chisel-async checkout's tooling
through the MCU timeout adapter:

```text
python tools/check_export.py build/four-phase-bd --library /path/to/chisel-async
python tools/check_export.py build/two-phase-click --library /path/to/chisel-async
python tools/check_export.py build/four-phase-soc --library /path/to/chisel-async --soc --vector-coverage --sleep-clock
python tools/check_export.py build/click-soc --library /path/to/chisel-async --soc --vector-coverage --sleep-clock
python -m unittest discover -s tools -p test_check_export.py -v
```

The library's 60-second component-probe limit was exceeded by both original core
exports. The adapter allows 600 seconds for each generated probe's compilation
and simulation, controlled by `--probe-compile-timeout` and `--probe-timeout`.
Other subprocess limits remain unchanged, and a timeout still fails. Complete
SoCs additionally require the explicit options above:

- `--soc` checks every async child reset against the registered `systemReset`
  endpoint and also checks the external POR contribution. The library's default
  assumption that all children directly use the external reset does not describe
  this SoC's watchdog-generated reset. Primitive-local reset checks stay intact.
- `--vector-coverage` replaces per-bit zero/one accumulation with equivalent
  packed two-state conversions of both value and inverse. X/Z count as neither.
  All drivers, mapping comparisons, endpoint coverage requirements and check
  counts are retained. The scalar full-SoC probes exceeded the practical time
  budget; this option reduces bookkeeping rather than deleting mapping cases.
- `--sleep-clock` appends a third single-driver campaign with the native
  `gate_enabled` register held high against an otherwise low background.
  The original low background closes the gate, while the high background blocks
  acceptance through other controls. The added campaign permits commit activity
  without forcing a derived endpoint. Every original stimulus case, comparison
  and coverage requirement remains; the library's paired fallback is retained.
  Use this option for retained-sleep exports, not legacy ungated fixtures.

The Python adapter tests verify timeout overrides apply only to generated probes,
correct reset wiring, deliberately missed watchdog
reset rejection, failure on unrecognized checker/endpoint shape, and coverage
equivalence for all 256 four-bit vectors over 0/1/X/Z, both singly and accumulated.
An independent clock-gated fixture demonstrates that the additional stimulus
covers an initially inactive endpoint and still rejects an incorrect binding.
Clocked helper modules are inlined into the contract root. Constant/partly unused
GPIO outputs remain in `ports.json`, with behavior checked by the SoC suites;
they are not declared as asynchronous timing endpoints that must toggle every bit.

Record actual pass/fail results separately from emitting files. The initial
Windows development run used the local RC1 JAR with SHA-256
`cc37c3baabdf03f2886912082347c34650695c472f6a788d653be9f8932a04ac`.
The version is pinned in the build; this hash records that run, not an enforced
dependency-integrity check or a cross-platform qualification claim.

## Initial Windows verification record

On 2026-10-07, `python tools/sbt.py test` passed all 16 tests in two suites,
with no skipped or pending tests. The suites include 99 passing randomized-delay
simulation runs and two intentionally rejected retirement expectations.
Both variants use the same instruction and memory-effect oracle; the oracle
also has hand-calculated signedness/x0 and branch checks.

Both strict exports passed with the longer probe timeout:

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase core | 110 | 2,367,200 | PASS |
| Native Click core | 84 | 1,563,072 | PASS |

The exported Click instance inventory contains no four-phase storage or phase
adapters. Mapping-check counts describe validator work, not hardware performance.
Raw results remain under `build/`; the final test reports are under
`verification/target/test-reports/`. No whole-MCU, firmware, Linux-host or physical
qualification is implied by this development run.

After adding the generic host schema and separate profile project, the full
`python tools/sbt.py test` run passed 20 tests in three suites on 2026-10-07,
including both core variants and all four new schema tests. No tests were skipped
or pending. A fifth schema test was then added for replacing application bindings
within unchanged hardware resource counts; a targeted HostSchemaSpec run passed
all five tests. At that stage, host/peripheral RTL and physical qualification were
outstanding. CPU RTL was unchanged, so
the strict core exports were not regenerated for this schema-only addition.

## SoC integration verification record

On 2026-10-07, the full `test` task passed 29 tests across five suites after SoC
integration. After inlining the clocked helper hierarchy for export and extending
the loader/policy assertions, a targeted `SocSpec FabricSpec HostSchemaSpec` run
passed all 15 tests. Together with the unchanged core/routing suites this verifies
31 distinct tests: 13 core, 3 routing, 6 schema/policy, 7 complete-SoC and 2 fabric.
There were no skipped, canceled or pending tests.

The SoC harness's deliberately incorrect ABI expectation was rejected as required,
as were the existing two incorrect retirement expectations. Both complete native
designs emit successfully, and Click's emitted contract inventory contains no
four-phase modules/adapters. Existing firtool `VerbatimBlackBoxAnno` warnings remain.
Physical cells, analog behavior, compiler-built applications, real Pi behavior and
Chiselator execution remain outside this digital verification record.

Both complete SoC exports passed the MCU adapter's generated-reset and equivalent
packed-coverage checks. The three Python adapter tests passed as well.

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase SoC | 152 | 16,612,992 | PASS |
| Native Click SoC | 126 | 13,403,880 | PASS |

Recorded semantic hashes:

- Four-phase: `60f883b27e965185b02210f94f85553747be8b78ba9ec221b60e415a392b9516`
- Click: `b09ddbe52d588c127bcf5cc835c93672dad15de39ad126f2a01dd8f4ac80d032`

An initial complete-chip validation rejected unregistered clocked helper scopes;
the helpers were subsequently inlined. The scalar mapping runs then exposed the
flat-reset assumption (Click) and exceeded 600 seconds (four-phase). The final
results above use the documented adapter, not a bypass of those failed runs.

## Retained-sleep verification record

On 2026-10-07, the full `test` task passed 39 tests in six suites. After the final
sampling-update change, all 17 affected tests passed again: eight SleepSpec,
seven SocSpec and two FabricSpec. The update now triggers a fresh conversion,
preventing repeated accepted interval changes from postponing sensing. Both
native variants also passed reset with the service clock gate closed and a
valid, locked image. No tests were skipped, canceled or pending.
The interruption test then passed a tighter rerun using immediate MMIO time
reads and a bounded expected delta, so host transfer time cannot hide lost ticks.
The eight-test sleep report is retained in `build/sleep-suite-report.xml`; the
latest focused report is under `verification/target/test-reports/`.

The sleep integration runs use accelerated reference
clocks and the documented small-memory long-duration fixtures. The nominal
4 kHz model period is checked separately. None of these results measures analog
oscillator accuracy, power, area, physical clock gating or metastability.

All nine Python tests passed: five export-adapter controls and four oscillator
model checks. The large paired endpoint probe initially exceeded the library's
60-second compile limit in concurrent and sequential runs. The adapter now gives
only generated-probe compilation the same bounded 600-second allowance as probe
simulation; it preserves every driver, assertion and coverage requirement.

The unaugmented paired fallback then exceeded 600 simulation seconds for
four-phase and reported inactive `commit_valid` coverage for Click. The added
clock-enabled campaign resolved that stimulus gap; no RTL or endpoint was removed
to make export checking pass. Both production-capacity digital exports passed
with `--soc --vector-coverage --sleep-clock`:

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase SoC with retained sleep | 152 | 25,190,352 | PASS |
| Native Click SoC with retained sleep | 126 | 20,330,352 | PASS |

Recorded semantic hashes:

- Four-phase: `6f719d2782e0cfae7429e4b6513cb48de5514e4d0cc2e9d76ed19347551ae3e9`
- Click: `154e7bba80464c45b1bc9c9ce1e20175b9237280a63d218fedd8d29f072de4e1`

The Click export contains no four-phase storage modules. The structural chip
wrappers are exercised by SleepSpec with the oscillator model; strict async
mapping checks cover their inner digital SoCs, not the analog macro boundary.

## Analog oscillator experiments

The separate [GF180 oscillator candidate](../analog/gf180-lf-osc/README.md) has a
transistor netlist, pinned upstream attribution and models, a parameter sweep,
PVT/startup/restart experiments, and independent measurement controls. Its
[characterization record](../analog/gf180-lf-osc/characterization.md) distinguishes
schematic simulation from physical qualification. The later slow-clock integration
uses that candidate's interface and nominal timing without modifying its circuit.

```text
python -m unittest discover -s analog/gf180-lf-osc -p "test_*.py" -v
python3 analog/gf180-lf-osc/characterize.py --fetch-models --suite nominal --output build/lf-nominal
python3 analog/gf180-lf-osc/characterize.py --suite sweep --jobs 3 --output build/lf-sweep
python3 analog/gf180-lf-osc/characterize.py --suite pvt --jobs 3 --output build/lf-pvt
python3 analog/gf180-lf-osc/characterize.py --suite controls --output build/lf-controls
```

SPICE runs use ngspice; on this workstation it is available inside WSL Ubuntu.
Use a fresh output directory for every campaign. The `controls` suite succeeds
only when the checker rejects a complete simulation with reset held asserted.
Each campaign first independently checks the PDK resistor's DC values, including
the documented ngspice compatibility transformation. Do not count model tests,
missing simulations, failed controls or raw PDK parser errors as analog success.

## Slow-reference and service-source shutdown verification record

On 2026-10-07, targeted runs passed 46 Scala tests across all seven suites:
17 SleepSpec/SocSpec/FabricSpec tests, 27 DeepSleepSpec/HostSchemaSpec/CoreSpec/
NativeRoutingSpec tests, and the two additional DeepSleepSpec probe-corner tests.
There were no ignored, canceled or pending tests. The final probe-corner rerun
uses 8 and 20 MHz, with 0 and 15 us startup; the complete-state and board tests
use 10 MHz and the maximum 100 us startup. All 14 Python export/model tests pass.
The first slow nominal model check exposed a hand-calculated expected-period
error; it was corrected to the independently calculated 1/7.7307 s. A Gray
monitor initially compared across POR and was corrected to reset its history;
Gray transitions during normal operation remain checked.

Both production-capacity slow-reference exports passed the unchanged MCU adapter
with `--soc --vector-coverage --sleep-clock`:

| Export | Resolved endpoints | Mapping checks | Result |
| --- | ---: | ---: | --- |
| Four-phase slow SoC | 152 | 25,247,808 | PASS |
| Native Click slow SoC | 126 | 20,377,980 | PASS |

Semantic hashes:

- Four-phase: `780d2d89b133315f5e1c617d635fbdc6046dec34ac9ff1f699e9765059721604`
- Click: `5ab5492d57e657e079ccbfc24aa629affdd870f8f0bb95b1b5af9dfcda24c96e`

Exports and checker evidence are under `build/four-phase-slow-soc`,
`build/click-slow-soc`, and their corresponding `build/*-slow-export.log` files.
The final oscillator-model bound/documentation update re-emits the same digital
netlists; it does not change the digital contracts validated above. The native
Click export still contains no four-phase storage/adapters. The generated chip
wrappers expose neither service nor LF clock inputs, and contain two explicitly
selected oscillator views. Strict mapping validates the inner digital SoCs;
complete-chip simulations exercise their wrappers/models separately.

No analog circuit or pinned transistor model changed in this integration, so the
prior LF SPICE campaign is unchanged rather than reported as rerun. A physical
fast oscillator, qualified POR/brownout source, LF layout/receiver validation,
actual Pi-adapter compatibility and whole-chip power measurements remain open.

## Compiled-firmware memory sizing record

On 2026-10-07, all four FirmwareSpec tests passed: two compiler-built RV32E C
fixtures on each native core, with full 2048-byte program and 256-byte working
RAM. No test was skipped, canceled or pending. All 18 Python tools tests passed,
including the four new firmware audit/linker controls. Production RTL did not
change in this sizing work; the prior digital export results remain applicable
and are not reported as rerun.

| Fixture | Loaded image | Static RAM | GCC stack bound | Four-phase SP / watermark | Click SP / watermark |
| --- | ---: | ---: | ---: | ---: | ---: |
| Event loop | 704 B | 16 B | 16 B | 16 / 16 B | 16 / 16 B |
| Runtime stress | 1204 B | 48 B | 88 B | 88 / 88 B | 88 / 88 B |

Each image includes startup, constants and initialized-data load copies. Both
SoCs loaded through I2C and checked CRC/start/lock, data/BSS initialization,
independent arithmetic expectations, a 16-byte guard and state across leased
WAIT. The terminal EBREAK is intentional for these finite fixtures. No simulator
preload or substituted handwritten image was used.

The chip models use a 10 MHz service source with the maximum 100 us startup and
an accelerated 500 Hz LF input to the slow-reference configuration. Nominal LF
frequency is covered by the separate oscillator-model checks; this campaign
does not measure analog timing or energy.

The original full-capacity run exceeded the harness's 90-second process limit;
it is not a pass. The final campaign uses supported repeated STARTs between
upload frames and a 300-second allowance per compiler/simulator process. It
preserves full capacity, wire transfers, watchdog behavior and all assertions.
The four-test suite completed in 12 minutes 49 seconds. Firmware compilation has
its separate 120-second limit; other clocked tests keep the 90-second default.

The build uses pinned GCC 13.2.0 and binutils 2.42, with `rv32e/ilp32e`, `-Os`,
no relaxation, M, C, libc or heap. ELF headers report ELF32 little-endian RISC-V,
RVE and soft-float ABI; disassembly is audited for the implemented instruction
set and x0-x15. The stack analysis rejects unknown/dynamic frames and recursion.
Actual links with 1 KiB program storage or 128-byte working RAM are rejected.

Binary SHA-256 values:

- Event loop: `eaad3454c08739d2c4ddb2929e3774b3beabf6bad1df59a79e88401ea73a95f6`.
- Runtime stress: `21bfa509b6d98eda799bd10ccc2cd6e3f05d76f7cc099d348357043b05cc33d1`.

Maps, ELF/binary/disassembly, source/compiler hashes and reports are under
`build/firmware/<application>/`; per-variant simulation summaries are alongside
them and full testbench evidence is under `build/soc-tests/`. These measurements
support the [memory budget](memory-architecture.md), not arbitrary future
firmware, physical SRAM integration or power/area claims. Remeasure when the
application, runtime, flags or compiler changes.

## Clock/reset schematic and integration record

On 2026-10-07, the new [clock/reset circuits](../analog/gf180-clock-reset/README.md)
passed 157 fast-source SPICE cases, 137 supply-monitor corner/ramp cases, 52
supply-event cases, and two deliberately broken-circuit controls rejected for
the expected measurement reasons. Each campaign independently checked nine PDK
resistor DC points. Netlist/model/report hashes and compact measurement ranges
are in [measurement-summary.json](../analog/gf180-clock-reset/measurement-summary.json).
These are schematic experiments, not extracted or statistical qualification.

Targeted digital runs passed 26 Scala tests: eight SleepSpec, seven SocSpec,
two FabricSpec and nine DeepSleepSpec cases. The latter includes new brownout
tests during sleep, partial upload and locked execution on both native cores.
All 28 Python tool tests pass, including production-length reset qualification
at 8 and 20 MHz and independent negative measurement controls. No skipped test,
timeout or simulator error is counted as success.

The first wrapper run exposed unknown reset state at simulation startup; the
supply model now emits an observable startup assertion and manual reset explicitly
forces the service clock on. Both reset-only and full-chip tests verify recovery.
The initial brownout fixture also advertised a 32-byte stack while allocating
16 bytes of RAM; the loader correctly rejected it. That fixture now allocates
32 bytes and both complete brownout scenarios pass. Other previously passing
cases were retained. Firmware capacities, instruction RTL and memory banks did
not change; the compiled FirmwareSpec corpus was not rerun in this clock/reset
turn. Its earlier results remain recorded above.

Both production-capacity exports were regenerated and passed
`--soc --vector-coverage --sleep-clock`: four-phase has 152 endpoints and
25,247,808 mapping checks; Click has 126 endpoints and 20,377,980 checks.
Their semantic hashes remain `780d2d89b133315f5e1c617d635fbdc6046dec34ac9ff1f699e9765059721604`
and `5ab5492d57e657e079ccbfc24aa629affdd870f8f0bb95b1b5af9dfcda24c96e`.
Evidence is under `build/four-phase-reset-soc` and `build/click-reset-soc`.
The new wrapper/reset logic is tested separately; the strict inner-SoC contract
does not characterize analog IP.

```text
python tools/sbt.py "verification/testOnly riscay.SleepSpec riscay.DeepSleepSpec riscay.SocSpec riscay.FabricSpec"
python -m unittest discover -s tools -p "test_*.py"
python3 analog/gf180-clock-reset/characterize.py --suite clock --output build/clock-check
python3 analog/gf180-clock-reset/characterize.py --suite monitor --output build/monitor-check
python3 analog/gf180-clock-reset/characterize.py --suite supply-events --output build/supply-check
python3 analog/gf180-clock-reset/characterize.py --suite controls --output build/clock-reset-controls
```

The LF schematic and its transistor models remain unchanged. The common model
preparation helper now uses atomic writes to prevent concurrent readers seeing
a truncated library; the transformation and prepared-model hash are unchanged.
Physical estimates are the next proposed stage and should use the selected
flip-flop memories. No synthesis area, whole-chip power or layout estimate is
claimed by this clock/reset work.

## Review fixes: recovery, host wake and storage

On 2026-10-07 the complete nine-suite regression passed **57 Scala/Icarus tests**
with zero failures, cancellations or skips. The Python controls passed **30 tests**.
A subsequent four-test FabricSpec run also passed after strengthening the coherent
snapshot test to modify a later word before the serializer reaches that boundary.
Evidence is in `build/review-regression.log`, `build/review-emit.log`,
`build/soc-tests/`, and the Scala XML reports.

The new cases cover production-ratio watchdog crashes while Groundlark is RUNNING
and SHUTDOWN, retained Pi power/lock/image and continued sensing, explicit locked
image restart, abandoned I2C writes/reads, held-low SDA, foreign-address data
traffic, queued kicks during CDC busy, lease writes without kicks, sparse register
holes, and coherent read snapshots across concurrent software updates. Scaling
checks exhaust all 4096 ADC codes and independently calculate elapsed fractions,
large tick deltas, wrap and updates during serial catch-up. The actual C event
helper is compiled and executed against mapped MMIO to detect blanket clears.

Both complete SoCs passed real I2C upload and execution of the revised firmware:

| Workload | Image | Static RAM | Compiler / observed SP / watermark stack |
| --- | ---: | ---: | ---: |
| Event loop | 728 B | 16 B | 20 / 20 / 20 B |
| Runtime stress | 1212 B | 48 B | 88 / 88 / 88 B |

Binary SHA-256 values are `8c3d0486f6a778a0c7f909c5782f1e24a72467cfdbd29de0bead147e8ec3b673`
and `87d90f3712f1abc92f9b5a154a658536728d5d11b52fdf5a73b8dde8db017595`, respectively.
Earlier firmware sizes above describe the preceding versions. The selected
2 KiB/256-byte flip-flop memories, 128-byte stack reserve and 16-byte guard remain.

The exported control token is 178 bits, down from 728; one 480-bit architectural
register bank sits outside the loop, and the 107-bit trace stays at execute output.
Groundlark allocates no software application-word bank. Elapsed time uses
fractional accumulators and bounded serial catch-up, ADC scaling is serial, and
the coherent host snapshot shares one word selector. These are structural RTL
changes, not mapped area, energy or physical timing measurements. Analog circuits
are unchanged, so their earlier SPICE campaigns were not rerun for these fixes.

Both regenerated production-capacity exports passed
`--soc --vector-coverage --sleep-clock`: four-phase has 162 endpoints and
29,472,336 mapping checks; Click has 136 endpoints and 24,547,456 checks.
Their semantic hashes are `63c4c88e171a14ff12bc0a3c389f6732126134b3d15d7fd9f08ba1c126cec91a`
and `5d2173a1d2946c0fd068eb99529b933dae0fcd1cb0068442bc3215f96a6681f9`.
Evidence is in `build/four-phase-review-soc`, `build/click-review-soc` and
`build/review-*-export.log`.

Initial export attempts exposed compiler-renamed diagnostic aliases and an
inactive operand-read path under the library's default mapping stimulus.
The register bank now uses its interface endpoints and registered primitive-port
probes. The MCU checker adds a full original bit-walk campaign with the registered
x1 storage output prefilled, allowing a valid source index and nonzero operand
to occur together. It forces no derived endpoint and retains every original
comparison, activity assertion and fallback. An independent negative control
proves that this extra stimulus activates the mux and still rejects incorrect
wiring. This changes mapping-test stimulus, not functional RTL or the library.
