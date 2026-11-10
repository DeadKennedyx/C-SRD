#include <stdint.h>

/* Reserved observer check; public contract is unsigned absolute difference. */
uint32_t kernel(uint32_t x, uint32_t y)
{
    return x < y ? y - x : x - y;
}
