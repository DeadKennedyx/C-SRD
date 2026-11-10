#include <stdint.h>

/* Independent bit-serial interleaving, with no variable shift counts. */
uint32_t kernel(uint32_t x, uint32_t y)
{
    uint32_t a = x & 65535u;
    uint32_t b = y & 65535u;
    uint32_t result = 0u;
    for (uint32_t i = 0u; i < 16u; ++i) {
        result = (result >> 2u) | ((a & 1u) << 30u) | ((b & 1u) << 31u);
        a = a >> 1u;
        b = b >> 1u;
    }
    return result;
}
