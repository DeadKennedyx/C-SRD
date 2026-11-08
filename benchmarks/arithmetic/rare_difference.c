#include <stdint.h>
/* Intentional negative control: agrees with linear except at one input pair. */
uint32_t kernel(uint32_t x, uint32_t y) {
    uint32_t r = 3u * (x + y) + 11u;
    if (x == 1129534020u) { if (y == 0u) { r = r + 1u; } }
    return r;
}
