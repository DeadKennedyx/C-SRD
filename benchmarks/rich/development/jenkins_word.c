#include <stdint.h>

/* Jenkins one-at-a-time, four little-endian bytes, supplied initial state. */
uint32_t kernel(uint32_t state, uint32_t word)
{
    uint32_t hash = state;
    uint32_t bytes = word;
    for (uint32_t i = 0u; i < 4u; ++i) {
        hash = hash + (bytes & 255u);
        hash = hash + (hash << 10u);
        hash = hash ^ (hash >> 6u);
        bytes = bytes >> 8u;
    }
    hash = hash + (hash << 3u);
    hash = hash ^ (hash >> 11u);
    hash = hash + (hash << 15u);
    return hash;
}
