# Host status, telemetry and programming lock

Required design contract, 2026-10-07. Applies identically to four-phase bundled
data and native two-phase Click. Both SoCs implement this baseline behavior.
The [SoC contract](soc-contract.md) defines the concrete protocol and limitations.
The [reusable interface](reusable-interface.md) assigns logical service/word
addresses. Common services have no Groundlark dependencies.

## Status interface

Expose status over the same proposed I2C connection used for uploading. No extra
status or lock pins are needed. A permanent hardware endpoint reports status
without depending on the uploaded program; reads remain available when that
program is absent, locked, faulted or stalled, while the MCU and bus are powered
and out of reset. Hold a coherent snapshot for each status read transaction.

| Field | Meaning |
| --- | --- |
| `MODE` | BOOT, LOADING, READY, RUNNING or FAULT; reported from the actual controller state |
| `PROGRAMMED` | A complete application image passed loader validation and is eligible for execution; never inferred from nonzero RAM contents |
| `PROGRAM_LOCKED` | Sticky hardware write protection is active |
| `CAN_PROGRAM` | Loader is unlocked, application is not executing, and controller can accept a new upload; validity alone does not imply writability |
| `BUSY` | An accepted loader operation has not completed |
| `LAST_ERROR` | Most recent loader rejection/failure, including locked, busy, range, incomplete-image or integrity error; reads have no clearing side effects |

`PROGRAMMED` and `RUNNING` are distinct: a verified image may be waiting to start
or may have faulted. Neither field proves host readiness or application health.
Read-only measurement channels and profile application data are required below.
Heartbeat and a serial diagnostic console remain outside scope.

## Generic measurements and application telemetry

Use the same I2C target for read-only measurements; no additional data pins or
separate serial console are required. Measurement channels carry neutral values,
units and freshness metadata. Profile-specific meanings and application registers
live in [profiles/](../profiles/README.md).

| Field/group | Meaning |
| --- | --- |
| `VALUE` | Signed 32-bit value with physical interpretation given by UNIT and SCALE10 |
| `FLAGS` | Sample valid, stale, never sampled, source fault and calibration applied; nominal conversion must not be reported as calibrated |
| `AGE_MS` | Age of the last successful sample at snapshot time; saturates rather than wrapping; no-sample flag makes age unusable, and reset reason identifies lost continuity |
| `SEQUENCE` | Counter incremented on each published acquisition result, including failures; host reads do not advance it; wrap/reset are not evidence of freshness |
| `UNIT`, `SCALE10` | Fixed descriptors for each channel; physical value = VALUE * 10^SCALE10 in UNIT |
| Application data | Profile-specific read-only words, versioned separately from common loader/device services |

Publish each acquisition result atomically with its validity, calibration status,
sequence and the last successful sample's capture time. A failed conversion must
not refresh that timestamp. Capture a coherent snapshot for a host read, including
the age calculated at that instant; bytes from different samples must not mix.
A source failure invalidates the current reading. If the numeric register retains
the previous value, flags and age must identify it as an invalid historical value.
Reads must not clear faults, alter outputs/policy or refresh sample age.

The telemetry endpoint remains accessible before application programming and
while the programming lock is set. A profile may publish unavailable samples
until its producer is active; Groundlark requires permanent sensing/bootstrap
measurements before the application starts. Endpoint availability alone does not
guarantee fresh measurements: report stale/invalid data if acquisition or its
producer stalls. Freshness must not depend on the application claiming it is
healthy. Loss of the service clock causes an independent watchdog reset; after
clock recovery, the retained LF count advances sample age to expose staleness;
the reset reason reports application recovery. The host endpoint needs the service clock to respond. Uploads and
host reads must not suspend required board safety functions.

The programming lock protects application code and metadata, not telemetry
updates. Normal sampling continues while locked. Age limits are build parameters;
calibration flags and wire encoding are defined in the SoC contract. When
measurements drive control decisions, telemetry must describe the same data.
The bounded `SAMPLE_PERIOD` and `WAKE` commands remain usable while locked;
neither modifies the image or its validation metadata. Retained sleep preserves
RAM, validity and programming lock, and the service-clocked I2C endpoint remains
available. See [retained sleep and clocks](sleep-and-clock.md).

Groundlark maps measurement 0 to battery millivolts and its application area to
supervisor mode, power/shutdown/ACK and faults. See its
[profile](../profiles/groundlark/README.md). Those names are not built-in MCU
registers, and a generic channel declaration does not add sensing hardware.

## Image lifecycle and protection

1. Full MCU reset enters BOOT, clears `PROGRAMMED` and `PROGRAM_LOCKED`, and
   discards in-flight loader commands. RAM bytes need not be cleared; none may
   execute until a new image has passed validation.
2. An accepted BEGIN invalidates any prior image before the first write and
   enters LOADING. Reject BEGIN if locked or the application is executing.
3. Writes must lie within the declared application range. The loader tracks
   completeness, validates supported ABI/resource requirements, consistent image
   identity/metadata, length/entry point and transfer integrity. Application ID
   is descriptive, not a fixed Groundlark-only firmware restriction.
   Partial or rejected images never become executable. Data-transfer ACK is not
   a substitute for reporting the operation's accepted/completed status.
