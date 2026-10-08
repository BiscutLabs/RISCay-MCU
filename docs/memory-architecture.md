# On-chip memory architecture

Updated scope, 2026-10-07: both RISCay variants use only on-chip execution and
working memory. A host may reload application firmware after total power loss;
no external memory chip is required. Boot behavior and capacities belong to an
[application profile](reusable-interface.md). Groundlark's permanent bootstrap
must start its Pi without depending on that application. Both SoCs now contain
the memories and loader; see the [implemented SoC contract](soc-contract.md).

## Groundlark sizing budget

| Storage | Selected baseline capacity | Implementation |
| --- | --- | --- |
| Bootstrap, loader and minimum power policy | 12-byte boot ROM plus fixed logic | ROM waits for the image; permanent loader and board controller operate independently of application code |
| Application firmware, constants and startup image | 2 KiB | On-chip flip-flop RAM loaded by the Pi; lost after total power loss |
| Application data and stack | 256 bytes | On-chip flip-flop bank behind a replaceable memory interface |
| Architectural registers and control | x1-x15 contain 480 bits; additional PC/control and pipeline storage | Protocol-appropriate standard-cell storage; x0 is constant |

Keep **2 KiB program RAM and 256 bytes working RAM** as the baseline. The
[compiled sizing fixtures](../firmware/README.md) provide repeatable code/data/stack
measurements; actual future application changes must pass these budget checks.
The minimal ROM is three RV32E instructions; power policy is fixed logic in this baseline.
SRAM and flip-flops are volatile; fixed ROM survives power loss and cannot be
rewritten by the Pi. A RAM image loaded only by a simulator is not a hardware
loader. Pi transfer into executable RAM is now required; persistent updates and
embedded flash remain on hold.

The selected implementation uses **flip-flops for both writable banks**, totaling
2.25 KiB (18,432 data bits). Memory sizing did not authorize an SRAM substitution.
Physical estimates should map the complete flip-flop banks, including their
read muxes, write decoding and clocks.
Keep memory separate from the CPU's circulating state token. Both protocol
variants must use the same backend, capacity and firmware for each comparison;
count their wrappers in the results.

The 256-byte working RAM budget includes static application data, a 16-byte guard,
and a 128-byte reserved downward-growing stack. It has no heap or interrupt stack.
CPU architectural/handshake state, loader state, measurement registers and the
existing 64-word MMIO application bank are separate hardware storage; these
program/data capacities are not a count of every flip-flop in the MCU.

Compiler sizing with pinned GCC 13.2.0, `rv32e/ilp32e`, `-Os`:

| Workload | Loaded program image | Static working RAM | Static maximum stack | Guard | RAM including measured bound |
| --- | ---: | ---: | ---: | ---: | ---: |
| Finite event loop | 704 B | 16 B | 16 B | 16 B | 48 B |
| Runtime stress fixture | 1204 B | 48 B | 88 B | 16 B | 152 B |

The larger image leaves **844 bytes (41.2%)** of program headroom. Reserving 128
stack bytes, rather than just its 88-byte bound, uses 192 RAM bytes including
static data and guard, leaving **64 bytes** uncommitted. A 1 KiB program budget
cannot hold that workload; 128 bytes of working RAM cannot hold its static data,
stack bound and guard. The linker negative controls deliberately reject both.
There is no measured reason to increase either baseline capacity. These finite
fixtures exercise useful runtime paths but are not the final Groundlark application.

The measured stress call chain uses `main` (12), `batch` (32), `transform` (44)
and `divide` (0), totaling 88 stack bytes. Startup uses no stack. The report includes load
copies of `.data` in program size and both `.data` and `.bss` in static RAM size;
it does not confuse ELF file size or debug metadata with on-chip storage.

