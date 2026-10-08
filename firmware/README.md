# RV32E firmware and memory sizing

These are compiler-built sizing and execution fixtures for the existing SoC.
They do not replace Groundlark's permanent hardware supervisor or add optional
peripherals. `event_loop` exercises deadline/leased WAIT, GPIO reads and application
registers. `runtime_stress` exercises nested stack frames, initialized data, BSS,
constants, byte stores and unsigned software division. Both deliberately return
after finite workloads, causing the startup EBREAK; they are not deployment images.
`wait_events()` arms timing and explicitly kicks the watchdog without clearing
pending events. Call `acknowledge_events(returned_bits)` before processing them;
new events during processing remain for the next wait. Pending bits coalesce,
so multiple edges on a still-pending bit are not an event queue. Lease writes
alone no longer kick the watchdog.

## Reproduce

```text
python tools/build_firmware.py --bootstrap
python tools/sbt.py "verification/testOnly riscay.FirmwareSpec"
python -m unittest discover -s tools -p test_firmware.py -v
```

The bootstrap downloads checksum-pinned Ubuntu 24.04 amd64 GCC 13.2.0 and binutils
2.42 packages into `.tools/riscv-gcc/`, and extracts them without installing system
packages. Native Linux needs their runtime dependencies and `dpkg-deb`. On Windows,
the driver delegates to the Ubuntu WSL distribution. Subsequent builds omit
`--bootstrap`. Missing tools fail; tests never substitute preloaded/handwritten
images or skip compilation. See [toolchain-lock.json](toolchain-lock.json).
The Python event-helper control also needs native `gcc` on Linux/Ubuntu WSL;
it executes the actual header against mapped MMIO storage to inspect writes.

The build uses `-march=rv32e -mabi=ilp32e -Os`, no compressed instructions, M,
libc, dynamic allocation or relaxation. It emits ELF, binary, words, disassembly,
map, per-function stack/callgraph information and a JSON report under
`build/firmware/<application>/`. Compiler and source hashes are recorded. The
entire loaded image includes text, constants, alignment and the initial `.data`
copy. `.bss`, stack and guard occupy working RAM, not the uploaded image.

## Runtime and budgets

[memory.json](memory.json) records the Groundlark sizing budget: 2048 program
bytes, 256 working-RAM bytes, a 128-byte stack reserve and a 16-byte guard.
`FirmwareSpec` checks these against the actual SoC configuration. The linker
rejects images or static data/guard/stack reservations that do not fit. The build
also rejects unsupported instruction encodings/registers, unresolved or dynamic
stack frames, recursive call graphs and a static bound above the reserved stack.
The reserve is headroom, not another allocation beyond the 256-byte RAM.

`startup.S` runs from validated program RAM, sets SP, copies `.data` from its
program-RAM load address, clears `.bss`, initializes the guard and fills remaining
RAM with a stack watermark. It uses no stack itself. Initial SP is 16-byte aligned;
the compiler follows ILP32E's 4-byte stack alignment for subsequent frames.
`runtime.c` checks the guard and scans the watermark. These aid the sizing tests;
the guard is not hardware memory protection. A production application can remove
watermark instrumentation, but must retain correct data/BSS/stack initialization.

The static bound sums frame sizes along the largest reachable direct call chain.
Sibling-call optimization can make that bound conservative. Unknown/indirect calls
are rejected, not assigned zero stack. Runtime tests independently watch each
architectural SP write and compare peak depth with the compiler bound and the
memory watermark; any observed SP below the guard or above RAM fails. All images pass
through the real I2C loader, CRC validation and START_AND_LOCK. Repeated STARTs
commit upload frames; this avoids a wake preamble for every word while preserving
the wire protocol. No MCU RAM is initialized by the simulator.

Tests use a generic profile exposing eight existing application words, with the
production memory capacities. They check initialization and arithmetic against
independent host expectations, retained sleep, image lock and the final EBREAK.
Changing compiler, flags, startup, libraries or application requires remeasuring;
these workloads are not a proof that arbitrary future firmware fits.

References: [GCC RISC-V options](https://gcc.gnu.org/onlinedocs/gcc/RISC-V-Options.html)
and [GCC callgraph/stack output](https://gcc.gnu.org/onlinedocs/gcc/Developer-Options.html).
