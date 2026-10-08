# Reusable MCU and host interface

The RV32E CPU RTL is already application-independent. Groundlark is the first
board/application profile, not the definition of the MCU. The logical host schema
and profile validation now exist in [HostSchema.scala](../shared/src/main/scala/riscay/HostSchema.scala);
I2C, GPIO, measurement capture, loader and both complete SoCs are implemented.
The [SoC contract](soc-contract.md) specifies their wire/MMIO behavior.

## Separation of responsibilities

| Layer | Owns |
| --- | --- |
| Shared MCU | ISA/datapath, memory transactions, generic GPIO, timer/events, watchdog/reset, host ABI, loader/protection and measurement records |
| Four-phase or Click implementation | Native handshakes, storage, timing and reset composition |
| Board/application profile | Logical pin roles, safe reset levels, sensor meanings/units, application registers, immutable startup policy and firmware |
| Physical implementation | Actual pads, analog frontend, LF and restartable fast oscillators, POR, memory macros and electrical/power-domain qualification |

The host can be a Pi, another processor or a development adapter. I2C is the
first host transport; the logical command/register model has no Linux, Pi or
I2C timing dependencies. This separation does not add UART, SPI-host, USB, JTAG
or a general-purpose interconnect. Existing optional features remain on hold.

## Logical host ABI v1

An address is `(space, instance, word)`, each an unsigned byte. Word selects a
32-bit register, not a byte of CPU memory. Wire framing uses explicit commands,
little-endian words and coherent snapshots with supported-word bits; see the
[implemented protocol](soc-contract.md#host-wire-protocol-v1).

| Space | Service | Addressing |
| --- | --- | --- |
| 0x00 | Device identity/build information | Instance 0; ABI version, application ID/version, program/working-RAM capacities, GPIO/channel counts, reset reason and retained crash count |
| 0x01 | Loader status | Instance 0; MODE, PROGRAMMED, PROGRAM_LOCKED, CAN_PROGRAM, BUSY, LAST_ERROR, IMAGE_ID, RECEIVED_BYTES |
| 0x02 | Measurements | Instance is channel; VALUE, FLAGS, AGE_MS, SEQUENCE, UNIT, SCALE10 |
| 0x03 | Timing and sleep | Instance 0; FEATURES, NOW_MS, SAMPLE_PERIOD_MS, WAKE_MASK, SLEEP_REMAINING_MS, PENDING, SLEEP_ENTRIES, TIMING_STATUS |
| 0x80 | Application data | Instance 0; up to 64 profile-defined read-only registers |

The exact logical word order is defined by `HostSchema`. Unknown words, spaces
and absent instances must return an unsupported-resource error, not alias RAM
or another channel. Host writes to read-only words must have no side effects.
Loader changes use explicit validated commands under the existing
[lock contract](loader-status-and-lock.md). The application area cannot bypass
image protection or expose unrestricted CPU-memory/peripheral writes.

The timing service is generic too. Explicit `SAMPLE_PERIOD` and `WAKE` commands
allow the host to request a bounded acquisition interval or wake a parked CPU.
They remain available while programming is locked, cannot write executable
memory, and do not override board power policy. Timing feature bits describe the
build's capabilities; absent acquisition hardware rejects interval changes.
See [retained sleep and clocks](sleep-and-clock.md) for timing limits and wake
semantics.

Read ABI and application ID/version before interpreting application words.
Common services retain the same meaning across profiles. Application layouts
are versioned independently. Application ID describes firmware/schema identity;
it must not become a hardwired Groundlark-only whitelist. Image headers must
declare the ABI, application/schema identity and required hardware resources.
The loader rejects unsupported ABI/resource requirements or inconsistent image
metadata before execution; the host checks that it selected the intended board
application. The hardware loader enforces these bounds before execution.

## Generic measurements and GPIO

A channel publishes signed 32-bit VALUE with a unit and decimal exponent:
`physical value = VALUE * 10^SCALE10`. Unit codes currently defined are 0
(unspecified), 1 (volt) and 2 (count). Other codes require explicit profile/ABI
agreement; unknown codes must not be guessed. Unit/scale descriptors are fixed
for a build. Names live in profile/SDK metadata; device ROM need not store strings.

Examples: Groundlark channel 0 is battery voltage, VALUE=12340 with Volt/-3 means
12.340 V. An unrelated counter fixture uses Count/0 and contains no battery or
Pi fields. This adds a common record format, not new sensor hardware.

Keep validity, staleness, source faults, calibration, age and sequence with every
sample. Capture coherent read snapshots, preserve the timestamp of a retained
old value on failure, and never let reads make data appear fresh. Boot/application
producer ownership is profile-specific; the host endpoint remains readable
independently of the application, with explicit unavailable/stale values when
the producer has not run or has stopped. Groundlark requires permanent sensing
before its application is loaded.

Generic digital integration uses GPIO input, output and output-enable vectors.
Profile pin roles determine ownership and safe reset values; they are not Pi
BCM numbers. Board-required reset safety cannot depend on downloaded code.
No runtime pin-mux fabric is added by these declarations. Host access to physical
controls is only through explicitly defined application behavior; read-only
telemetry must not become a way to override the Groundlark supervisor.

## Build configuration and boot policy

`McuConfiguration` describes aligned program/working-RAM sizes, 0..32 logical
GPIOs, 0..16 measurement channels and an application profile. Constructors reject
duplicate/absent bindings and ambiguous registers. The Groundlark instance lives
in [profiles/](../profiles/README.md). These parameters size the actual generated
memory/peripheral blocks and their host-reported capacities.

Memory/GPIO/channel capacities are hardware parameters: changing them creates a
hardware variant. Another application can reuse an existing chip within those
limits, using its own firmware and application data definitions. Its immutable
boot policy and electrical reset behavior must also suit that board; reloading
RAM cannot change boot ROM or pad characteristics. Both async variants use
identical configuration and
workload in any comparison. Physical ROM/pads and the ADC connection remain
unresolved; a measurement channel is not itself an ADC macro.

Every profile provides permanent boot behavior. An independently powered host
can upload while the MCU waits in ROM. If the MCU controls power to its own host,
its permanent profile bootstrap must start and supervise that host before upload.
Groundlark implements the latter policy; another project need not inherit it.
The common protocol knows nothing about battery thresholds or Pi shutdown GPIOs.
Full MCU reset clears programming lock/validity; output reset values come from
the build's board profile. Host-only and bus resets do not clear the lock.
Application watchdog recovery resets the CPU/bridges and software-owned state,
preserving the permanent controller, image validity and lock. It returns a started
image to READY and requires an explicit host START before execution resumes.
Only profile-declared software-owned application words allocate storage; sparse
word IDs are legal, holes reject, and hardware-owned words use controller outputs.

## Verification

`HostSchemaSpec` exercises a Groundlark profile and an unrelated counter fixture,
checks unknown-address rejection and channel bounds, and rejects contradictory
configurations. Both CPU protocol suites remain required. SocSpec additionally
runs generic and Groundlark configurations through each complete SoC's I2C pins.
FabricSpec covers service-bus behavior, sample failures/staleness and zero-channel
builds. SleepSpec covers both protocols' retention, timing, wake, interval changes,
watchdog recovery and permanent Groundlark supervision during sleep. These
complement the independent ISA/routing and later physical qualification.
