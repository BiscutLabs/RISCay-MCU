# Timing closure for asynchronous circuits

## Vocabulary

- **Launch event**: the request or capture enable that makes new data leave a
  storage element.
- **Capture event**: the enable edge that closes (latch) or clocks (flop) the
  destination storage.
- **Matched delay**: the delay inserted on the request so that the capture event
  arrives after the data. It is one per stage, not one per bit.
- **Relative timing constraint (RTC)**: "event A arrives before event B by at least
  m", where A and B are on the same chip. Both scale with PVT.
- **Absolute constraint**: a fixed-time requirement, such as a macro datasheet
  setup or hold, a minimum pulse width, or a POR hold time.

## The constraints every bundled-data stage needs

For each stage, at every corner, with min/max RC and an on-chip variation derate:

1. **Setup / bundling**: `arrival(capture enable at earliest leaf) ≥ arrival(data at D, max) + setup`.
   Use the *earliest* leaf of the capture tree for setup.
2. **Hold**: `arrival(next data change at D, min) ≥ arrival(capture enable close at latest leaf) + hold`.
   Use the *latest* leaf for hold. The next data change usually follows the ACK
   back to the source, the source's reaction, and the data path's contamination
   delay.
3. **ACK after capture**: the ACK that lets the source change data must be
   generated after the capture is complete at every leaf.
4. **Pulse width**: every enable pulse is at least the storage cell's minimum
   width at every corner.
5. **Control hazard freedom**: control logic is speed-independent or verified under
   explicit isochronic-fork assumptions. Each such assumption is recorded as an RTC.

Report all five per stage and per corner. Report the limiting path (cells and
pins) for each, not just a number.

## Sizing matched delays

**Relative constraints.** The requirement scales with the logic, so size per corner:

```
n_cells = ceil( max over corners c of ( δ × requirement_c / cell_delay_c(load_c, slew_c) ) )
```

- `requirement_c` is the data path's max delay (setup) or the needed ordering
  margin at corner c, from STA on the mapped netlist.
- `cell_delay_c` is the delay of one chain element *at that same corner*, with its
  real load and input slew. Never take it from a different corner.
- `δ` is a small derate for on-chip variation and mismatch, e.g. 1.1–1.3. Take it
  from your process data, and record its source.

**Absolute constraints**, such as a datasheet pulse width or a POR hold time:

```
n_cells = ceil( requirement / min over corners c of cell_delay_c )
```

This is the only case where the fastest corner sets the length. The chain will
be several times longer at the slow corner. Accept that only for constraints that
are truly absolute, and record which ones they are.

**The common mistake** is to apply the absolute formula to relative constraints,
and to use the smallest number anywhere in the delay table (smallest load and
smallest slew) rather than realistic operating points. The result is chains 4–6×
longer than needed at slow corners. That costs area, throughput and energy, and
can break throughput budgets.

**Construction.** Delay lines built from a mix of cell types (similar to the logic
they shadow) track PVT within a few percent. Chains of a single delay cell
drift much further from the logic across corners, which forces larger
margins. Place matched delays near the logic they match. Constrain their routing
if your flow allows it.

## Simulation timing vs physical timing

Keep three separate things:

1. **Digital model delays**, used in RTL simulation to exercise ordering. These
   are arbitrary; randomize them within declared bounds.
2. **Physical requirements**, derived from STA of the mapped netlist.
3. **Physical implementation**, the mapped chains sized from (2).

Never copy (1) into (3). Whenever (3) changes, re-run any throughput test with
delays set to the slow-corner values of (3).

## STA setup for async netlists

- Create analysis clocks ("pseudo-clocks") at launch and capture event pins.
  These clocks exist only in the analysis; no clock is added to the hardware.
  Results must not change when the pseudo-clock period changes. Run a test that
  proves this.
- Break combinational loops formed by C-element keepers only at the reviewed
  feedback arc (for example the keeper input of an AOI-based C-element). Never
  break loops with blanket false paths.
- Use case analysis to select the handshake phase being analysed, and record each
  case. A case-conditioned pin has no arrival, so measure its driver instead and
  state the limitation.
- Run all corners × {min, max} RC. A margin measured at zero wire RC does not
  survive routing, especially margins under ~100 ps.
- Include mutation controls. Shorten one matched delay, delay one capture
  branch, or bypass one guard, and show the expected check fails. Without this,
  a passing report may simply be checking nothing.

## Composition

Local stage checks are necessary but not sufficient. Compose:

- the source's launch and retention (how long it holds data after ACK),
- the transform's min/max delay,
- the destination's capture tree,
- the return path, including any guards and repair buffers.

Before adding a guard because a local margin is small, compute the composed
margin through the real return path. In one project, a ~1 ns local hold margin
turned out to be ≥52 ns once the existing 32 ns parent ACK guard was included.

## Throughput budgets

If an async loop must keep up with an external event rate (a timer tick, a bus,
a sensor):

- Write the budget: `events per window × worst-corner work per event < window`.
- Make work batchable. Accumulate a delta or pending count and process once,
  never once per event.
- Test with slow-corner delays. A design that passes only at nominal delays
  will fail in silicon.

## Clock-free does not mean timing-free

Async removes the global clock, not timing. Every bundled-data design has
relative-timing constraints. Close them with the same discipline as synchronous
setup/hold: per corner, with RC, with variation, with negative controls.
