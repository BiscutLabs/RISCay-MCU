# Review checklist for asynchronous changes

Use this before opening a PR and when reviewing one. Answer each item with a
fact or a measurement, not "should be fine".

## Architecture
- [ ] Does each new stage, register, bridge, receipt or guard exist for a named
      obligation? Could the design work without it?
- [ ] Is any value now stored in more than one place? Is each copy justified?
- [ ] Are widths the minimum the contract proves?
- [ ] Is payload storage plain latches without reset (BD), with reset only on
      control state?
- [ ] Are there any per-bit delay/allowance/isolation cells? If so, why is a
      per-stage matched delay plus STA not enough?
- [ ] Could bulk state live in SRAM, or a parallel datapath be serial, given the
      throughput actually needed?

## Clocks
- [ ] Clocked storage bits per domain: before → after. Did it go down?
- [ ] Was any clocked logic added to fix an async timing or ordering issue?
      If so, reject it and fix the async circuit instead.
- [ ] Does each remaining clock have a written obligation (independent timebase,
      pin sampling, macro requirement)?
- [ ] Were producer and consumer migrated together, with no new crossing?

## Timing
- [ ] Each delay is labelled relative, absolute or simulation-only.
- [ ] Relative delays are sized per corner as a ratio; absolute delays from the
      fastest corner. No simulation value is used as a physical target.
- [ ] Setup (earliest capture leaf), hold (latest leaf), ACK-after-capture and
      pulse width are reported at all corners with min/max RC.
- [ ] Margins below ~100 ps at zero wire RC are flagged as not yet trustworthy.
- [ ] Before any new guard: the composed path through the real return was
      measured.
- [ ] Throughput-dependent loops are tested with slow-corner delay values, and
      work is batched.
- [ ] At least one mutation control proves each class of check can fail.

## Physical
- [ ] Electrical repair ran after synthesis, placement and global routing, with
      per-corner reports.
- [ ] Residual violations are grouped (locked native / tool gave up / ordinary)
      with a fix plan per group.
- [ ] Wide enables, SRAM clocks, resets and pad outputs have explicit drivers and
      budgets.
- [ ] Every clock sink is enumerated and covered by CTS; async nets are excluded.
- [ ] Area reported as: mapped logic, repair buffers, CTS buffers, macros,
      separately.

## Reset
- [ ] Every handshake wire and C-element has a defined reset value.
- [ ] Reset release is ordered and waits for quiescence; no raw reset crosses
      domains.
- [ ] POR during an in-flight handshake or macro access is covered.

## Verification
- [ ] Digital tests randomize delays within declared bounds.
- [ ] No oracle, deadline or assertion was relaxed to make the change pass.
- [ ] Results compare against the parent revision with only this change.
- [ ] Evidence scales with the change. Simplifying the design beats documenting
      complexity.
