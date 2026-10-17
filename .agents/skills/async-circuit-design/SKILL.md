---
name: async-circuit-design
description: Use when designing, implementing, reviewing or timing-closing asynchronous (clockless) digital circuits — bundled-data four-phase, two-phase/Click, micropipelines, desynchronized designs, async SoCs/MCUs, matched delays, C-elements, handshake controllers, or GALS boundaries. Covers architecture choices that keep area low, relative-timing closure, delay sizing across PVT corners, physical repair of async netlists, reset, and review gates.
---

# Asynchronous circuit design

This skill exists because async projects fail in predictable ways: area balloons
to several times the synchronous equivalent, timing guards are sized wrongly
across corners, clocked logic creeps back in through bridges, and verification
effort grows faster than the design improves. A well-built bundled-data design
costs only a few percent more area than its clocked equivalent (the desynchronized
DLX "ASPIDA" was +1.4%). If yours is much larger, the implementation is wrong,
not async itself.

Read the whole of this file before starting. Read a reference file when its
topic comes up:

- `references/timing-closure.md` — relative timing, delay sizing, hold, STA setup
- `references/area-budget.md` — cost model, per-stage arithmetic, worked numbers
- `references/physical-flow.md` — synthesis, electrical repair, CTS, P&R for async
- `references/review-checklist.md` — gates to pass before opening or approving a PR

## The five rules that prevent most problems

1. **Decide the architecture before writing verification.** Removing a structure
   is always cheaper than proving it correct. Before adding any stage, register,
   bridge, receipt, guard or crossing, ask whether the design works without it.
   Rigorous evidence for an unnecessary structure is wasted effort.
