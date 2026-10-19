/* SPDX-License-Identifier: Apache-2.0 */
.section .text.start,"ax",@progbits
.globl _start
_start:
    lui a0,0x30000
    lw sp,92(a0)
    call boot_main
    jalr zero,a0,0
1:  ebreak
    j 1b
.section .boot_capacity,"a",@progbits
.balign 4
.globl riscay_program_capacity
riscay_program_capacity:
    .word 0xc0dec0de /* Generic build capacity, replaced at elaboration. */
