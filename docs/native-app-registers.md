# Native Telemetry register view

Both independent Telemetry owners retain the application words and GPIO output/OE
in one closed native bank. Services has no payload mirror. Pending events are a
separate six-bit clocked arbitration register described in [native-events.md](native-events.md).
The command scheduler and CPU MMIO crossing remain clocked; this slice does not
provide MMIO with the work clock stopped.

## Ownership and ABI

The bank contains only the configured application words and `gpioCount` output/OE
bits. Feedback carries sample state and a unit credit, not another architectural
bank. The transform explicitly declares the bank as an input. Public native
storage and passive data allowances implement it; neither owner contains a
periodic clock, ordinary register or synchronizer.

GPIO output/OE and application selector/data retain offsets 24/28 and 48/52.
Reads are padded to the existing 32-bit ABI. Full-word aligned MMIO accesses are
required; partial masks fault, an undeclared selector write faults without effect,
and absent host words read `0xffffffff` with their supported bit clear. GPIO pads
come from closed storage plus reset isolation: each accepted write changes each
pin at most once. Sample publication, GPIO input sampling and the host snapshot
bank retain their existing roles.

## Native commit and receiver qualification

**BD.** The existing work-clock receipt captures one authorization bit on
`out.fire`. Only a live or attributed recovery reply raises bank ACK; revoked
replies drain without changing the bank. The qualified ACK clocks the native
event register. Feedback waits for base ACK, bank completion and the owner's
relative output guard. Full fork return holds the payload throughout capture.

`telemetryReturning` closes clocked readers immediately after acceptance and
reopens only after the receipt observes synchronized native reply return-to-zero.
The fork cannot return until its feedback branch has passed the bank guard and
state capture. This reuses existing completion state; it adds no synchronizer or
payload bank to BD.

**Click.** The receipt retains an authorization bit alongside its accepted ACK
phase. A standard native Click bank consumes **both** ACK polarities. Live replies
capture the new value; revoked replies recapture the old value. The fork retains
its payload until feedback acceptance, and feedback waits for the bank's guarded
output phase. Its existing Click capture, ACK guard and rearm policy remain in
force. Two clocked completion synchronizer bits compare this phase with receipt
ACK before reopening readers. There is no four-phase adapter or level-based RTZ
loop in this path. This is functional parity with BD, not a Click physical campaign.

**Host.** `readStart` is the actual snapshot receipt acceptance edge. For the
application bank it requires bank completion; other spaces read clocked state.
Application cancellation/recovery selects constant zero and does not block host
reads. A snapshot coincident with receipt acceptance captures the complete old
bank. Reads offered during the subsequent capture/settling interval wait until
completion, then capture the complete new bank. The serial snapshot remains
frozen for the transaction. There is no extra payload mirror in Services.

**CPU.** MMIO launch and owned-reply acceptance both require the explicit
`telemetryBankReady` qualification plus the existing command/recovery/return
barrier. Unrelated Control commands mask native peripheral data. Assertions
check both readers and require an owned MMIO reply to coincide with CPU request
acceptance. A data mask alone is not used as permission to capture changing data.

## Reset and pins

POR clears the native bank, receipts and event register. Application/watchdog
reset uses synchronous cancellation and the existing ordered ResetApplication
command. Application reads remain zero through recovery. Ordinary GPIO is retained
only when configured; SPI boot outputs 3–5 always clear/release. Pin isolation
stays asserted through the recovery return, so old enables cannot reappear while
the native clear is pending. Raw watchdog reset reaches only the existing
immediate pad/diagnostic isolation, never a retained data or capture qualifier.
Samples, image, programming lock, SRAM and crash accounting keep their lifetimes.

## Verification and physical obligations

Both variants run sparse-word/mask/error tests, repeated recovery, both retention
settings, revoked replies, same-edge old-bank snapshots and serial reads while
reset stays asserted. Standalone native tests randomize controller delays and
stall replies. Event-only tests and the shared event oracle verify that removing
Telemetry event transport preserves clear and WAIT semantics.

BD's repaired-map campaign inventories **every** periodic reader reached from
the native bank. Only snapshot and Control receipt D pins are allowed. It checks
per-endpoint Liberty setup/hold, the allowed same-edge old-bank capture and a
conservative next-work-edge read, even though the completion gate can delay that
read further. The bank-to-feedback ordering check uses the owner's actual loaded
paths with the same-corner 20% two-sided derate and 2 ns floor. Missing readers,
paths or nonfinite results fail; no functional path is waived.

Signed NLDM data offsets are preserved by the stage checker. A negative
contamination offset reduces hold margin; positive contamination receives no
credit until its source launch is composed. Request/ACK delays still require
nonnegative values. This fixes the two FF parser rejections without clamping
away their timing cost.

Current measurements and test evidence are recorded in [the area ledger](area-ledger.md).
Zero-wire checks do not qualify routed RC, clock skew, reset distribution,
electrical/table-range violations or the full-chip launch/return envelope.
Those remain item 17, with the separate 0.05 mm² failing-path hold-repair reserve.
