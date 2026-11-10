#include <stdint.h>

uint32_t buffer_update(uint32_t *p, const uint32_t *q, uint32_t x)
{
    uint32_t sum = q[0] + x;
    uint32_t result = 3u * sum + 11u;
    p[1] = result;
    return p[0] + result;
}
