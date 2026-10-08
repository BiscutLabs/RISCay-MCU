/* SPDX-License-Identifier: Apache-2.0 */
/* Test-only workload: nested frames, initialized data, BSS, byte stores,
 * constants and arbitrary unsigned software division without M or libc.
 */
#include "riscay.h"
volatile uint32_t seeds[4] = { 17u, 0x1234u, 0x80000001u, 0xdeadbeefu };
volatile uint32_t results[4];
volatile uint8_t scratch[16];
static const uint32_t salts[4] = { 3u, 7u, 11u, 13u };
static NOINLINE uint32_t divide(uint32_t value, uint32_t divisor) {
    uint32_t quotient = 0, remainder = 0;
    for (uint32_t bit = 32; bit != 0; --bit) {
        uint32_t carry = remainder >> 31;
        remainder = (remainder << 1) | (value >> 31);
        value <<= 1; quotient <<= 1;
        if (carry || remainder >= divisor) { remainder -= divisor; quotient |= 1; }
    }
    return quotient;
}
static NOINLINE uint32_t transform(uint32_t seed, uint32_t salt) {
    volatile uint32_t lanes[8];
    for (uint32_t i = 0; i < 8; ++i) lanes[i] = (seed ^ (salt + i)) + (i << 8);
    uint32_t mixed = 0;
    for (uint32_t i = 0; i < 8; ++i) mixed ^= lanes[i];
    return divide(seed, salt) ^ mixed;
}
static NOINLINE uint32_t batch(void) {
    volatile uint32_t keep[4];
    uint32_t checksum = 0;
    for (uint32_t i = 0; i < 4; ++i) {
        keep[i] = seeds[i];
        results[i] = transform(keep[i], salts[i]);
        checksum ^= results[i];
        scratch[i] = (uint8_t)results[i];
    }
    return checksum;
}
int main(void) {
    uint32_t initialized = seeds[0] == 17u && seeds[3] == 0xdeadbeefu;
    for (uint32_t i = 0; i < 4; ++i) initialized &= results[i] == 0;
    for (uint32_t i = 0; i < 16; ++i) initialized &= scratch[i] == 0;
    app_word(0, initialized ? 0x43525431u : 0xbad00001u);
    uint32_t checksum = batch();
    app_word(1, checksum);
    for (uint32_t i = 0; i < 4; ++i) app_word(2u + i, results[i]);
    app_word(6, check_guard());
    app_word(7, stack_watermark());
    /* Sleep with initialized state retained, then verify it was not corrupted. */
    acknowledge_events(wait_events(500u));
    for (uint32_t i = 0; i < 4; ++i)
        if (scratch[i] != (uint8_t)results[i]) { app_word(0,0xbad00002u); return 1; }
    return 0;
}
