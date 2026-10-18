# Clocked event arbitration and retained register views

This batch preserves the service/work edge as the ordering point for independent
event producers, clear arrival and WAIT. Both implementations remove event fields
and event-only transactions from Telemetry. Click gains its own native retained
application/GPIO bank; BD gains explicit qualification of every clocked reader.
The contracts are [events](../native-events.md) and
[retained register views](../native-app-registers.md).

## Independent review and fixes

Two fresh independent agents reviewed RTL ownership and timing separately.
The RTL review found a duplicated admission predicate: MMIO data was masked while
the bank settled, but owned reply acceptance could still proceed. Both dispatch
and reply acceptance now require `telemetryBankReady`. An assertion requires an
owned MMIO reply to coincide with CPU request acceptance. Host reads during
reset still select constant zero and do not wait for native recovery.

The timing review required complete polarity/index coverage, protected endpoint
bindings, per-reader Liberty apertures and conservative treatment of signed NLDM
offsets. It also caught receipt finalization in `atexit`, whose exceptions do not
set the process exit status. The retained tool now finalizes in `try/finally`,
checks every expected row, and derates negative segments in the adverse direction.
Feedback timing uses the existing native-receiver graph-path helper at the
actual state input. It avoids OpenSTA's invalid combinational-endpoint warning;
strict warning rejection remains. No setup, hold, ACK, reset or firmware deadline
was relaxed.

The final RTL review found no remaining cutoff, WAIT, reset or Click bank-lifetime
defect. The final timing review checked both receipts and their file hashes, all
224 reader bindings and the signed FF offsets, and found no blocking issue.
Neither agent independently reran the simulation or physical campaigns.

## Evidence scope

Evidence and failed attempts are retained under `build/clocked-events/`.
The first ownership run exposed the admission mismatch and a leftover Click
retention assignment; both were fixed. Tests that required native pending
projection were replaced with the requested clocked-event semantics, while their
reset, retention and stale-publication assertions remain. The unchanged held-clear
test and the shared event oracle protect arrival-cutoff behavior.

The first fast gate passed its simulations and Python properties, but its receipt
rejected source files changed during the run. That receipt remains failed.
The extended run passed 205 of 206 tests. Its shared-ADC test conflated a scheduled
sample wake with GPIO wake: the retained diagnostic shows Housekeeping starting
conversion five at time word 360, with zero GPIO events. The test now pauses only
the fixture's LF source, drains outstanding acquisition, toggles MISO through the
same full 10 µs sleep window, then resumes LF and requires another conversion.
The original no-GPIO/no-CS assertion and deadline remain; a continuous check also
rejects any sleep exit or ADC activity during that isolated window. Both variants
pass the corrected test. The independent RTL reviewer confirmed the diagnostic
and stimulus correction. The failed log and all 13 original suite reports remain
under `extended-r1.log` / `extended-r1-reports`; the rerun is `shared-spi-r2.log`.

The final frozen-source gate, `ci-r2/receipt.json`, passes **302 Python tests and
195 Scala/export tests** (182 fast simulations, eight generic SPI-boot cases and
five physical-export tests). Both RDC structural proofs and all four strict
functional/physical export checks pass. The shared event oracle and unchanged
Admission held-clear case run on both implementations.

Both repaired maps and all ten BD bank-reader and update-stage cases pass.
The reader screen's worst derated setup/hold residuals are +27.147/+1.242 ns;
feedback-after-bank separation is +12.638 ns. Final activity, sink, area and
verification results are in the [area ledger](../area-ledger.md).

Zero-wire repaired-map measurements do not qualify routed RC, clock skew,
electrical/table-range violations or the complete reset envelope. Click receives
functional and area/sink verification, with no new physical timing campaign.
