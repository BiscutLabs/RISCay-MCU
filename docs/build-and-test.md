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
python tools/sbt.py --bootstrap test
python tools/sbt.py "fourPhaseBd/runMain riscay.bd.EmitFourPhase build/four-phase-bd"
python tools/sbt.py "twoPhaseClick/runMain riscay.click.EmitClick build/two-phase-click"
python tools/sbt.py "fourPhaseBd/runMain riscay.bd.EmitFourPhaseSoc build/four-phase-soc"
python tools/sbt.py "twoPhaseClick/runMain riscay.click.EmitClickSoc build/click-soc"
python -m unittest discover -s tools -p "test_*.py" -v
```

The bootstrap fetches and checksum-verifies only the pinned sbt launcher. It does
not install Java, the compiler, the library or a simulator. With sbt already
installed, the same task strings work directly with `sbt`.

Generated RTL/manifests and simulation evidence remain in ignored `build/`.
Each SoC emitter also produces `chip/` with internal LF and stoppable fast-source
boundaries, synthesis black boxes and separately selected simulation models. See
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

`FabricSpec` drives the shared service bus independently of the CPU to check
response stability under backpressure, exactly-once acceptance, ROM/unmapped
errors, event/clear races, deadlines, failed/stale samples, interrupted upload,
reset cancellation and zero-channel/zero-GPIO configurations. Groundlark tests
accelerate the millisecond divider and ADC cadence together; their enabled
fixture is not a deployment policy. Test watchdog clocks are accelerated too.

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
timing/metastability qualification. A compiler-generated application workload and
real Pi/analog validation remain subsequent qualification work.

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
