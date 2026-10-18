OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0;
  .text : { KEEP(*(.text.start)) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) }
  .forbidden : { *(.data .data.*) *(.bss .bss.*) *(COMMON) }
  ASSERT(SIZEOF(.forbidden) == 0, "Boot ROM cannot contain initialized or static writable storage")
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
