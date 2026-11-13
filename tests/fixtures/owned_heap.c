#include <stdint.h>
#include <stdlib.h>

uint32_t heap_pair(uint32_t *out, uint32_t x)
{
    uint32_t *p = malloc(2u * sizeof(uint32_t));
    if (!p) return x + 1u;
    uint32_t *view = p + 1u;
    p[0] = x + 3u;
    *view = 3u * p[0] + 5u;
    *out = *view;
    uint32_t result = p[0] + *view;
    free(p);
    return result;
}

uint32_t heap_zero(uint32_t *out, uint32_t x)
{
    uint32_t n = (x & 3u) + 1u;
    uint32_t *p = calloc(n, sizeof(uint32_t));
    if (p == 0) return x + 7u;
    for (uint32_t i = 0u; i < n; ++i) {
        p[i] = p[i] + 3u * x + i;
    }
    uint32_t result = p[0] + n;
    *out = result + 11u;
    free(p);
    return result;
}

uint32_t heap_resize(uint32_t *out, uint32_t x)
{
    uint32_t *p = malloc(2u * sizeof(uint32_t));
    if (!p) return x + 13u;
    p[0] = x + 3u;
    p[1] = 5u * x + 7u;
    uint32_t *q = realloc(p, 4u * sizeof(uint32_t));
    if (!q) {
        uint32_t fallback = p[0] + p[1];
        *out = fallback;
        free(p);
        return fallback + 17u;
    }
    q[2] = q[0] + q[1];
    q[3] = 3u * q[2] + 19u;
    uint32_t result = q[3];
    *out = q[2];
    free(q);
    return result;
}

uint32_t heap_shrink(uint32_t *out, uint32_t x)
{
    uint32_t *p = calloc(4u, sizeof(uint32_t));
    if (!p) return x + 23u;
    p[0] = x + 29u;
    p[1] = 3u * p[0];
    uint32_t *q = realloc(p, 2u * sizeof(uint32_t));
    if (!q) {
        uint32_t fallback = p[0] + p[1];
        free(p);
        return fallback;
    }
    p = q;
    uint32_t result = p[0] + p[1];
    *out = result;
    free(p);
    p = 0;
    free(p);
    return result;
}

uint32_t heap_nullable(uint32_t *out, uint32_t x)
{
    uint32_t *p = 0;
    p = realloc(p, sizeof(uint32_t));
    if (!p) return x + 31u;
    *p = 7u * x + 37u;
    uint32_t result = *p;
    *out = result;
    free(p);
    return result;
}

uint32_t heap_repeated(uint32_t *out, uint32_t x)
{
    uint32_t sum = x;
    for (uint32_t i = 0u; i < 3u; ++i) {
        uint32_t *p = malloc(sizeof(uint32_t));
        if (!p) return sum;
        *p = sum + 3u * i + 41u;
        sum = *p;
        free(p);
    }
    *out = sum;
    return sum;
}
