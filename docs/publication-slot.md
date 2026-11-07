# BD command publication slot

Batch 2 of the [area action plan](native-area-action-plan.md) removes the
Telemetry and Housekeeping reservation round trips. Click keeps its independent
native reservation implementation. This document describes the BD replacement;
[verification and measured limits](reviews/bd-publication-slot.md) are recorded separately.

Services already arbitrates CPU effects, background work and application recovery
on the receiving work-clock edge. A POR-owned slot (seven elaborated bits;
six functional bits when the diagnostic tag is removed) now records its
reservation phase, recovery role, diagnostic tag, sticky revocation and recovery
debt. It stores no command or reply payload. Native Telemetry/Housekeeping banks,
their actual command senders, reply receipts and bank-reader qualification stay
unchanged. No periodic clock enters a native owner.

The slot reserves only when the client is quiet and the real channels have
returned. A grant commits on the actual CPU acceptance or recovery-command edge.
For an accepted CPU effect, it waits for the retained command to enter the real
sender. A recovery decision and that sender's acceptance occur on the same edge.
Only an accepted command can produce a publication receipt. Reuse waits for the
sender to be idle, the reply receipt's actual ACK to be low, the bank readers to
be ready and the client to accept drainage. An apparently idle pair of bridges
is insufficient while a native command is executing.

A rejected grant produces no drain receipt: it has no accepted effect. It retires
when the channels and client are quiet. Background Housekeeping work needs no
reservation, but its outstanding command still excludes a new reservation.

Coordinated cancellation sets recovery debt and permanently revokes the current
slot. It neither clears accepted payload nor fabricates completion. A Telemetry
command accepted before cancellation but not issued remains retained; it executes
and drains after cancellation releases. Ordered Housekeeping effects also drain.
Application presentation is suppressed, while retained software samples keep
their existing lifetime. A fresh recovery may start only after this work returns.
Debt clears only after the fresh recovery's qualified reply and full return.
Another cancellation revokes that recovery too. POR starts with debt asserted.

The raw watchdog reset still isolates pads and enters the existing reset
coordinator. Only its coordinated cancellation reaches the slot. The RDC audit
checks the slot's actual work clock, POR reset and cancellation connection; it
adds no native-status or payload exemption. Program/RAM Source and Return remain
native because their asynchronous eligibility capture has a different contract.

The old BD PublicationSource/RecoveryReturn exist only under verification's
legacy fixtures, preserving their component tests. The obsolete clocked boundary
and final-return receipt have no remaining users and are deleted.

The unchanged receiving-edge consumed-time acknowledgement remains in Services.
Wake demand includes accepted, returning and recovery-pending work. Maintenance
continues during a prolonged application reset. Tests hold admission, command,
reply acceptance and the actual reply-ACK return, including repeated resets at
each boundary. These are functional obligations; full-chip routed timing remains
migration item 17.
