# Implemented SoC contract

The four-phase and native Click SoCs implement the same RV32E execution, internal
storage and peripheral behavior. Compressed instructions remain deferred. The
CPU is asynchronous; a **shared clocked service island** contains the memories,
host endpoint, timer, GPIO, measurements and permanent board controller. Its
default clock is 10 MHz. An independent watchdog clock is required (nominally
32.768 kHz). Include the island and both CPU boundary bridges in comparisons.
These are digital RTL implementations, not qualified physical cells or pads.

## Memory and CPU interface

| Byte address | Region | Permissions |
| --- | --- | --- |
| `0x00000000..0x0000000b` | 12-byte constant boot ROM | Read/fetch only |
| `0x10000000` + configured capacity | Executable program RAM | Host loader writes; CPU reads/fetches only after validation, within image length |
| `0x20000000` + configured capacity | Working RAM | CPU data reads and byte-masked writes; no instruction fetch |
| `0x30000000..0x30000037` | MMIO | Aligned 32-bit data accesses only |

All storage is on chip. Portable flip-flop banks implement RAM initially; SRAM
macro selection and its wrapper remain physical implementation work. RAM is not
reset-cleared. Image validity resets to false; application startup must initialize
its data, BSS and stack before use. No simulator preload is necessary or used by
the serial upload tests. A successful store returns data zero; read responses are
aligned little-endian words. Unmapped/protected accesses return an access error.
One accepted CPU transaction commits once; its response remains stable under
backpressure. A coordinated reset cancels pending transactions and replies, but
does not undo already committed writes.

The ROM executes `lui x1,0x30000; lw x2,0(x1); jalr x0,x2,0`. The load blocks
until START, then returns the validated absolute entry address. Control transfer
does not reset the SoC or board outputs. Registers follow the core reset contract;
the ROM clobbers x1/x2. A separate permanent board controller handles startup and
supervision, including when no application exists. The loader is fixed hardware.

| MMIO offset | Read | Write |
| ---: | --- | --- |
| 0 | Wait for START; return entry address | Error |
| 4 | Milliseconds, wrapping unsigned 32-bit | Error |
| 8 | Deadline | Set absolute deadline and arm one-shot event; use a future interval less than 2^31 ms |
| 12 | Pending events | Write-one acknowledge |
| 16 | Wait for nonzero pending events, without clearing | Error |
| 20 | Synchronized GPIO inputs | Error |
| 24 | Effective GPIO outputs | Set generic output latch; board-owned bits stay protected |
| 28 | Effective GPIO enables | Set generic enables; board-owned bits stay protected |
| 32 | Zero | `0x57444f47` services watchdog; other values error |
| 36 | Measurement producer index | Select an existing channel |
| 40 | Producer value staging register | Stage signed 32-bit value |
| 44 | Zero | Publish staged value: bit 0 valid, bit 1 calibrated; permanently acquired channels reject CPU publication |
| 48 | Application word index | Select word 0..63 |
| 52 | Selected application word | Update firmware-owned word; board-owned words reject writes |

Events are bit 0 millisecond tick, bit 1 deadline, bit 2 any configured GPIO
change, bit 3 acquisition result. Events coalesce. Set wins a simultaneous
acknowledge. GPIO uses two sampling stages; pulses must last at least three
service cycles and meet the eventual synchronizer implementation's constraints.
Blocking the CPU never blocks host status or the permanent controller.

## Host wire protocol v1

Default I2C address is **0x35**, configurable at elaboration; verify address
availability on the intended board. SDA is represented by input plus open-drain
pull-low output. SCL is an input. No stretching or multimaster MCU operation.
Use standard-mode 100 kHz or fast-mode 400 kHz with the default service clock;
the digital sampling contract requires at least eight service cycles per SCL
period and four per high/low phase. Electrical rise-time/pad qualification remains.

A write transaction begins with an opcode, followed by the exact payload below.
All multi-byte numbers are unsigned little-endian words unless described
otherwise. STOP or repeated START commits the completed frame atomically.
Incomplete/oversize/unknown commands cause no image mutation. ACK means the byte
was received; read LAST_ERROR to determine command acceptance. There is no queue
of pending writes and no deferred memory write after a command completes.

