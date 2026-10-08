/* SPDX-License-Identifier: Apache-2.0 */
.option norvc
.option norelax
.section .init,"ax",@progbits
.global _start
.type _start,@function
_start:
    /* Set SP in one architectural write, with stronger-than-ILP32E alignment. */
    la t0, __stack_top
    mv sp, t0
    la t0, __data_load
    la t1, __data_start
    la t2, __data_end
1:  bgeu t1, t2, 2f
    lw a0, 0(t0)
    sw a0, 0(t1)
    addi t0, t0, 4
    addi t1, t1, 4
    j 1b
2:  la t0, __bss_start
    la t1, __bss_end
3:  bgeu t0, t1, 4f
    sw zero, 0(t0)
    addi t0, t0, 4
    j 3b
4:  la t0, __guard_start
    la t1, __guard_end
    li t2, 0xfeedc0de
5:  bgeu t0, t1, 6f
    sw t2, 0(t0)
    addi t0, t0, 4
    j 5b
6:  la t1, __stack_top
    li t2, 0xa5a5a5a5
7:  bgeu t0, t1, 8f
    sw t2, 0(t0)
    addi t0, t0, 4
    j 7b
8:  call main
    /* Returning is a terminal test/application fault, never a jump into RAM. */
    ebreak
9:  j 9b
.size _start, .-_start
