/* SPDX-License-Identifier: Apache-2.0 */
#ifndef RISCAY_H
#define RISCAY_H
#include <stdint.h>
#define MMIO(offset) (*(volatile uint32_t *)(0x30000000u + (offset)))
#define NOINLINE __attribute__((noinline))
static inline void app_word(uint32_t index, uint32_t value) {
    MMIO(48) = index;
    MMIO(52) = value;
}
/* Uses existing deadline/lease/WAIT registers; no ISA WFI/interrupt dependency. */
static inline uint32_t wait_events(uint32_t delay_ms) {
    MMIO(56) = 6u; /* Deadline or GPIO. Lease and host wake remain unconditional. */
    MMIO(8) = MMIO(4) + delay_ms;
    MMIO(60) = 2000u;
    MMIO(32) = 0x57444f47u;
    return MMIO(16);
}
/* Acknowledge the returned bits before handling them. Later events remain pending.
 * Events are coalesced flags, not per-edge counters; hardware sets win clear races.
 */
static inline void acknowledge_events(uint32_t consumed) { MMIO(12) = consumed; }
uint32_t check_guard(void);
uint32_t stack_watermark(void);
#endif
