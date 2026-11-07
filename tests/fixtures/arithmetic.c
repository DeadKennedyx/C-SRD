#include <stdint.h>

uint32_t calculate(uint32_t x, uint32_t y)
{
    uint32_t sum = x + y;
    return 3u * sum + 11u;
}

uint32_t pipeline(uint32_t x, uint32_t y)
{
    uint32_t a = x - y;
    uint32_t b = 4294967295u * (a + 1u);
    a = (b - x) + (y * 17u);
    x = a + x;
    return (x - a) + b;
}

uint32_t identities(uint32_t x, uint32_t y)
{
    uint32_t a = 0u * (x + y);
    uint32_t b = 1u * (x - x);
    return a + b + (y - y);
}

uint32_t constants(uint32_t x, uint32_t y)
{
    uint32_t a = 4294967295u;
    uint32_t b = 0;
    return (3 * (x + y)) + (a - b) + (3u * 5u);
}

uint32_t collisions(uint32_t csrd_tmp, uint32_t encoded)
{
    uint32_t csrd_a = csrd_tmp + encoded;
    uint32_t csrd_inverse = csrd_a - csrd_tmp;
    encoded = csrd_inverse * 2u;
    return encoded;
}

/* Unchanged because of the macro; preceding replacements must preserve its line. */
uint32_t line_sensitive(uint32_t x, uint32_t y) { return x + y + __LINE__; }

/* An unrelated negative control, deliberately outside the supported subset. */
uint32_t unrelated(uint32_t x, uint32_t y) { return x ^ y; }
