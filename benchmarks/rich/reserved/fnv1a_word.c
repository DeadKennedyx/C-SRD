#include <stdint.h>

/* FNV-1a update of four LE bytes, using the caller's 32-bit state. */
uint32_t kernel(uint32_t state, uint32_t word)
{
    uint32_t hash = state;
    uint32_t bytes = word;
    for (uint32_t i = 0u; i < 4u; ++i) {
        hash = (hash ^ (bytes & 255u)) * 16777619u;
        bytes = bytes >> 8u;
    }
    return hash;
}
