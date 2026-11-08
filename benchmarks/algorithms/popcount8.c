#include <stdint.h>
/* Population count of the low byte; higher input bits are irrelevant. */
uint32_t popcount8(uint32_t x) {
    uint32_t bits = x & 255u;
    uint32_t count = 0u;
    for (uint32_t i = 0u; i < 8u; ++i) {
        count = count + (bits & 1u);
        bits = bits >> 1u;
    }
    return count;
}
