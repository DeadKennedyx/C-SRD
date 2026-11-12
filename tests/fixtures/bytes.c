#include <stdint.h>

uint32_t bytes_mix(unsigned char *p, uint32_t *q, uint32_t x)
{
    (void)q;
    uint32_t i = x & 7u;
    uint32_t sum = p[i] + x;
    uint32_t scaled = 3u * sum + 11u;
    p[i + 1u] = scaled;
    return scaled + p[i + 1u];
}

uint32_t bytes_alias(unsigned char *p, uint32_t *q, uint32_t x)
{
    uint32_t before = q[0];
    p[x & 3u] = x;
    return before + q[0] + p[0];
}

uint32_t bytes_word(unsigned char *p, uint32_t *q, uint32_t x)
{
    q[0] = 7u * x + 19u;
    p[x & 3u] = x >> 8;
    return q[0];
}

uint32_t bytes_view(unsigned char *p, uint32_t *q, uint32_t x)
{
    (void)q;
    unsigned char *cursor = p + (x & 3u);
    x = x + 1u;
    cursor[1] = 5u * x + 13u;
    return p[0] + cursor[1];
}

uint32_t bytes_promotions(unsigned char *p, uint32_t *q, uint32_t x)
{
    (void)q;
    uint32_t sum = p[0] + 3 * p[1] + (p[2] << 8);
    return sum + x;
}

uint32_t bytes_signed(signed char *p, uint32_t *q, uint32_t x)
{
    (void)q;
    uint32_t before = (uint32_t)p[0];
    p[1] = x;
    return before + (uint32_t)p[1];
}

uint32_t bytes_string(const char *p, uint32_t *q, uint32_t x)
{
    (void)q;
    uint32_t a = (uint32_t)p[x & 3u];
    uint32_t b = (uint32_t)p[4];
    return 3u * a + b + 11u;
}
