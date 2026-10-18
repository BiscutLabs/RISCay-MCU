# SRAM prepare stage fusion

A10's first adopted fusion removes the pure-copy prepare stage in both independent
SRAM sequencers. The preceding native Join already stores the word request and
its execution credit. Its output projects the request unchanged and appends a
constant zero read-assembly field directly into the first lane's fork.

Each variant has a program sequencer and a data-RAM sequencer. Removing their
two 101-bit prepare payload stores removes 202 native payload bits per variant,
plus the two stage controllers, allowances and guards. Count the final mapped
change in the area ledger; do not add a separately estimated allowance saving
for the same removed stages.

The first fork acknowledges the Join only after both its issue stage and its
retained left operand for the byte-response rendezvous accept. Four-phase ACK
return and Click phase history connect directly through the projection. The
execution credit still returns only after the final word response is accepted.
Early presentation of another word therefore cannot touch a macro prematurely.
There is no new storage, clock, synchronizer or protocol conversion.

The four byte lanes, explicit clocked macro boundaries, byte masks, loader
accounting and service-domain drainage stay in place. This change does not
implement the separately planned self-timed macro clock. POR cancels native
ownership; application reset preserves accepted memory work and SRAM contents
under the existing reset coordinator.

Verification uses the existing independent byte/macro scoreboards, all masks
and bank boundaries, immediate next requests, independent byte and word
backpressure, and POR at every byte and held final response. Integrated SRAM
tests also cover loader accounting, watchdog offsets and clock stops. Preserve
those expectations. The physical source is now the Join operand storage;
source-to-first-lane setup, source reuse/hold, fork return and extracted wire
timing must follow that actual path. A passing digital campaign is not physical
qualification. Adoption status and measured evidence belong in the migration
checklist and area ledger.

The local composition tool binds the repaired graph's Join operand stores,
first fork, issue stage and retained response operand. Reproduce one target
with a fresh output directory and the mapping's recorded tool configuration:

```text
python tools/sram_fusion_timing.py build/area-adoption/map-bd-r3 build/fusion-bd-program-issue-recheck --variant bd --owner program --branch issue --campaign
```

Run both `--branch issue` and `--branch store` for `--owner program` and
`--owner ram` in each variant. Each target includes both operand-arrival orders
and all five corners/two slews. Click's local hold argument also requires the
matching first-fork receiver ACK/rearm evidence from the guard campaign.
The eight-target result is distinct from complete return/reset and extracted
wire qualification.
