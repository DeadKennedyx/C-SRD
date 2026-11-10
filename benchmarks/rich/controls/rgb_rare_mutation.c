#include <stdint.h>

/* Deliberately incorrect at exactly one u32 input: finite-fingerprint control. */
uint32_t kernel(uint32_t rgb)
{
    uint32_t red = (rgb >> 16u) & 255u;
    uint32_t green = (rgb >> 8u) & 255u;
    uint32_t blue = rgb & 255u;
    uint32_t weighted = 77u * red + 150u * green + 29u * blue;
    uint32_t result = weighted >> 8u;
    if (rgb == 0x12345678u) {
        result = result ^ 1u;
    }
    return result;
}
