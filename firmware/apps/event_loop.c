/* SPDX-License-Identifier: Apache-2.0 */
/* A finite sizing workload for the generic application-register fixture.
 * Groundlark's permanent power supervisor does not depend on this program.
 */
#include "riscay.h"
volatile uint32_t period_ms = 500u; /* Must be copied from validated program RAM. */
volatile uint32_t completed;
volatile uint32_t observed_events;
volatile uint32_t last_gpio;
int main(void) {
    uint32_t initialized = period_ms == 500u && completed == 0 && observed_events == 0 && last_gpio == 0;
    app_word(0, initialized ? 0x43525431u : 0xbad00001u);
    for (uint32_t i = 0; i < 4u; ++i) {
        observed_events |= wait_events(period_ms);
        last_gpio = MMIO(20);
        ++completed;
    }
    app_word(1, completed);
    app_word(2, observed_events);
    app_word(3, last_gpio);
    app_word(4, check_guard());
    app_word(5, stack_watermark());
    app_word(6, 0x600d600du);
    return 0;
}