2. **Every timing number has a kind.** Each delay is either a *relative* ordering
   (A must happen after B, both on silicon), or an *absolute* requirement (a
   minimum pulse width, a macro's datasheet setup, a POR hold time). Simulation
   model delays are a third kind: they only make digital tests pass. They are
   never physical targets. Write the kind next to each delay in the code.
3. **One matched delay per stage, never per bit.** Data bits are plain wires
   checked by STA. Per-bit delay or "allowance" cells across thousands of lanes
   are the single most common area mistake.
4. **No clock may be added to fix an async problem.** Clocked staging, mirrors and
   receipts used as a shortcut multiply storage and bring CTS, synchronizers and
   crossings back. Keep clocks only where an obligation demands them, such as
   an independent watchdog timebase or sampling an external asynchronous pin.
   Write that obligation down.
5. **Measure area, clocked state and worst-corner timing on every change.** Compare
   against the immediate parent and the original baseline. A change that "passes"
   while area or clocked storage grows needs explicit justification.

## Choosing a style

| Need | Prefer | Avoid |
|---|---|---|
| Lowest area, moderate speed | Four-phase bundled data (BD) with **latch** storage, coarse stages | Dual-rail/QDI datapaths (≥2× wires plus completion trees) |
| Two-phase signalling | Click controllers, or MOUSETRAP (latch + XNOR per stage) for lower storage cost | Phase-converting adapters inserted everywhere |
| Robustness to unknown delays in small control | QDI/speed-independent control only, synthesized and hazard-checked | QDI for wide data |
| Converting an existing synchronous design | Desynchronization: FFs → latch pairs, one controller + matched delay per block | Rewriting every block as a fine-grained pipeline |
| Very low throughput (supervisors, housekeeping) | Serial/iterative datapaths (nibble/byte/bit loops), bulk state in SRAM | Fully parallel, deeply staged datapaths |

Pipelining buys throughput. Each stage boundary costs a full-width register, a
controller, a matched delay, a capture-enable tree and a set of timing checks. A
CPU running tens of instructions per wake does not need many stages. The ASPIDA
DLX used four controllers for a whole CPU.

## Architecture rules

**Stages and storage**
- Store each architectural value once. A stage whose output equals its input
  ("receipt", "return", "copy", "mirror", "publication") is a code smell. Keep it
  only for a named obligation: reset containment, an independent stall that
  must not back-pressure, or crossing a real domain. Merge it otherwise.
- In four-phase BD, use plain transparent latches for payload. Payload bits need
  no reset: validity is carried by the handshake, not the data. Reset only
  control/phase state. (GF180 7-track: `latq_1` 43.9 µm² vs `dffrnq_1` 74.6 µm²,
  41% smaller per bit.)
- Narrow every field to what its contract proves is needed. Width multiplies
  every downstream cost: storage, capture tree, delay bundle, STA checks.
- Put bulk state (frame buffers, large register files, logs) in SRAM behind a
  serial owner rather than in latches or flops, when the throughput allows.
- Consider whether rarely-used arithmetic (scaling, conversions) can run in
  firmware on the CPU that already exists, rather than in dedicated hardware.

**Control**
- Use a small, reviewed set of controller primitives (C-element, asymmetric
  C-element, Click stage, latch controller, mutex, Join/Fork). Do not let
  synthesis restructure them: mark them don't-touch and verify the netlist
  still contains them.
- Never put general combinational logic on a request or acknowledge wire unless
  it is proven hazard-free. A glitch on a request is a spurious event.
- Rings need tokens and bubbles; prove liveness (no deadlock) for each ring and
  each Join/Fork composition, including under reset release.
- Arbitration (two independent requesters) needs a mutex with a metastability
  filter. Never resolve it with ordinary logic.

**Crossings to clocked logic**
- Minimize the number of crossings. Use one crossing per subsystem, not one per
  message type. Each crossing costs synchronizers, handshake state and usually a
  data copy on each side.
- When migrating clocked logic to async, move producer and consumer together.
  Moving one side creates a bridge plus two copies. Done piecemeal, migration
  can *increase* clocked storage.
- Track a single number in every change: clocked storage bits by clock. It
  should only go down.

## Timing rules (summary — details in references/timing-closure.md)

- **Bundling (setup):** the matched request delay ≥ δ × the data path's max
  delay, at *each* corner, where δ is a small variation derate. Check it as a max-delay
  constraint in STA from the launch to the capture enable.
- **Hold:** data must stay stable after the capture enable closes, until the
  source can change it (usually after ACK propagates back). Check it as min-delay
  in STA, including the capture-tree spread (earliest vs latest leaf). Fix it
  with hold buffers only on the failing paths STA reports.
- **Size delays per corner, as a ratio.** For relative constraints:
  `n_cells = max over corners ( δ × requirement_c / cell_delay_c )`, using each
  corner's own load and slew. Do **not** divide an absolute ns target by the
  fastest cell delay found anywhere in the library. That makes chains 4–6×
  too long at the slow corner, wasting area and throughput.
- Build matched delays from a mix of cells resembling the logic they shadow, so
  they track it across PVT (mixed-cell delay lines track within a few percent;
  single-cell chains drift tens of percent).
- **Composed paths decide, not local ones.** Before adding a guard because a
  local stage margin looks small, measure the full path through the real return
  (source → stage → ACK → source release). Often an existing guard already covers
  it.
- **Throughput budgets use worst-corner delays.** If a loop must keep up with an
  external event rate, simulate it with the slow-corner delay values, not the
  nominal model. Design the work to batch (accumulate pending events, process
  once) so that step latency never limits correctness.

## Physical rules (summary — details in references/physical-flow.md)

- **Electrical repair before timing.** Slew and capacitance violations make every
  timing number untrustworthy. Repair after synthesis, after placement and
  after global routing. Report each corner separately.
- **Design the fanout of every native output that leaves a primitive.** Wide
  capture enables, SRAM clocks and reset distribution need explicit, bounded
  trees (e.g. ≤16 loads per branch, equal depth, known polarity) with a delay
  budget. If a primitive is protected from repair, the repair tool cannot fix
  its output net. Give it a parent-side driver.
- **Anchor timing checks on protected leaf pins, not hierarchy ports.** Repair
  moves buffers across hierarchy boundaries. Leaf pins of protected primitives
  are stable.
- **Independently enumerate every clock sink** and check CTS built a path to each
  one. CTS tools can silently skip roots, e.g. when a repair buffer sits at the
  root.
- Weak `_1` complex gates (AOI222, OAI31, …) driving any real wire generate repair
  buffers; prefer `_2`, or exclude `_1` complex gates at synthesis, and compare.

## Reset

- Assert reset asynchronously everywhere; release it in an ordered,
  quiescence-checked way. Each domain releases only after its handshakes are at
  rest (all req/ack in their reset state).
- Do not wire a raw reset across domains to "keep it simple". It causes reset-
  domain-crossing (RDC) hazards: one side leaves reset while the other is mid-handshake.
- Specify the reset state of every handshake wire and every C-element.
  An uninitialized C-element is a deadlock or a spurious event.

## Working method

1. Write a one-page contract per block: interfaces, protocol, tokens, stages,
   widths, every delay with its kind, reset behaviour, and an area estimate using
   `references/area-budget.md`. Reject the design if fixed overheads (delays,
   allowances, controllers) exceed ~20% of the block's area, unless you can
   justify why.
2. Implement the smallest version that meets the contract.
3. Digital tests with randomized delays inside the stated bounds, plus negative
   controls: shorten a matched delay or bypass a guard and prove a check fires.
   A test that cannot fail proves nothing.
4. Synthesis → electrical repair → STA with relative constraints at all corners.
5. Matched area/clocked-state/activity comparison against the parent revision.
6. Review with `references/review-checklist.md`.

Keep evidence proportionate. A hash-bound provenance chain is worth having for
signoff artifacts. It is not a substitute for simplifying the design, and
documenting failed attempts in detail is less valuable than not needing them.

## Anti-patterns seen in practice

| Symptom | Root cause | Fix |
|---|---|---|
| Logic area 6–7× the clocked baseline | Per-bit allowances, guards sized at the fastest corner, many pass-through stages, reset flops for payload, clocked mirrors | Apply the architecture and timing rules above; measure each |
| Hundreds of ns of guard at the slow corner | Absolute target ÷ fastest library delay | Per-corner ratio sizing; classify each guard's kind |
| A test passes at nominal delays, fails with slow-corner values | Throughput depends on step latency | Batch pending work; budget with worst-corner delays |
| 5–14 ns slews on capture/SRAM clock nets | Protected primitive drives a wide net | Bounded capture tree in the primitive, or a parent driver per load group |
| Timing campaigns break after repair | Bound to hierarchy ports | Bind to protected leaf pins; treat added buffers as part of the path |
| CTS reports far fewer sinks than exist | Root obscured by a buffer | Enumerate sinks independently; compare with STA's clock reach |
| Clocked storage grows during an "async migration" | Half-migrated producer/consumer pairs with bridges | Migrate pairs together; track clocked bits per change |
| A small local hold margin prompts a new guard | Local metric ignores the real return path | Measure the composed path first |
