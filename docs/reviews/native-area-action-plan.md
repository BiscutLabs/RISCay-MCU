# Native-area action plan review

Scope: read-only source and existing-evidence review against `1f256eb`, followed
by review of the [concrete redesign plan](../native-area-action-plan.md).
Reviewer: fresh agent `area_action_plan_review`. No simulation, synthesis or
P&R was run for this planning batch. No RTL, library or mapping recipe changed.

The review supports the four structural batches and their order. Its main
findings were incorporated before delivery:

- **SRAM lifetime:** retain separate Return payload storage and native memory
  eligibility. Assembly reuse follows the word-to-Return channel's return;
  `effectsDrained` must continue to exclude Return idle. Otherwise a cycle can
  form between memory drainage, publication ACK and Return release.
- **Reservation consolidation:** Telemetry/Housekeeping's five auxiliary
  channels begin and end in the existing work-edge arbitration. Keep that
  receiving-edge slot and actual native command/reply path; delete the duplicate
  native Source ownership rather than size its eight long guards first.
  Program/RAM Source eligibility has a different asynchronous consumer and
  cannot be replaced with a clocked flag by analogy.
- **Cancellation:** POR starts with recovery debt and no completed history.
  Accepted POR-owned command loans survive cancellation, including before issue.
  Drain them before fresh recovery. An idle-looking channel pair is not proof
  that a command completed: record acceptance and reply, then observe full
  return and bank readiness. Repeated cancellation revokes old recovery too.
- **Control:** computing CRC on Stored is supported by the invariant that
  pending loader word/CRC cannot change before Stored consumes them. Keep
  Services' existing external state view in that batch. Price the new closed
  EventRegister bank as flip-flops, not as the cheaper pipeline latches it replaces.
- **Bank folding:** perform it after reservation consolidation, separately.
  Preserve commit qualification, optional software-sample retention, reader
  inhibition, held pre-commit effects and Housekeeping's consumed-time value.
  Click retains native phase/bank-completion semantics independently.
- **Budgets and performance:** the proposed BD payload/control caps are feasible
  design budgets, not historical count assertions. The 1.60 mm² integrated
  goal is a stretch gate, not a prediction. SRAM crossing reuse removes hardware
  copies but still performs four byte transactions and may lose return overlap;
  unchanged deadlines and measured work edges remain mandatory.

The draft initially described SRAM Return lifetime too broadly and left queued
cancellation/POR slot initialization implicit. Both were made explicit. The
plan keeps full-return/rearm, protected primitive graphs and physical checks;
none may be weakened to meet a storage or area budget. Independent review of
the actual implementation and its measurements is still required per batch.
