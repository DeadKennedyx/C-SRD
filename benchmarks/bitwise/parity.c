#include <stdint.h>
uint32_t kernel(uint32_t x) {
    x = x ^ (x >> 16u);
    x = x ^ (x >> 8u);
    x = x ^ (x >> 4u);
    x = x ^ (x >> 2u);
    x = x ^ (x >> 1u);
    return x & 1u;
}