On 2026-10-07, both binaries passed real I2C upload and execution on both native
SoCs at these full capacities. The independent retirement-SP monitor and RAM
watermark both measured 16 bytes for the event loop and 88 bytes for the stress
fixture, matching the compiler bounds. Initialization, arithmetic, guard,
sleep-retained state and programming lock checks passed. See the
[verification record](build-and-test.md#compiled-firmware-memory-sizing-record).

## Groundlark cold-start and loading sequence

1. Power-on/brownout reset disables Pi power and invalidates the application image.
   The MCU enters permanent boot ROM without a dedicated boot-mode pin.
2. Bootstrap checks supply and battery validity, confirmation and restart timing
   using an ADC/timebase available with the Pi off. It needs qualified minimum
   policy in fixed hardware; the Pi cannot supply those initial startup decisions.
3. When permitted, bootstrap enables Pi power and continues essential battery,
   timeout and watchdog supervision. A blank application must not prevent this.
4. The Pi boots from its own storage and sends the application through the implemented
   two-wire I2C target interface, after reading status. If a validated application
   survived a Pi-only restart, the host does not overwrite it. See the
   [pin budget](groundlark-io.md) and [loader contract](loader-status-and-lock.md).
5. The loader bounds-checks writes, validates image length, entry point and transfer
   integrity, and marks the image valid only after a complete successful transfer.
   Partial images never execute. CRC detects transfer errors, not authenticity.
6. The Pi can request a hardware programming lock after validation, then start the
   application. A start-and-lock operation applies both as one ordered transition.
   Bootstrap transfers control without resetting the SoC or dropping Pi power.
   Normal application execution uses only local memory; status remains readable.

The baseline remains in permanent supervision with a missing, rejected or stalled
upload. It has no host-readiness detector or upload deadline; battery/shutdown
policy continues independently. Policy is validated at build time, and the third
unacknowledged shutdown timeout latches power off. Loading is allowed
only while the application is not executing; live patching is outside scope.

Pi power cycling alone does not erase MCU RAM because the supervisor remains
on its always-on supply. Complete supervisor supply loss requires a new upload.
Full reset remains fail-off; upload handoff is a control transfer, not warm-reset
retention. Numeric policy is a build parameter, disabled by default pending board
qualification. The implemented loader permits an upload to remain incomplete
while permanent supervision continues; it never executes incomplete code.

Status and the programming lock do not themselves solve cold-start dependency:
an unpowered Pi cannot read status or load code. The permanent bootstrap must
decide whether Pi power is allowed without requiring a valid application or an
upload. A full MCU reset clears the lock and image-valid flag even if RAM bits
physically remain. A Pi-only reset/power cycle clears neither.

## Earlier SRAM comparison (not the selected implementation)

SRAM is a strong candidate when storage grows, but its peripheral circuitry can
be significant for a tiny array. As an illustrative GF180 comparison, its
256-by-8 SRAM occupies 0.1472 mm2. [SRAM datasheet][sram]

The GF180 7-track DFFQ1 cell occupies 63.6608 um2. Multiplying by 2,048 bits gives
0.1304 mm2 for bare flip-flops, before read muxes, write decoding/enables, local
clock distribution, placement and routing. This is a lower bound, not a complete
RAM estimate. [Standard-cell datasheet][dff]

These 256-byte figures do not characterize the larger program-plus-data memory
or select a winner, and do not freeze GF180 as the process. Compare
complete mapped implementations, including controllers, timing closure and
standby leakage at the intended voltage and temperature. For this supervisor,
energy per wake and standby consumption matter more than peak bandwidth.

For the selected capacity, four 512-by-8 macros could form a 512-by-32 program
bank (2 KiB). Their combined published area is approximately **0.8376 mm2**.
Adding one 256-by-8 data macro gives approximately **0.9848 mm2** of macro area,
before interfaces, power routing and placement margins. The data macro would
need byte sequencing for 32-bit accesses. These are calculated candidates,
not a mapped implementation or a power result.
[512-by-8 datasheet](https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/SRAM/gf180mcu_fd_ip_sram/cells/gf180mcu_fd_ip_sram__sram512x8m8wm1/gf180mcu_fd_ip_sram__sram512x8m8wm1.html),
[256-by-8 datasheet][sram].

At the cited DFF cell area, the same 18,432 data bits alone occupy about
**1.1734 mm2**, before the standard-cell RAM's muxes, decoding and clocks.
These earlier comparisons do not change the flip-flop decision. No SRAM macro
has been instantiated; an SRAM experiment would require a separate scope change.

## Async integration and initialization

The example SRAM has a synchronous single-port interface. Its 8-bit width also
requires sequencing to serve the core's 32-bit read response. A local controller
can bridge either async protocol, but must satisfy macro pulse-width, setup/hold
and access timing, then retain the response until consumed. [SRAM datasheet][sram]

Do not wire an arbitrary request signal directly to a macro clock. Qualified
local timing is necessary; a free-running global CPU clock is not required.
Include byte sequencing and response storage in the comparison. A Chisel
`SyncReadMem` declaration alone does not supply the technology macro or its
physical integration. [Chisel memory guide][chisel-memory]

Use the existing one-outstanding-request contract and byte masks. Validate a
transaction before any write commits; return exactly one completion. Define
coordinated reset behavior, including reset during a multi-byte operation.

RAM contents are not guaranteed after power-on. Bootstrap initializes its own
working state; application startup initializes data from the validated image
and clears the required zero-initialized region before use. Do not make
an instantaneous hardware clear of every RAM bit part of the architectural
contract; that would unnecessarily constrain an SRAM replacement. Supervisor
memory stays supplied when the Pi rail is switched off.

## Verification required at integration

Test both SoCs booting from their internal ROM with an initially unpowered Pi
and invalid application RAM, then loading through a modeled serial host. Check
RAM first/last addresses, byte masks, aliasing, ROM write rejection, access errors,
backpressure, exactly-once writes and reset during each memory transaction phase.
Check firmware startup initialization and bounds using an independent model.
Inject missing, truncated, corrupt and out-of-range images, bus stalls, brownout
during upload, and failed Pi boot. Verify the loader never enters a partial image,
essential supervision continues, and successful handoff preserves Pi power.
Exercise status reads before upload, during transfer and execution, and while
locked. Verify denied writes have no memory effects, locking cannot race a
pending write, and bus/Pi resets preserve the lock. Full MCU reset must unlock
and invalidate the image; unprogrammed cold start must reach Pi power-on under
valid supply conditions. See the [loader contract](loader-status-and-lock.md).
Existing core tests remain useful but do not establish these SoC properties.

[sram]: https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/SRAM/gf180mcu_fd_ip_sram/cells/gf180mcu_fd_ip_sram__sram256x8m8wm1/gf180mcu_fd_ip_sram__sram256x8m8wm1.html
[dff]: https://gf180mcu-pdk.readthedocs.io/en/latest/digital/standard_cells/gf180mcu_fd_sc_mcu7t5v0/cells/dffq/gf180mcu_fd_sc_mcu7t5v0__dffq_1.html
[chisel-memory]: https://www.chisel-lang.org/docs/explanations/memories
