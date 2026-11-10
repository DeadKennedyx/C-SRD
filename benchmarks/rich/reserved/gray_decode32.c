#include <stdint.h>

/* Convert a 32-bit reflected Gray code to its unsigned binary value. */
uint32_t kernel(uint32_t gray)
{
    uint32_t result = gray;
    result = result ^ (result >> 16u);
    result = result ^ (result >> 8u);
    result = result ^ (result >> 4u);
    result = result ^ (result >> 2u);
    result = result ^ (result >> 1u);
    return result;
}
