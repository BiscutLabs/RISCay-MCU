# Retained sleep and internal clocks

Both native SoCs implement the same timing and wake behavior. The production
emitters use the GF180 LF candidate's nominal 7.7307 Hz, a guarded 5..12 Hz
engineering envelope, and a restartable internal service-clock boundary.
These bounds are design assumptions around schematic experiments, not silicon
qualification. The analog LF circuit has not changed during digital integration.

## Time and sensing

The always-on source counter increments by exactly one LF tick. Its registered
Gray encoding therefore changes one bit per increment. At references of 1 kHz or
more, a divider retains a nominal 1 ms source tick for legacy fixtures. Below
1 kHz, each oscillator edge is one tick. The service domain synchronizes Gray,
decodes it, subtracts the previously consumed tick count modulo 2^32, and only
then converts elapsed ticks to milliseconds. Sub-millisecond remainders carry
between updates, so frequent wakes cannot round elapsed time away.

The production nominal quantum is 129354 us. A single tick is bounded for this
engineering configuration by 83333..200000 us. CPU deadlines, NOW_MS, leases and
requested sample periods remain **nominal milliseconds**, quantized to LF ticks.
They are not a 1 ms-resolution wall clock. The untrimmed source has no runtime
calibration. Nominal time wraps at 2^32 ms; deadline offsets must be below 2^31 ms.
The source tick counter wraps independently; a complete source-counter wrap during
a service outage cannot be reconstructed.

Groundlark minimum-off, shutdown grace and confirmation durations use the
fastest-reference lower elapsed-time bound, so they cannot be shortened by a
fast oscillator within the assumed envelope. Confirmations accrue only across
consecutive matching observations, reset on observed changes, and do not credit
missed ticks after a service outage. A 20 ms ACK qualification therefore takes
multiple coarse observations; sub-tick pulses are not guaranteed to be captured.
Shutdown response and off-time can be substantially longer at the slow corner.
These timing consequences must be included in board/hold-up qualification.

Sample ages accrue the slowest-reference upper time bound. Freshness reserves an
additional sub-tick phase margin. The production configuration uses a nominal
1000 ms sample request and 3000 ms freshness budget. Programmable periods are
bounded by conversion time, coarse resolution and the frequency envelope; query
timing instance 1 rather than hard-coding the old 3..98 ms limits. Sensing remains
mandatory. Interval changes apply between conversions on a maintenance tick and
trigger an immediate acquisition, so repeated writes cannot starve sensing.
Regular intervals round up to source ticks; missed acquisitions coalesce rather
than replay. ADC conversion, CPU execution and I2C run on the fast source.
The disabled-by-default Groundlark policy remains disabled until qualified board
values are supplied; this cadence is an integration configuration, not an approved
battery policy.

## Fast-clock shutdown and wake

`chip/*SocChip.sv` instantiates both oscillator boundaries internally; neither
clock requires a package input. The portable inner SoC retains explicit clocks
for testing and exports `serviceClockEnable`. With `stopServiceClock=true`, the
source stops after the CPU is blocked at boot WAIT or an eligible leased WAIT,
there is no outstanding response, ADC or configuration work, and the work-clock
gate has drained. RAM, registers, image validity, programming lock, GPIO outputs
and native handshake phases remain retained. This is clock shutdown, not supply
power gating.

Event-set wake storage responds while service clocks are absent. An unconsumed
LF tick, a configured GPIO level differing from its last synchronized observation,
I2C bus-low activity, POR or watchdog reset enables the fast source. GPIO must
remain stable through oscillator startup and synchronization for reliable event
capture. The work gate opens only after its normal synchronization frontier runs.
A short maintenance hold drains wake pipelines; I2C activity additionally holds
the source for 4096 service cycles after the last low bus level. A recognized
transaction holds the work gate open through STOP/repeated START and its drain
interval. No CPU wake occurs merely because the host reads status or telemetry;
WAKE remains explicit.

The required fast oscillator contract is about 12 MHz nominal, 8..20 MHz,
startup no longer than 100 us, and full high pulses when
stopping, followed by a low output and no edges. I2C is limited to 400 kHz in this
integration contract; the lower frequency bound accommodates at least four
service cycles in each fast-mode SCL high/low phase. The upper frequency bound makes the 4096-cycle host window
at least 204.8 us. The [GF180 schematic candidate](../analog/gf180-clock-reset/README.md)
measures 8.62..17.05 MHz across its corner campaign; the wider envelope remains
an engineering contract, not silicon qualification. ADC SCLK limits must also be checked
against its actual frequency range. `riscay_service_osc.v` is a synthesis black
box; its separately selected `_model.sv` supplies executable timing behavior.
A transistor-level fast oscillator and supply monitor now exist. Their layout,
extracted views and statistical/physical qualification remain work.

