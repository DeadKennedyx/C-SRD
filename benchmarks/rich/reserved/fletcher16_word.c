#include <stdint.h>

/* Two mod-255 sums packed into the low 16 bits; update four LE bytes. */
uint32_t kernel(uint32_t state, uint32_t word)
{
    uint32_t first = state & 255u;
    uint32_t second = (state >> 8u) & 255u;
    uint32_t bytes = word;
    first = first == 255u ? 0u : first;
    second = second == 255u ? 0u : second;
    for (uint32_t i = 0u; i < 4u; ++i) {
        first = first + (bytes & 255u);
        first = first >= 255u ? first - 255u : first;
        second = second + first;
        second = second >= 255u ? second - 255u : second;
        bytes = bytes >> 8u;
    }
    return (second << 8u) | first;
}
