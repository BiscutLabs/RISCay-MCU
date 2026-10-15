# LF counter width decision

The A3 review retains the existing 32-bit LF counter, Gray transport and
consumed target in both implementations. No RTL, clock, reset or time ABI
changes are made. Narrowing to 8 or 10 bits needs a proven maximum interval
between counter observations with safe retained accumulation and wake ownership,
or independently retained overflow accounting. Neither is currently established.
A bound through final publication would be sufficient, but is stronger than
the minimum needed for a redesigned transport.

The LF counter advances independently. The wake circuit compares its
synchronized Gray value with `consumedGray`; the latter advances only when
the final Housekeeping reply is accepted. Separately, each elapsed-scaler receipt
advances the scaler's consumed target, and Services can accumulate elapsed time
while Housekeeping is stalled. Thus a delayed final publication does not by
itself demonstrate lost LF observations. Detecting a tick and requesting a wake
does not establish a worst-case observation/progress bound either. Native work,
retained replies, reset coordination and consumer backpressure remain separate
obligations.

For a counter of width `w`, elapsed values `d` and `d + 2^w` give exactly the
same retained counter, Gray code and modular delta. A check running after that
wrap cannot distinguish them from those values alone. In particular, a missed
complete wrap looks like no elapsed time; a wrap plus one looks like one tick
and can incorrectly qualify the `single` freshness indication.

| Counter width | Complete wrap at 12 Hz | Complete wrap at 1 kHz |
| --- | ---: | ---: |
| 8 bits | 21.333 seconds | 256 milliseconds |
| 10 bits | 85.333 seconds | 1.024 seconds |
| 32 bits | About 11.34 years | About 49.71 days |

This is an information-loss argument, not evidence that a particular production
stall reaches any listed duration. Keeping 32 bits preserves existing tolerance;
it does not make an unbounded stalled consumer safe. The 1 kHz configurations
also matter: changing only the production profile would not preserve the
supported parameterized interface and existing verification behavior.

`build/async-lf-width-gate/receipt-r1.json` pins the six implementation files,
the audit script, twelve wrap counterexamples and exact rational wrap periods.
It checks the independent count/Gray owners and final-publication feedback in
both variants. It does not claim a simulated reachable stall or a maximum-gap
proof. Since no hardware changes, area, leakage and clock activity are unchanged
by this decision; no new measurement is attributed to A3.

Fresh independent review is bound by
`build/async-lf-width-gate/independent-review-r1.json`. It independently checks
11,520 modular-counter cases and the actual observation/publication ownership;
this is arithmetic/source evidence, not proof of a reachable production stall.

Reopen narrowing with a compositional bound across all supported configurations
and reset/stall paths. A final-publication bound is one sufficient route;
bounded LF observation/scaler progress with proved retained accumulation and
wake ownership is another. Alternatively specify an overflow owner that
preserves elapsed time and freshness independently of a stalled consumer.
Measure any added owner's area and standby cost before treating a narrower
bus as a saving.