## Host wake protocol: no additional pin

A host must assume the service source is off before each new transaction:

1. Send an **address-only write probe** to the MCU and issue STOP. No opcode or
   data bytes are sent. Either ACK or NACK is acceptable for this probe.
2. Wait 100 us after STOP. Begin the actual transaction within another 50 us.
3. Perform the normal command/read. Repeated STARTs within that transaction need
   no further probe. Subsequent separate transactions repeat this procedure.

The probe may be missed during startup and must not carry a programming command.
Its late or partial reception cannot commit a payload. Do not blindly retry a
side-effecting loader command as a wake mechanism. No SCL stretching is used and
no new wake pin is needed. A Linux client needs an adapter supporting address-only
writes (for example SMBus Quick); qualify that capability on the actual Pi adapter.
A bit-banged alternative is to hold SCL low for at least 100 us with SDA released,
then produce a legal START while the source is awake. Ordinary existing host
traffic remains valid in builds with source stopping disabled.

## Watchdog and reset

Production watchdog timeout is 32 raw LF edges, nominally about 4.14 s and
2.67..6.4 s over the assumed envelope, with a two-edge reset hold. Synchronizer and
heartbeat-handshake latency apply to the time since software's last kick.
A stalled service source cannot stop it. A halted/spinning application gets no
automatic kicks; bounded leased WAIT and unprogrammed bootstrap retain their
existing exemptions. Sleep lease expiry wakes the CPU and ends automatic service.

LF failure still stops both timer and watchdog. Detecting LF failure would require
another independent reference or external supervisor; that is not claimed here.
Watchdog reset asserts all transaction resets and requests fast-source restart,
but **does not reset the LF oscillator**. Only POR/brownout reset drives its
`rst_n`. The analog candidate requires reset low during the supply ramp and at
least 5 ms after valid supply. The wrapper now connects the supply-monitor macro
to an asynchronous-assert reset sequencer. It synchronizes qualification and
counts 100,000 consecutive fast cycles before releasing LF and SoC reset.
This is at least 5 ms at the maximum 20 MHz; any fault clears the count.
Raw comparator startup chatter is contained by this hold. The fast source is
forced on during qualification, independent of the held LF/SoC reset, avoiding
a circular startup dependency. The existing `reset` input remains a manual
override; no extra supply-good pin is introduced. A watchdog reset does not
retrigger this POR sequence.

## Physical and verification boundaries

Compile the emitted filelist, chip wrapper, `riscay_reset_hold.sv`, and exactly
one view of EACH analog macro (LF, fast oscillator and supply monitor).
The LF digital interface now matches the untrimmed analog
`vdd/vss/rst_n/clk` candidate, with supplies implicit in its digital view.
There is no imaginary enable/trim DAC. Models exercise the integration; they do
not establish chip power, PVT yield, metastability or a physical netlist binding.

Physical work includes a Gray-bus skew/max-delay bound shorter than the minimum
source-tick interval, synchronizer placement, event-set storage recovery/removal,
clock gating and test enable, retained-state timing and both oscillator receivers.
Event-set reset release is synchronized before wake hold counters decrement.
Pad noise filtering and actual startup bounds also need physical qualification.

`SleepSpec` retains legacy timing/regression coverage. `DeepSleepSpec` exercises
both native CPUs through internally generated, stopped/restarted clocks with the
maximum specified fast startup, real I2C probes, fractional elapsed time, sample
aging across service outages, retained state, watchdog recovery and cold boot.
Oscillator-model tests check cancellation/restart and complete final pulses.
Some SoC reference clocks are accelerated; those tests establish behavior, not
real-time or energy measurements. All comparisons of the two architectures must
include identical memory, clocks, sensing and host traffic.

Full-SoC regression fixtures also override the POR hold to two fast cycles and
monitor startup to zero. `tools/test_reset_circuit.py` separately tests the real
100,000-cycle hold at both frequency limits, interrupted qualification, failed
clock, manual reset, asleep brownout and total power loss. `DeepSleepSpec` tests
supply faults during sleep, partial upload and locked execution on both cores.
The analog monitor's approximately 2.22 uA nominal always-on current and measured
39.84..62.02 us dip response must be included in physical power/rail analysis.
