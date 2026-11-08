#include <stdint.h>

uint32_t bit_mix(uint32_t x, uint32_t y)
{
    uint32_t a = (x ^ y) & 4294967295u;
    uint32_t b = (~a) | (x >> 7u);
    return (b << 3u) ^ (y >> 31u);
}

uint32_t mixed_regions(uint32_t x, uint32_t y)
{
    uint32_t a = x + y;
    uint32_t b = a ^ y;
    uint32_t c = b & x;
    uint32_t d = c + 1u;
    return d + a;
}

uint32_t choose(uint32_t x, uint32_t y)
{
    uint32_t a = x + 3u;
    if (x < y) {
        a = a ^ y;
    } else {
        a = a - y;
    }
    if (a == 0u) a = 7u;
    return (a > y) ? (a + x) : (a ^ x);
}

uint32_t lookup(uint32_t x, uint32_t y)
{
    const uint32_t table[4] = {0u, 4294967295u, 17u, 23u};
    uint32_t index = (x ^ y) & 3u;
    return table[index] + y;
}

uint32_t bounded_sum(uint32_t x, uint32_t y)
{
    uint32_t sum = y;
    for (uint32_t i = 0u; i < 8u; ++i) {
        sum = sum + x + i;
        x = x ^ 17u;
    }
    return sum;
}

uint32_t table_loop(uint32_t x, uint32_t y)
{
    uint32_t table[4] = {1u, 3u, 7u};
    uint32_t result = x;
    for (uint32_t index = 0u; index < 4u; index++) {
        result = result + table[index] + y;
    }
    return result;
}

uint32_t comparisons(uint32_t x, uint32_t y)
{
    uint32_t a = x <= y;
    uint32_t b = x >= y;
    uint32_t c = x != y;
    return a + 3u * b + 7u * c;
}

uint32_t zero_iterations(uint32_t x, uint32_t y)
{
    for (uint32_t index = 0u; index < 0u; ++index) {
        x = x + y;
    }
    return x + y;
}