| Opcode | Payload after opcode | Effect |
| ---: | --- | --- |
| 0 SELECT | Three bytes: space, instance, starting word | Select read window; no loader-state/error clearing |
| 1 BEGIN | Eight words: length bytes, entry offset, expected CRC32, ABI, required working RAM bytes, required GPIO bitmask, required measurement count, image ID | Validate metadata, invalidate old image, start new upload |
| 2 WRITE | Two words: byte offset, data | Append exactly four bytes at next expected offset |
| 3 VERIFY | None | Validate completeness and CRC; enter READY |
| 4 LOCK | None | Lock validated image; repeat is idempotent |
| 5 START | None | Transfer to validated image without locking |
| 6 START_AND_LOCK | None | Atomically lock and start validated image |

BEGIN requires a nonzero four-byte-aligned length within capacity and an aligned
entry offset strictly below length. ABI must be `0x00010000`. Resource needs must
fit the built capacities. Image ID is descriptive and may differ from the board
profile ID; it is not an application whitelist. Header fields are immutable for
the upload. CRC-32/ISO-HDLC covers image bytes in increasing address order:
reflected polynomial `0xedb88320`, initial/xor-out `0xffffffff` (compatible with
Python `zlib.crc32`). CRC provides transfer integrity, not authenticity. Duplicate,
skipped and out-of-range WRITE offsets reject without advancing the image.

An I2C read returns a **36-byte coherent snapshot** captured when the read address
is accepted: eight consecutive 32-bit words, then a 32-bit supported-word bitmap
(bits 0..7). Unsupported words return `0xffffffff` with their bitmap bit clear;
they never wrap/alias into another resource. The master may read a shorter prefix
and must NACK its last byte. SELECT followed by repeated START is supported.
Do not use SMBus's one-byte command/block-length framing for this protocol.

Service/word order comes from [HostSchema](../shared/src/main/scala/riscay/HostSchema.scala):

- Device 0, instance 0: ABI, build profile ID/version, actual memory/GPIO/channel
  capacities, reset reason (1 external reset/POR, 2 watchdog since external reset).
- Loader 1, instance 0: MODE, PROGRAMMED, PROGRAM_LOCKED, CAN_PROGRAM, BUSY,
  LAST_ERROR, IMAGE_ID, RECEIVED_BYTES. MODE is BOOT=0, LOADING=1, READY=2,
  RUNNING=3, FAULT=4. BUSY is zero: bounded commands commit in one service edge.
  LOADING describes an incomplete upload, not a queued operation.
- Measurements 2, instance channel: VALUE, FLAGS, AGE_MS, SEQUENCE, UNIT, SCALE10.
- Application 128, instance 0: profile-defined read-only words.

Loader errors: 0 success, 1 malformed frame/opcode, 2 locked, 3 already started,
4 range/offset, 5 incompatible ABI/resources, 6 wrong state, 7 incomplete image,
8 CRC mismatch. Rejected commands preserve protected memory/metadata. A rejected
BEGIN preserves the previous image; an accepted BEGIN invalidates it immediately.
Only LOADING can accept writes; READY requires a new BEGIN before replacement.
After START, replacement/restart requires full MCU reset, including after a trap.
The host may LOCK a running valid image. A bus recovery, host reboot or Pi rail
cycle never clears the lock. Full MCU reset clears both lock and image validity.
Working RAM and permitted peripheral writes remain available when locked.

An interrupted upload may remain LOADING indefinitely; fixed supervision keeps
running. The host can restart with BEGIN while unlocked. No host-boot detector,
upload-driven power cycling or heartbeat policy is implied.

## Measurements, ADC and timebase

Measurement FLAGS: bit 0 currently valid and fresh, bit 1 stale, bit 2 no
successful sample yet, bit 3 last acquisition failed, bit 4 calibration applied
to the current successful reading. AGE_MS saturates; before any success it reads
`0xffffffff`. Each result increments SEQUENCE, including failure. Failure retains
the old numeric value/age, clears valid/calibrated, and sets fault. Reads neither
refresh age nor acknowledge anything. The entire 36-byte read is one snapshot.

