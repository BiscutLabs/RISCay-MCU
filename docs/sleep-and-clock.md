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
decodes it and captures a target for its own native elapsed-time engine. A
POR-owned state token subtracts the previously processed target modulo 2^32.
One native four-bit step iterates one through eight times per coalesced delta,
retaining exact fractional milliseconds between updates. Work is bounded by
the 32-bit delta width, not by the number of missed ticks. No general multiplier
or divider is instantiated. The [elapsed contract](native-elapsed-contract.md)
separates maintenance throughput targets from physical qualification.
A clocked scaler boundary publishes one coalesced elapsed observation. Independent
measurement ingress consumes it immediately; the separate native
Housekeeping loop orders it with timer/cadence writes. Only the final housekeeping
publication advances consumedGray; native internal completion and the earlier
scaler publication cannot acknowledge LF work.
Target changes during arithmetic, publication stalls and return drainage enter
later transactions. Pending work and bridge drainage inhibit retained sleep.
One-tick replies grant observation credit only while their target still matches
the live synchronized count; delayed replies preserve elapsed time but cannot
pretend missed GPIO observations occurred.

The production nominal quantum is 129354 us. A single tick is bounded for this
engineering configuration by 83333..200000 us. CPU deadlines, NOW_MS, leases and
requested sample periods remain **nominal milliseconds**, quantized to LF ticks.
They are not a 1 ms-resolution wall clock. The untrimmed source has no runtime
calibration. Nominal time wraps at 2^32 ms; deadline offsets must be below 2^31 ms.
The source tick counter wraps independently; a complete source-counter wrap during
a service outage cannot be reconstructed.

Application firmware chooses its policy and must account for the published
oscillator bounds and coarse time resolution. No shutdown, restart or halt-line
qualification policy is implemented in hardware or mask ROM. GPIO changes can
wake the CPU independently of the LF tick; firmware owns any subsequent filtering.

Sample ages accrue the slowest-reference upper time bound. Freshness reserves an
additional sub-tick phase margin. The production configuration uses a nominal
1000 ms sample request and 3000 ms freshness budget. Programmable periods are
bounded by conversion time, coarse resolution and the frequency envelope; query
timing instance 1 rather than hard-coding the old 3..98 ms limits. Sensing remains
mandatory. Interval changes apply between conversions on a maintenance tick and
trigger an immediate acquisition, so repeated writes cannot starve sensing.
Regular intervals round up to source ticks; missed acquisitions coalesce rather
than replay. SPI pin timing and full-frame MISO capture run on the fast source;
native SPI controllers own conversion/priming, assembly, scaling and retirement.
The complete waveform runs without native per-edge feedback, so a stalled native
consumer cannot stretch SCLK. Busy covers admission, waveform, buffered capture,
native processing, publication and crossing return; none may be gated halfway.
Conversion age accumulates upper-bound elapsed time from admission and survives
publication stalls and application reset. Both host and CPU reads retain
that age, including a coincident publication tick. The unstalled digital allowance
is 32 half-periods plus 32 service edges and 2 us of native processing; it still
requires physical qualification. CPU and I2C service boundaries also use the fast source.
This cadence is generic measurement configuration, not application policy.

## Fast-clock shutdown and wake

The work gate retains its two-flop demand synchronization and falling-edge
update. Ordinary CPU/control, ADC/SRAM, host/GPIO and reset activity reload the
existing seven-edge grace interval. That interval may expire while explicitly
tracked elapsed/housekeeping/telemetry maintenance is active; full demand still holds the
gate open until publication and bridge drainage finish. This avoids extending
an already safe maintenance interval by another unconditional seven edges.
BD telemetry ACK return is a clocked bridge output, already qualified by the
bridge's synchronized request return. Click acceptance returns its reply bridge
to idle directly. Neither case permits an outstanding effect to disappear during
a handoff. This is digital integration, not physical clock-gating qualification.

CPU admission uses one native credit. Boot WAIT or a leased event WAIT is
eligible for sleep only while that grant is available; a held prior response
cannot authorize sleep. An unused grant creates no clock demand. BD recycling
waits for full response request/acknowledgment return, and both variants retain
retirement without a service edge. The clocked-client grant crossing and
synchronized completion-drain observation remain explicit boundaries.

An accepted program/working SRAM transaction keeps the service island awake
until its native byte sequence, word completion and all request/reply crossings
have returned. The execution credit and all crossings are POR-only, so an
application reset cannot cancel accepted stores or prematurely grant sleep.
All three SRAM macros remain
powered during retained sleep; CEN is inactive and their service clock stops.
There is no refresh or memory power gating. See [SRAM integration](sram-integration.md).

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
an I2C START edge, POR or watchdog reset enables the fast source. GPIO must
remain stable through oscillator startup and synchronization for reliable event
capture. The work gate opens only after its normal synchronization frontier runs.
A short maintenance hold drains wake pipelines; I2C activity additionally holds
the source for 4096 service cycles after a captured START or selected activity.
A rejected address cancels that retry hold; a foreign transaction's data edges
do not extend it. A selected transaction holds the work gate open through STOP,
final read NACK or an inactivity timeout and its drain interval. The timeout is
262144 service cycles without a synchronized line edge (13.1072..32.768 ms over
20..8 MHz); it releases SDA and discards an incomplete command. Static low SCL
or SDA cannot continually retrigger wake, including after host power disappears.
Repeated real STARTs can still wake the MCU; this is not a bus-noise filter.
No CPU wake occurs merely because the host reads status or telemetry;
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
Holding SCL low alone is not a wake mechanism. Bit-banged clients use the same
address-only probe and retry window. Ordinary existing host
traffic remains valid in builds with source stopping disabled.

