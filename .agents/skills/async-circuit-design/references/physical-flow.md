# Physical flow for asynchronous netlists

Standard synchronous tools work for async designs if you protect the async
primitives and give the tools enough structure. Their defaults will otherwise
break the circuit or quietly skip work.

## Synthesis

- Map controller primitives (C-elements, latch controllers, mutexes, matched delays)
  as don't-touch instances. Verify after synthesis that each still exists with
  the expected cells and pin connections. A graph comparison against the
  generator's intent is worth automating.
- Let ordinary datapath logic be optimized normally.
- Check what drive strengths the mapper chose. A netlist full of `_1` complex
  gates will need many repair buffers after placement. Run a matched comparison
  with `_1` complex gates excluded.
- If the hierarchical netlist writer has defects (aliasing outputs, mis-escaped
  names), fix or upgrade the tool. Don't accumulate workaround buffers.

## Electrical repair (before any timing claim)

Order: synthesis → pre-placement repair → placement → repair with placement
parasitics → CTS → global route → repair with route parasitics → detailed
route → extraction → STA.

- Set slew/cap targets per corner from the library limits (e.g. a fraction of
  each corner's max_transition). Ordinary logic does not need the tight slew
  of the async capture and request nets. Keep tight targets only on native
  request, capture, ACK and reset nets, where delay-table accuracy matters.
- Report each corner separately. A single merged report hides which corner fails.
- After repair, prove the graph is unchanged apart from buffers and equivalent
  resizes: same cells, same native pin connections, no new logic.
- Expect protected nets to stay unrepaired. The tool cannot insert buffers
  inside a don't-touch primitive or on its locked nets. Classify residual
  violations into:
  1. locked native nets, which need a parent driver or a primitive recipe change;
  2. nets the tool gave up on, which need driver upsizing;
  3. ordinary nets, which need a policy or floorplan change.

  Each class has a different fix. Don't just rerun repair.
- Watch for repair-tool bugs (for example a resizer that loops forever on a net it can't
  repair). Use a fixed tool version and record its exact version and any patch.

## Distribution networks owned by the design, not by repair

Design these explicitly and give each a delay/skew budget:

- **Wide capture enables**: a balanced tree with ≤16 loads per branch, equal depth
  and the right polarity per primitive. Budget both root-to-latest-leaf delay and
  the earliest-to-latest spread. The setup check uses the earliest leaf, the hold
  check the latest.
- **SRAM clock/enable pins**: one exclusive, adequately sized driver per macro.
- **Reset distribution**: parent-side buffers into each protected primitive's
  reset pin, with an assertion/release envelope.
- **Outputs to pads**: an explicit driver. Never connect a protected storage
  output directly to a top-level port.

## CTS for the clocks you keep

- Enumerate every clock sink independently, from the cells' clock pins and the
  Liberty definitions. Compare with what STA reaches and what CTS built.
  CTS can skip a root when a buffer sits at it. Explicit `-clk_nets` lists can
  hide this.
- Exclude async capture networks and external event pins from CTS.
- Check skew, duty cycle and pulse width at macro clock pins.
- Count the CTS buffers in area and energy.

## Floorplan

- Size the outline from the cell area at a realistic utilization (e.g. 60–70%),
  not an arbitrary large square. Sparse placement means long wires, and long
  wires mean repair buffers.
- Place macros near the logic that uses them. Macros spread across the die
  stretch every address, data and clock net.
- Placement density alone has little effect if the outline and macro positions
  are fixed. Test outline and macro moves too.

## Anchoring timing checks after repair

- Bind every stage and handshake check to protected leaf pins (stable through
  repair), not to hierarchy ports (repair moves buffers across them).
- Include added buffers in the measured paths. Never assign an assumed
  arrival time to an input that repair created.
- Re-run timing campaigns after each repair stage that changes the netlist.
