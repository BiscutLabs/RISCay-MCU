# RV32E core execution contract

Implemented first RTL milestone, 2026-10-07. Both variants implement the same
sequential RV32E execution engine. They are CPU cores with memory service ports;
these ports are intended for internal SoC connections. The completed SoC must
boot from permanent on-chip ROM and execute a host-loaded application from on-chip
RAM, with no external memory chip. A board profile supplies bootstrap behavior;
Groundlark powers its Pi independently of the application when a qualified policy
is enabled. Both complete SoC wrappers now implement memory and loader integration;
see the [SoC contract](soc-contract.md).

## ISA and state

- RV32E base integer instructions, little endian, reset PC zero, IALIGN=32.
- x0 is hardwired zero; x1-x15 are 32-bit registers initialized to zero on reset.
- Compressed instructions, M, A, CSR/privileged execution and interrupts are not
  implemented. Unsupported encodings, including reserved upper registers, fault.
- FENCE completes as an ordering barrier: the core has one outstanding memory
  operation and waits for its response before proceeding. FENCE.I is unsupported.
- ECALL and EBREAK stop execution and produce diagnostic causes 11 and 3.
  These numeric causes do not imply an implemented privileged trap handler.
- Illegal instruction, instruction alignment/access, and load/store
  alignment/access errors produce a fault record and stop until reset.

Each variant circulates one architectural-state token. Fetch responses execute
ordinary ALU/control-flow instructions. A load/store fetch instead creates a
second memory transaction; its response completes that instruction. The shared
datapath is combinational; each design owns its async storage and sequencing.
Architectural state travels through multiple storage stages in this initial
implementation. No small-area or low-energy claim is made for that choice.

Four-phase reset automatically reinstalls the initial token. Click additionally
requires `start` to rise after coordinated reset settles, then remain high until
the next reset. `start` is currently an integration signal, not an allocated
package pin. The MCU reset controller will eventually own it.

## Memory request/response port

Both variants use the same payload with their own electrical handshake:

| Request field | Contract |
| --- | --- |
| `operation` | 0 fetch, 1 data read, 2 data write, 3 terminal halt notification |
| `address` | 32-bit byte address; actual addressed byte, not rounded down |
| `data` | Write data shifted into lanes of the word at `address & ~3`; zero for other operations |
| `mask` | Four byte-lane enables: fetch=15, data operation=selected lanes, halt=0 |

Responses contain 32-bit lane-aligned `data` and `error`. For a subword load,
return the addressed aligned word; the CPU extracts and sign/zero extends the
selected bytes. A store response acknowledges its commit; its data is ignored.

Exactly one ordered response is required per fetch/read/write. Request acceptance
is distinct from instruction retirement. A backend must report write errors
without committing the rejected write. A halt request may be acknowledged but
must receive no response: the token stops while awaiting that response, leaving
the core quiescent until reset.

Reset clears protocol and architectural state together. The attached memory
service must abort uncommitted work and discard stale replies in the same reset
epoch. Reset cannot undo already committed writes. Resetting only one side of a
live bus is unsupported.

## Retirement observation

`traceEvent` is an observation of the execute-stage output request. On each high
request phase for four-phase, or each phase change for Click, `trace.valid`
distinguishes a completed instruction/fault from an intermediate memory step.
Other fields record PC, instruction, register-write destination/value, fault and
cause. A fault record has no register write. The observer must not acknowledge or
consume this signal; it is not an additional channel consumer.

The tests compare these records and every committed bus transaction with an
independent software interpreter. They do not compare internal cycles or assert
a throughput advantage from the library's simulation delay presets.

## SoC integration

Standalone core tests use independent memory models. Both SoC wrappers connect
the cores to real on-chip ROM/RAM, MMIO, ADC, events/timers, watchdog and output
control. Permanent Groundlark supervision is fixed hardware, independent of the
uploaded application. Memory is outside the circulating CPU token. Physical
cells, pads, analog integration and timing remain a later stage.