## Watchdog and reset

Production watchdog timeout is 32 raw LF edges, nominally about 4.14 s and
2.67..6.4 s over the assumed envelope, with a two-edge reset hold. Synchronizer and
heartbeat-handshake latency apply to the time since software's last kick.
A stalled service source cannot stop it. A halted/spinning application gets no
automatic kicks; bounded leased WAIT and unprogrammed bootstrap retain their
existing exemptions. Sleep lease expiry wakes the CPU and ends automatic service.
Lease writes themselves do not kick; firmware writes the magic key explicitly.
Busy kick requests are retained until the crossing is acknowledged (coalescing
multiple busy requests into one pending kick).

LF failure still stops both timer and watchdog. Detecting LF failure would require
another independent reference or external supervisor; that is not claimed here.
The raw application-reset qualifier catches short pulses and restarts eight
ungated service edges on every pulse. Its conservative 350 ns minimum at 20 MHz
is pulse-observation history. R1 keeps native producers intact until their
clocked consumers acknowledge closure; CPU-facing bridge state remains POR-owned
and rebases synchronously while closed. Qualified watchdog reset immediately
isolates application outputs, records native debt and requests fast-source restart.

The digitally verified R2a repair separately counts 64 continuous service edges of
native reset after all rebase receipts, then 64 edges after its release while
core reset and cutoff stay held. Actual receipt withdrawal is also mandatory.
Each interval is conservatively at least 3.15 us at 20 MHz, covering the known local
1.55 us guard observation with margin. The supported 250 ns digital timing-policy
cap does not change. It is not a physical settlement bound. The two-edge LF hold
remains separate. Complete reset-tree, core-startup, skew and recovery/removal
qualification remain open; longer counters alone do not establish them.

Mode/admission/loader logic observes reset through a POR-owned two-flop service
copy, and the coordinator retains `forceRun` through actual closure and restart.
The gate additionally synchronizes the full demand, including changes caused
indirectly by application reset, before its falling-edge enable register.
These extra service cycles fit within the existing wake hold and probe wait.
The ungated oscillator wake still uses raw reset so a stopped source can start.
Digital tests exercise watchdog edges between service edges and check complete
gated pulses; analog metastability and physical gate timing still need closure.
The device service's word 8 reports a saturating service-observed crash counter;
it is POR-only and distinguishes successive application recoveries.
ADC/samples, elapsed-time accumulator, loader/image/lock and LF counter retain
state. The generic boot ROM restarts a retained valid image unless ENTER_LOADER
requested a hold. GPIO outputs default to disabled on watchdog recovery; the
generic retention option preserves ordinary GPIOs, while shared SPI outputs are
always released before ROM reclaims the bus. There is no board-owned output path
or permanent application controller. See the [boot contract](generic-boot-contract.md).
Watchdog reset **does not reset the LF oscillator**. Only POR/brownout reset drives its
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
The START-capture phase flop is clocked by falling SDA and samples SCL; constrain
its SCL setup/hold, event clock routing and subsequent synchronizer explicitly.
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

## Implementation ownership during async migration

Each design now owns its Platform, SleepTiming, Services and clocked peripheral
implementation, with separate native Fabric, Control, Telemetry, Supervisor,
scaling, SRAM sequencing, housekeeping, I2C and SPI ADC protocol logic. Native Control owns loader/MMIO
state and selector/producer staging. Native Telemetry
owns software GPIO/application words, pending flags and host sample records.
Native Housekeeping owns time/deadline/lease/wake-mask state, kick authorization
and low-power cadence. Clocked event capture, independent LF/watchdog timing,
heartbeat phase/ACK delivery, peripheral ingress and snapshots remain. Every pending command, reply, accepted commit, buffered
observation or SRAM accounting token keeps the work clock awake.
Application reset covers CPU, native fabric and both CPU endpoint bridges
together. The Control and Telemetry loops and their crossings are POR-only;
reset notification is retained until serialized recovery, and queued HALT or
unaccepted MMIO preparation is canceled. MODE/status projection still consumes
the synchronized reset on the original third service edge. Permanent supervision, SRAM accounting and
programming protection keep their established reset domains. The independent
LF timebase/watchdog remains necessary after other service work becomes async.


### Native I2C migration boundary

I2C protocol state is now separate native BD/Click RTL. The source-start detector,
two-flop wire sampler, captured-edge ring, inactivity counter and coherent
service publication remain clocked. Busy covers native transaction activity and
held frame/read-start effects through synchronized return; inactive foreign
payload edges do not retain the clock. Native rejection is synchronized as a
retained level and converted to one service-edge event before wake policy, so a
prior foreign-address rejection cannot cancel the next START wake hold.
The existing address-only probe, 100 us wait, 50 us entry window and seven-edge
drain guard remain unchanged. POR alone resets I2C state/crossings; frame and
read-start publication waits for local POR release. Pending frames retain
intervening watchdog-reset history. Independent LF/watchdog timing
remains necessary. See the migration checklist for qualification status.

Item 11a1 replaces the clocked frame payload copy with a control-only receipt
in each design. The native publisher retains the frame while that receipt
waits for the actual work-clock enable. Receipt acknowledgment and mailbox
capture share the same rising edge; a stopped work clock cannot consume a
frame on the ungated front clock alone. Low-power enable comes from the existing
falling-edge gate register. Pending `out.valid`, independently of ready, remains
in ungated wake demand. The unchanged snapshot bridge and clocked mailbox are
still migration candidates. See the [frame-admission contract](frame-admission-contract.md)
for current qualification status and physical timing obligations.
