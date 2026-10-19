OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0;
  .text : { KEEP(*(.text.start)) *(.text .text.*) }
  .rodata : { *(.rodata .rodata.*) }
  .boot_capacity ALIGN(4) : { KEEP(*(.boot_capacity)) }
  ASSERT(SIZEOF(.boot_capacity) == 4, "Boot ROM requires one final capacity word")
  .forbidden : { *(.data .data.*) *(.bss .bss.*) *(COMMON) }
  ASSERT(SIZEOF(.forbidden) == 0, "Boot ROM cannot contain initialized or static writable storage")
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
