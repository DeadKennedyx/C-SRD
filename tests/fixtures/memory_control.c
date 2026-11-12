#include <stdint.h>

uint32_t control_branch(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t before = p[0] + x;
    if (x & 1u) p[1] = 3u * before + 11u;
    else p[1] = 5u * before + 7u;
    q[0] = p[1] + 1u;
    return p[0] + p[1];
}

uint32_t control_early(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t before = p[0] + x;
    if (x == 0u) return before;
    p[1] = 3u * before + 11u;
    if (q[0] & 1u) return p[1];
    q[0] = 5u * before + 7u;
    return p[0] + q[0];
}

uint32_t control_loop(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t n = x & 3u;
    uint32_t sum = x;
    for (uint32_t i = 0u; i < n; ++i) {
        sum = sum + p[i];
        p[i] = 3u * sum + 11u;
    }
    q[0] = sum;
    return q[0] + p[0];
}

uint32_t control_nested(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t n = x & 3u;
    uint32_t sum = x;
    for (uint32_t i = 0u; i < n; ++i) {
        if (p[i] & 1u) {
            sum = sum + p[i];
            p[i] = 3u * sum + 7u;
        } else {
            sum = sum - p[i];
            p[i] = 5u * sum + 11u;
        }
    }
    q[0] = sum;
    return sum + p[0];
}

uint32_t control_loop_exit(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t n = (x >> 1u) & 3u;
    uint32_t sum = p[0] + x;
    for (uint32_t i = 0u; i < n; ++i) {
        sum = sum + p[i];
        if (sum & 1u) return sum + 7u;
        p[i] = 3u * sum + 11u;
    }
    q[0] = sum;
    return sum + p[0];
}

uint32_t control_loop_local(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t n = x & 3u;
    uint32_t sum = p[0] + x;
    for (uint32_t i = 0u; i < n; ++i) {
        uint32_t v = 3u * sum + 11u;
        p[i] = v;
        sum = v + q[0];
    }
    q[1] = sum;
    return sum + q[0];
}
