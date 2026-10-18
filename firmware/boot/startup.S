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
