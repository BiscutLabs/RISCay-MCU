# Generic MCU boot and supervisor removal

This batch replaces the rejected fixed application controller with generic SPI
image boot. It changes both independent BD and native Click implementations.
Groundlark source, firmware and board files are outside the batch and unchanged.
The immediate comparison parent is `90ce9f7`.

## Ownership and reset

The Supervisor owners, schemas, command/reply crossings, ingress statistics and
board GPIO/register override are removed. Applications own every application word
and ordinary GPIO. The existing independent LF watchdog, sampling, image/lock
retention and close/reset/rebase coordinator remain.

SPI boot adds eight bits to native Control state and reuses the existing loader,
native CRC, SRAM reservation/Stored completion and CPU MMIO crossing. There is no
new flash hardware peripheral or periodic stage in a native owner. CPU and host
ingress alternate through one service-domain arbitration bit; an upload session
prevents transports from splicing headers or bodies. The generic SPI claim adds
two POR-owned service bits to inhibit new ADC transactions and wait for the whole
existing transaction to drain. Software bit-bangs the claimed ordinary GPIOs.

POR disables every output. The generic watchdog-retention option defaults off;
when enabled it preserves ordinary GPIO output/OE, while SPI outputs 3–5 still
release during recovery. Raw isolation, retained output projection and native
Telemetry state agree on that rule. ROM reclaims the SPI bus before driving it.
Active ROM must kick through actual progress; deliberate idle-loader waits and
reset maintenance retain their bounded watchdog-service semantics.

## ROM and external image

The pinned RV32E build produces **2,096 bytes / 524 instructions**, with a 56-byte
static stack bound. The source and binary hashes are in
`firmware/boot/rom-report.json`. Header validation uses the existing full-width
compatibility checks; only Stored commits body progress and CRC. ROM observes its
session, exact header index and verified completion, not the shared LAST_ERROR
diagnostic, so rejected concurrent I2C commands cannot abort valid flash boot.

PERSIST is an explicit unlocked, unstarted operation. ROM erases one NOR slot,
programs and reads back header/body, and commits the magic last. There is no A/B
rollback promise. POR during an update falls back to I2C; application reset retains
the request for retry. The programming lock protects loader APIs, not arbitrary
application bit-banging of externally writable GPIO storage.

## Review and export bindings

Fresh independent review found and fixed the shared LAST_ERROR race, SPI output
retention across recovery and MISO-driven GPIO wake events. Test fixes place reset
at an actual accepted service edge and exclude initialization transitions from
the GPIO-event measurement. Original failures remain in the numbered build logs.

The complete native Fabric graph was compared with the accepted parent export.
BD retains 24 native cells and Click 22. Native identities, parameters, storage,
reset and external boundary expressions remain identical. The larger ROM and
128-byte MMIO aperture change four BD and three Click input cones. BD's service
response ACK rising route predicate changes with address decoding; its common/
falling return history remains unchanged. Independently reviewed exact hashes
bind the new production graph; the unchanged 70-bit CPU source/phase/reset alias
proof passes. These are lifetime proofs, not a ROM timing result.

The guard policy drops only four BD and three Click supervisor paths. Remaining
87 BD and 70 Click selections retain their primitive identities, original
parameters, canonical families and cell counts; generated module suffixes are
reconciled. The old strict frame campaign covered an earlier arbitration snapshot; final
arbitration is covered by the chip suites and generation/RDC gates below.

## Final digital and structural evidence

The broad R8 verification run passed 750 of 790 cases. Its 40 failures were
confined to the changed ingress/arbitration and stale fixture/CRC layout checks;
the complete affected suite group then passed all 84 cases in R9. R9 separately
passed all 28 generic boot cases, including maximum-capacity page crossing,
interrupted persistence and repeated recovery. R10 passed all five physical
export/core-policy cases and the experimental SRAM byte-owner campaign. Original
failure logs are retained; no simulated deadline or effect oracle was relaxed.

The final library generation audit passes on all four portable/physical exports.
Both production RDC proofs have zero violations. The integrated fast gate passes
292 Python tests and 166 Scala cases with fresh JUnit execution reports. Windows
and Linux Python runs pass; Linux skips only the explicit Windows-path test.
The preceding strict export runs passed on the earlier arbitration snapshot;
they are not final-tree evidence. Completed-step mutation and strict-probe
campaigns are retired under the separately reviewed
[test cleanup](../test-suite-cleanup.md), which lists the lost unique coverage.

Fresh independent generic and cleanup reviews found no remaining blocker after
fixes. The final CPU/host arbitration reserves an accepted or just-enqueued host
frame while permitting genuine ROM MMIO/RAM progress. It prevents both starvation
and observation of a false idle interval. The physical export test now requires
the generic v4 architecture fields, actual ROM byte count and absence of profile
behavior, retaining all prior reset/timing/Click-purity assertions.

Both final maps and accepted repair proofs are complete. Mapped logic is
2.100657 / 2.894444 mm² BD / Click; repaired logic is 2.283901 / 3.099576 mm²,
excluding unchanged 0.466240659 mm² of SRAM. Net mapped reductions from `90ce9f7`
are 0.128738 / 0.153980 mm². Periodic clock sinks are 4,125 / 4,179, down 685 / 686.
See the [area ledger](../area-ledger.md). These are pre-placement costs, not a
new routed design or leakage/energy estimate. Final reports and graph proofs are
under `build/generic-mcu-r10/`; logs are `build/generic-regression-r9.log`,
`generic-regression-r10.log`, `generic-map-*-r3.log` and `test-suite-cleanup/`.

For the current 16-byte valid-image digital fixture, first application retirement
occurs at 9.464006 ms BD / 10.6869824 ms Click. Both retire 11,297 ROM instructions;
service/work edges are 94,620 / 106,850 and SPI edges 496 each. The service model
is 10 MHz. These are one-time boot costs, not application wake energy or silicon
latency. Groundlark firmware-loop activity is outside this MCU-only workstream.

The unchanged generic activity workload (loaded through I2C, `spiBoot=false`)
still uses 3,257 / 3,212 work-clock edges for its 43-instruction wake, lasting
271.774507 / 268.024477 us in the 12 MHz model. Its firmware, maintenance and ADC
windows complete and return to sleep. This is application-independent workload
evidence, not a Groundlark firmware port or a claim of lower wake energy.
Logs are `build/soc-tests/four-phase-physical-estimate8505647665453051113/simulation.log`
and `click-physical-estimate9597151660601558308/simulation.log`.

## Physical limits

The enlarged ROM mux, Control decode, SPI pin setup/hold, reset distribution and
full source/capture/return timing remain physical obligations. Digital tests and
structural electrical repair do not qualify them. Existing same-corner guard
policies are retained on unchanged native controller families; no guard is
shortened in this batch. Full routed/min-max-RC qualification remains item 17.