The Groundlark reference emitter includes a receive-only, 16-clock mode-0 SPI ADC
controller with ADC121S021 framing (four leading bits, 12-bit sample). It discards
the first conversion after reset and uses independent CS, SCLK and MISO signals.
Default SCLK is 1 MHz, with at least 10 ms between completed conversions and the
next start. The nominal conversion is `raw * 25300 / 4095` mV, based on a 3.3 V
ADC reference/supply and the existing 23/3 divider ratio. Build parameters permit
gain/offset calibration; the default explicitly reports **uncalibrated**.
[ADC datasheet](https://www.ti.com/lit/ds/symlink/adc121s021.pdf)

This is a digital reference interface, not a selected/qualified replacement for
the TI's integrated ADC. Analog settling, reference error, divider loading,
buffering and board wiring must be qualified. SPI has no CRC/ready indication;
all-zero/all-one results are real possible codes and cannot diagnose every
disconnected/stuck ADC. Groundlark rejects out-of-range battery voltages for power
policy. Generic software producers can explicitly report acquisition failure.

The watchdog owns a separate reference clock and a held-toggle kick handshake.
Permanent bootstrap services it while the application has not started; afterward
firmware must write the key regularly, including around event waits. With the
default reference it expires after approximately one second without a kick.
Expiry asserts full coordinated reset of CPU, bridges, memories' validity state,
I2C, peripherals and board controller. Reset assertion is asynchronous; release
is synchronized to the service clock. Watchdog reason survives that generated
reset until external reset. Loss of the service clock therefore forces outputs
safe and holds the system reset until it resumes. I2C needs that clock to respond;
after recovery the reset reason and invalid/never-sampled state expose the loss
of continuity. Stopping both clocks is outside this digital watchdog's coverage.

## Groundlark permanent policy

[GroundlarkSupervisor](../profiles/src/main/scala/riscay/profiles/GroundlarkSupervisor.scala)
implements the bootstrap safety policy in fixed logic rather than requiring an
uploaded or compiler-built supervisor. GPIO 0/1 are permanently owned outputs;
GPIO 2 remains the halt input. Firmware cannot override their ownership. Stable
inactive ACK must be observed after each power-on before a subsequent stable
active ACK is accepted. A stale active ACK blocks initial startup.

Reusing the generator with `GenericBoard` permits firmware-owned GPIO and
application words. Reusing a fabricated Groundlark-specific build preserves its
immutable power policy and pin ownership; uploading a new image does not turn
those three pins into unrestricted GPIO.

States: OFF=0, RUN=1, SHUTDOWN=2, LATCHED=3. Qualified recovery permits startup;
low voltage requires confirmation. Invalid/stale/out-of-range sensing requests
shutdown immediately while running. Power stays on until qualified ACK or a
bounded timeout. Minimum-off timing applies before restart. Three unacknowledged
shutdown timeouts latch off until reset. Power-enable telemetry reports a command,
not measured 5 V or host readiness.

Fault codes: 0 none, 1 policy disabled, 2 confirmed low voltage, 3 invalid sensing,
4 forced timeout, 5 acknowledged halt. Timeout count is reset-scoped. Policy is
validated at elaboration against Groundlark's numeric bounds. **Default emission
uses a disabled policy and never powers the Pi.** Supply qualified values and
enable the policy for a board build. Tests use explicit enabled fixtures, with
accelerated milliseconds; these values are not a battery recommendation.

## Remaining qualification

Digital implementation and event simulation do not establish physical timing,
metastability, power/area, real Linux poweroff pulse compatibility or analog safety.
Both SoCs retain native CPU protocols and explicit boundary bridges. There are
no four-phase blocks inside Click's core or its toggle bridges. Strict export
checks, directed SoC tests and randomized core/routing tests have distinct scopes;
see [build and test](build-and-test.md). A compiler-built application corpus,
Chiselator runs and board/physical qualification are subsequent work.