4. Successful validation enters READY and sets `PROGRAMMED`. Metadata and the
   validated bytes must describe the same image. A failed upload remains in
   permanent profile bootstrap with `PROGRAMMED=0`.
   Raw code/metadata writes are permitted only as part of the active LOADING
   session; READY/RUNNING images cannot be modified by ordinary stores, even
   when unlocked. Replacement must begin with an accepted BEGIN that invalidates
   the image before mutation. This prevents execution of changed-but-still-valid
   bytes between validation and lock/start.
5. LOCK is optional and sets a write-one hardware latch. Accept it only with a
   valid image and no pending image mutation. Repeating LOCK is idempotent.
   There is no command to clear it. Locking does not start or stop the application.
6. START requires a valid image. START_AND_LOCK checks the same preconditions and
   sets the lock before allowing execution in one ordered operation. The normal
   host workflow should use START_AND_LOCK after checking validation results.
7. While RUNNING, reject programming even when unlocked: live replacement of
   executing code is outside scope. An unlocked READY image may be replaced with
   BEGIN. Re-entering the loader from running firmware requires a future explicit
   quiescence/handoff contract; it is not implied by an I2C write.

The hardware lock gates all normal write paths to application code and its
validation/entry metadata, including host and CPU stores. Protect boot ROM
unconditionally. Working RAM, stack and normal peripheral controls remain
usable. The application cannot modify the validity/lock latches through ordinary
stores. Report a rejected operation without changing protected memory or metadata.
This is reset-scoped write protection, not firmware authentication.

Serialize commands at the point where memory writes commit. A lock cannot be
reported complete while an earlier write can still take effect; a later write
cannot slip through a stale permission check. Do not reuse commands from before
a reset. Validate any queued request against the current protection state when
it commits. The protection applies in both protocol wrappers under backpressure.

## Reset and power ownership

| Event | Image validity | Programming lock |
| --- | --- | --- |
| Host reboot or host rail off/on, MCU supply retained | Preserved | Preserved |
| Retained sleep with MCU supply maintained | Preserved | Preserved |
| I2C STOP, bus recovery or host-interface reset | No new validity; a discarded partial transfer stays invalid | Preserved |
| Application fault or a local CPU-only restart that does not assert full MCU reset | Preserved if protected bytes remain unchanged; no automatic permission to execute | Preserved |
| Application watchdog reset (CPU and CPU transaction bridges) | Preserved; RUNNING/FAULT becomes READY, explicit START required | Preserved |
| Full MCU manual/POR/brownout reset | Cleared | Cleared |
| Complete loss of MCU supply | Lost; cleared on restart | Cleared on restart |

Full MCU reset applies the profile's safe output values. In Groundlark this cuts
Pi power, so it is not a harmless unlock while the Pi keeps running. Application
watchdog recovery preserves permanent supervision, GPIO ownership, sensing and
timekeeping, plus the validated image and its lock. The host may explicitly
START the retained image after recovery. Host reboot, malformed packets and bus
recovery cannot unlock.

Status and locking prevent accidental reprogramming after a host-only restart.
Each profile must address its host power dependency. In Groundlark, permanent
ROM (or fixed hardware) must qualify the battery, start the Pi when permitted
and maintain supervision with `PROGRAMMED=0`; it cannot wait for an upload first.
A project with an independently powered host can wait for an upload in boot ROM.

## Acceptance checks

Run common checks on both protocols for each profile, plus Groundlark's boot
and power-specific scenarios:

- Cold-start invalid RAM with the Pi off; valid supply conditions allow the
  permanent bootstrap to start the Pi before any upload occurs.
- Read status throughout boot, upload, validation, execution and faults; each
  response is coherent and remains available with missing/stalled application code.
- Reject incomplete, corrupt, inconsistent-metadata/ABI, out-of-range and busy uploads
  without entering them.
- Lock a verified image, then reject host writes, CPU code stores, BEGIN and
  metadata changes while continuing to allow status reads and working-RAM writes.
- Race writes/validation/lock/start with delayed acknowledgements; verify no
  protected write commits after lock completion and execution sees validated bytes.
- Exercise Pi-only and bus resets while locked; verify full MCU reset clears both
  flags, returns to bootstrap and discards stale queued commands.
- Reject premature lock/start requests; exercise idempotent LOCK and atomic
  START_AND_LOCK without dropping Pi power.
- Read telemetry across sample updates, ADC failures, aging and timebase faults;
  reject torn snapshots and stale-as-fresh results. Cover sequence wrap/reset and
  reads that overlap upload, lock and application handoff.
- Keep status/telemetry readable while locked and without a programmed image;
  verify reads do not clear faults, change policy or interrupt supervision, and
  that the lock does not prevent new ADC results from being published.

Source-stopping builds require the address-only I2C wake probe and wait described
in [sleep and clocks](sleep-and-clock.md). The probe contains no loader command;
do not use retries of WRITE/BEGIN as a wake mechanism. Status and locked-image
telemetry remain available after wake without an additional pin.

Core suites cover the ISA/protocol in isolation. SocSpec, FabricSpec, SleepSpec and DeepSleepSpec
exercise the implemented host, loader, memory, reset, telemetry, board and retained
sleep paths; these directed suites are not exhaustive reset/timing or physical
qualification.
