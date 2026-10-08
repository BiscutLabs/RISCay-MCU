/* SPDX-License-Identifier: Apache-2.0 */
#include "riscay.h"
extern uint32_t __guard_start[], __guard_end[], __stack_top[];
NOINLINE uint32_t check_guard(void) {
    for (volatile uint32_t *p = __guard_start; p < __guard_end; ++p)
        if (*p != 0xfeedc0deu) return 0;
    return 1;
}
NOINLINE uint32_t stack_watermark(void) {
    volatile uint32_t *p = __guard_end;
    while (p < __stack_top && *p == 0xa5a5a5a5u) ++p;
    return (uint32_t)((uintptr_t)__stack_top - (uintptr_t)p);
}
