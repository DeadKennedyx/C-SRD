#include <stdint.h>

/* Reserved observer check: five recurrence steps, with a data-dependent add. */
uint32_t kernel(uint32_t x, uint32_t y)
{
    uint32_t state = x;
    for (uint32_t i = 0u; i < 5u; i = i + 1u) {
        state = 1664525u * state + 1013904223u;
        if ((state & 1u) != 0u) {
            state = state + y;
        }
    }
    return state;
}
