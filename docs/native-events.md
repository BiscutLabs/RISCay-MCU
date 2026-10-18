# Event pending, clear and WAIT

BD and Click intentionally arbitrate events on the work-clock edge in Services.
Each independent implementation owns one six-bit `eventPending` register, one
six-bit arrival-protection mask (`mmioEvents`) and the request-observed flag.
Telemetry contains no pending/events/clear fields and event-only activity cannot
launch a Telemetry command. There is no native event owner or MUTEX.

## Sources and readers

| Bit | Event | Origin and present commit point |
| --- | --- | --- |
| 0 | Tick | LF Gray timebase crosses to service/work; elapsed scaling publishes a nonzero elapsed interval. With no low-power timebase, the work-clock millisecond divider supplies it. Services recognizes `elapsed != 0`. |
| 1 | Due | Native Housekeeping computes deadline expiry; Services recognizes an accepted, eligible Housekeeping reply. Replacement suppresses the old deadline's event at the ordered write boundary. |
| 2 | GPIO | Two service-clock input synchronizers, then work-clock previous-sample comparison masked by `gpioEventMask`. SPI boot pins 3–6 are excluded. |
| 3 | Acquisition | Accepted physical ADC result **or a validated CPU measurement publication** for a software-owned channel. The physical ADC has native assembly/scaling but its result currently crosses into Services. |
| 4 | Lease expired | Native Housekeeping computes expiry; Services recognizes the accepted, eligible reply. |
| 5 | Host wake | Native Control accepts valid host opcode 8, then its clocked reply commits the effect. This is not raw I2C START or receipt of an unvalidated frame. |


SDA START independently requests the service oscillator; it is not host event bit
5. The asynchronous GPIO/SDA wake paths are unchanged. SPI boot pins 3–6 remain
excluded from GPIO activity through `gpioEventMask`.

MMIO 12 reads pending and clears selected bits; MMIO 16 parks WAIT until
`pending & (wakeMask | 0x30)` is nonzero. Parking and accepting WAIT retain the
existing sleep, admission, lease and completion rules. Host space 3, instance 0,
word 5 captures this same clocked register at `readStart`, freezing it for the
serial transaction. All other ABI fields and errors are unchanged.

## Ordering contract

1. Pending means at least one occurrence since the last acknowledged clear;
   repeated occurrences coalesce.
2. At the first visible MMIO request, protection starts before admission or
   Control dispatch. Every event at or after that arrival is accumulated in
   `mmioEvents` until acceptance. A clear may remove only requested bits absent
   from that protection mask. Current-edge events are ORed after the clear, so
   they always survive, including on the arrival/commit edge itself.
3. The clocked update is `(pending & ~acceptedClear) | events`. A successful
   deadline replacement additionally clears old due only. The existing ordered
   Housekeeping transport excludes an old publication at replacement; a later
   reply for a newly expired deadline may raise due again.
4. Synchronous application cancellation overrides all sets/clears and clears
   pending and its arrival state. Events during cancellation are discarded;
   events after reopening survive stale native replies and their return. POR
   clears everything. Raw watchdog reset is only immediate diagnostic/pad
   isolation, never a retained register's data or enable qualifier.
5. Event clear and deadline replacement reserve no Telemetry publication. GPIO
   outputs, application writes and samples retain their separate publication
   rules. Time/sample aging can still legitimately trigger Observe transactions.

The service/work edge is the intentional arbitration decision. The rejected
saturated Gray-counter scheme cannot distinguish a late event from no late event
once saturated, and cannot preserve the arrival cutoff. `EventReferenceSpec`
retains the executable counterexample; it is not an implementation candidate.

## Verification and accounting

`EventReferenceModel` uses unbounded occurrence watermarks as an architectural
oracle. `ClockedEventsSpec` drives the six producer commit inputs with the same
random stimulus for both variants, checks every clocked transition against that
oracle and compares checkpoint histories. `AdmissionSpec` retains the held-clear
case with a GPIO arrival behind an earlier owned response. Existing producer,
WAIT, sleep, reset, ADC, deadline and host-wire tests cover their real interfaces.

The register-view tests verify event-only activity while Telemetry is stalled,
without waiting for a native event publication. Recovery tests require fresh
post-cutoff events immediately, even with publication held. These replace checks
of the removed mirror handoff; no event-loss, retention, error or deadline oracle
is relaxed. The bank-reader and Click ownership obligations are in
[native-app-registers.md](native-app-registers.md). Area, sinks, Telemetry commands
and wake edges are recorded in [the area ledger](area-ledger.md).

The event bank remains clocked under item 15. Full routed timing, reset distribution
and physical clock/wake qualification remain item 17; digital model activity is
not a physical power measurement.
