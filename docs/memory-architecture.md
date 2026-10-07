# On-chip memory architecture

Updated scope, 2026-10-07: both RISCay variants use only on-chip execution and
working memory. A host may reload application firmware after total power loss;
no external memory chip is required. Boot behavior and capacities belong to an
[application profile](reusable-interface.md). Groundlark's permanent bootstrap
must start its Pi without depending on that application. Current RTL consists of cores with
testbench memory; the SoC memory and loader described here are planned.

## Initial Groundlark configuration

| Storage | Provisional capacity | Implementation |
| --- | --- | --- |
| Bootstrap, loader and minimum power policy | To be measured separately | Fixed on-chip ROM, initially synthesized constant logic; survives total power loss |
| Application firmware, constants and startup image | 2 KiB | On-chip executable RAM loaded by the Pi; lost after total power loss |
| Application data and stack | 256 bytes | On-chip flip-flop bank behind a replaceable memory interface |
| Architectural registers and control | x1-x15 contain 480 bits; additional PC/control and pipeline storage | Protocol-appropriate standard-cell storage; x0 is constant |

Compile and measure both bootstrap and application before freezing capacities.
SRAM and flip-flops are volatile; fixed ROM survives power loss and cannot be
rewritten by the Pi. A RAM image loaded only by a simulator is not a hardware
loader. Pi transfer into executable RAM is now required; persistent updates and
embedded flash remain on hold.

The earlier flip-flop recommendation covered only 256 bytes of working RAM. With
2 KiB of writable program storage, total provisional RAM is now 2.25 KiB (18,432
bits), making SRAM a stronger physical candidate. Use portable storage for RTL
bring-up, then compare available macros against complete standard-cell banks.
Keep memory separate from the CPU's circulating state token. Both protocol
variants must use the same backend, capacity and firmware for each comparison;
count their wrappers in the results.

## Groundlark cold-start and loading sequence

1. Power-on/brownout reset disables Pi power and invalidates the application image.
   The MCU enters permanent boot ROM without a dedicated boot-mode pin.
2. Bootstrap checks supply and battery validity, confirmation and restart timing
   using an ADC/timebase available with the Pi off. It needs qualified minimum
   policy in ROM; the Pi cannot supply those initial startup decisions.
3. When permitted, bootstrap enables Pi power and continues essential battery,
   timeout and watchdog supervision. A blank application must not prevent this.
4. The Pi boots from its own storage and sends the application through the proposed
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

Define bounded behavior for a missing image, failed Pi boot, low battery and a
stalled upload before implementing this sequence. Remain in bootstrap supervision
on rejected images; apply the defined shutdown/retry policy on deadline expiry.
Numeric thresholds, upload deadline and retry limits are not frozen here.
Loader activity must not suspend critical power supervision. Loading is allowed
only while the application is not executing; live patching is outside scope.

Pi power cycling alone does not erase MCU RAM because the supervisor remains
on its always-on supply. Complete supervisor supply loss requires a new upload.
Full reset remains fail-off; upload handoff is a control transfer, not warm-reset
retention. No board or loader RTL change is implied by this planning document.

Status and the programming lock do not themselves solve cold-start dependency:
an unpowered Pi cannot read status or load code. The permanent bootstrap must
decide whether Pi power is allowed without requiring a valid application or an
upload. A full MCU reset clears the lock and image-valid flag even if RAM bits
physically remain. A Pi-only reset/power cycle clears neither.

## SRAM versus flip-flops

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
