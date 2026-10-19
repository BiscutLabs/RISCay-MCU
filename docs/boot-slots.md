# External A/B boot slots and factory provisioning

The legacy format-1 SPI image and
I²C loader ABI remain supported. No application or board policy is added to ROM.
Both BD and Click run the same generic RV32E boot program through their own
native implementation.

## Factory layout

All words are little-endian. SPI addresses remain 24 bits. A factory image has
a 4 KiB directory sector, followed by equal-sized golden, A and B regions.
The stride is the configured program capacity plus the 48-byte record header,
rounded up to 4 KiB. The complete layout must fit the declared flash capacity,
which is at most 16 MiB. Legacy single-slot images retain their larger address
space limit; A/B does not silently reduce a supported MCU configuration.

| Directory word | Value |
| ---: | --- |
| 0–1 | Magic `0x32425352`, format 2 |
| 2–3 | Region stride in bytes, complete flash capacity in bytes |
| 4–6 | A base = `4096+stride`, B base = `4096+2*stride`, golden base = `4096` |
| 7 | CRC32 of the preceding 28 bytes |

Directory validation checks CRC, alignment, all three addresses, overflow and
capacity before using a slot address. A damaged directory falls back to I²C;
it does not guess the location of a golden image. The directory is factory-owned
and is never changed by runtime persistence.

Each slot starts with the existing ten image-header words, with format changed
to 2. Word 10 is an unsigned generation; word 11 is CRC32 of the preceding
44 bytes, including magic and generation. The body follows at byte 48. Its CRC
and the eight canonical loader fields retain their existing definitions.
Factory golden uses generation zero, A one, and optional B two. An unused B
region is erased. CRC supplies integrity, not authentication.

## Selection and updates

Boot checks header integrity and actual MCU compatibility: program capacity,
entry alignment, ABI, RAM, GPIO mask and measurement count. The newer compatible
A/B header is tried first (A wins a generation tie). Its body still passes the
ordinary loader CRC/SRAM path. Failure tries the other compatible field slot,
then golden, then the existing I²C loader. Each slot is tried at most once.

PERSIST still accepts only a verified, unstarted, unlocked RAM image. Before
choosing a destination, ROM checks both existing field images' bodies as well
as their headers and compatibility. It preserves the newest usable field image
and erases the other slot; if neither is usable, it writes A. The generation is
one greater than the preserved image, or one for the first field image. Generation
`0xffffffff` cannot advance: persistence fails instead of wrapping the order.

Erase/program touches only the destination's sectors. Header and body are read
back before magic is programmed and verified last. The directory, golden and
previous usable field image remain intact through an interrupted update. POR
boots from whichever complete record survives. Application/watchdog reset retains
the verified RAM image and pending persistence request, so ROM retries. A reset
just after commit can produce another equivalent generation; exactly-once flash
wear is not promised. Lock and rejection/status semantics are unchanged.

Legacy persistence retains commit-last behavior and I²C fallback after a POR
interruption. A watchdog interruption may leave an erased or partially written
magic and partially programmed format-1 header. Retrying requires NOR-bit consistency with the current
verified RAM header: `(observed & expected) == expected`. Unknown metadata and
format-2 directories with a bad CRC cannot authorize a legacy erase.

There is no runtime application-health protocol in this format. An ordinary
watchdog reset still restarts the retained valid RAM image; it does not mark an
application bad merely because it reset. Golden fallback concerns missing,
incompatible or corrupt stored images. Arbitrary application GPIO writes can
still modify external storage; the loader lock is not flash hardware protection.
Physical golden write protection, if needed, belongs to board/device provisioning.

## Generic capacity literal and resource bounds

Program capacity is a final aligned, non-executable ROM word. The reproducible
build verifies its ELF symbol and sentinel; elaboration replaces only this word
with the MCU's configured program capacity. Existing MMIO supplies RAM capacity,
GPIO mask and channel count. No MMIO address or application ABI changes.

The image is 4,224 ROM bytes (1,055 instructions plus one capacity word)
with a statically audited 188-byte maximum stack, within the existing 256-byte
minimum RAM requirement. These figures must be refreshed if the source changes.
All SPI polls and image traversals are bounded. Watchdog kicks accompany bounded
progress; a permanently busy device cannot receive an unbounded lease.

## Factory procedure

Build ordinary format-1 `.flash` application images with `tools/boot_image.py`,
then assemble the complete device image, for example:

```sh
python tools/boot_slots.py --a application.flash --golden recovery.flash \
  --program-bytes 2048 --ram-bytes 1024 --gpio-count 7 --measurement-count 1 \
  --flash-bytes 16384 --output factory.flash
```

The golden application is supplied externally. This repository does not generate
Groundlark policy or firmware. The factory programmer erases/programs the device,
then reads back its complete declared capacity. Repeat the command with
`--readback programmer-readback.bin`; it checks layout, compatibility, header/body
CRC and byte-for-byte equality, including erased regions. A failure prevents
factory acceptance. The tool creates/checks image files; it does not claim to
have programmed or electrically qualified a board.

## Full-capacity boot activity

Both variants load complete 2,048-byte images through SPI, CRC validation and
the normal SRAM loader. Time runs from initial POR assertion to the first
application instruction, including the 2 µs initial reset. Edge counters start
at POR release. Fallback corrupts both field bodies and loads golden.
These are native digital-model measurements with a 10 MHz service clock, not
silicon timing bounds or power estimates.

| Variant / path | Boot time | Work-clock edges | Service-clock edges | SPI clock edges |
| --- | ---: | ---: | ---: | ---: |
| BD, first field image | 353.740 ms | 3,537,379 | 3,537,379 | 18,288 |
| BD, both fields corrupt → golden | 1,010.868 ms | 10,108,660 | 10,108,660 | 52,592 |
| Click, first field image | 398.806 ms | 3,988,038 | 3,988,038 | 18,288 |
| Click, both fields corrupt → golden | 1,139.608 ms | 11,396,064 | 11,396,064 | 52,592 |

The model executes 425,518 ROM instructions on the primary path and 1,208,031
on the fallback path in each variant. ROM bit-banging and the retained clocked
SRAM boundary dominate this boot activity. Evidence is the `FULL_CAPACITY_BOOT`
records in `build/soc-tests/generic-ab-full-*`, selected by the complete
`GenericBootSpec` run. No application RAM is preloaded by the testbench.

## Verification and remaining physical obligations

All 69 `GenericBootSpec` cases pass across the two retained runs
`build/generic-boot/slots-persistence-r2-reports` and `slots-remaining-r1-reports`.
They cover selection, compatible-image preservation, interrupted erase/header/
commit, POR, watchdog retry, lock, corrupt directory, generation exhaustion,
legacy behavior, shared ADC bus and full-capacity primary/golden paths.
`slots-ci-r1` passes 372 Python and 197 Scala tests without skips. Both RDC proofs
and all four current export/generation audits pass in `slots-rdc-*` and
`slots-check/`. Independent final review found no remaining implementation issue.
Failed preliminary runs remain under `build/generic-boot/`.

The larger ROM creates a new mux/timing obligation. The matched maps in the
[area ledger](area-ledger.md) measure its cost; an older routed layout does not
qualify this ROM. Factory read-back has a host-level passing fixture and a
rejected byte-mutation control; no physical board programming is claimed.
