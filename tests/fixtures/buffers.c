#include <stdint.h>

uint32_t buffer_mix(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t sum = p[0] + x;
    uint32_t scaled = 3u * sum + 11u;
    p[1] = scaled;
    uint32_t after = q[0] - p[1];
    q[1] = after + x;
    return p[0] + q[1];
}

uint32_t buffer_store(uint32_t *p, uint32_t *q, uint32_t x)
{
    *p = x + 1u;
    *q = *p * 7u - 3u;
    return 19u;
}

uint32_t buffer_snapshot(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t before = p[0];
    q[0] = x;
    x = before * 3u;
    return x + p[0];
}

uint32_t buffer_boundary(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t last = p[15] + x;
    q[15] = 4294967295u * last - 1u;
    return q[15] + p[15];
}

uint32_t buffer_unused(uint32_t *p, uint32_t *q, uint32_t x)
{
    (void)p;
    (void)q;
    return x * 3u + 11u;
}

uint32_t buffer_const(const uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t before = *p + x;
    q[0] = before * 17u;
    return before + p[0];
}
