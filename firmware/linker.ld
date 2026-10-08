/* SPDX-License-Identifier: Apache-2.0 */
OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
  PROGRAM (rx) : ORIGIN = 0x10000000, LENGTH = PROGRAM_BYTES
  DATA (rw) : ORIGIN = 0x20000000, LENGTH = RAM_BYTES
}
SECTIONS {
  .text : { KEEP(*(.init)) *(.text .text.*) } > PROGRAM
  .rodata : { *(.rodata .rodata.* .srodata .srodata.*) . = ALIGN(4); } > PROGRAM
  .data : {
    __data_start = .; *(.data .data.* .sdata .sdata.*) . = ALIGN(4); __data_end = .;
  } > DATA AT> PROGRAM
  __data_load = LOADADDR(.data);
  __image_end = LOADADDR(.data) + SIZEOF(.data);
  .bss (NOLOAD) : {
    __bss_start = .; *(.bss .bss.* .sbss .sbss.* COMMON) . = ALIGN(4); __bss_end = .;
  } > DATA
  __static_end = .;
  .guard (NOLOAD) : { __guard_start = .; . += GUARD_BYTES; __guard_end = .; } > DATA
  __stack_top = ORIGIN(DATA) + LENGTH(DATA);
  __stack_limit = __stack_top - STACK_BYTES;
  ASSERT(__image_end <= ORIGIN(PROGRAM) + LENGTH(PROGRAM), "PROGRAM_BUDGET_EXCEEDED")
  ASSERT(__guard_end <= __stack_limit, "RAM_STACK_BUDGET_EXCEEDED")
  ASSERT((__stack_top & 15) == 0, "STACK_TOP_ALIGNMENT")
  /DISCARD/ : { *(.comment .note .eh_frame .eh_frame.*) }
}
