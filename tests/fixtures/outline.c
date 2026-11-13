#include <stdint.h>

uint32_t outline_calculate(uint32_t x, uint32_t y)
{
    uint32_t sum = x + y;
    return 3u * sum + 11u;
}

long long outline_signed(int x, short y)
{
    long long value = (long long)x * y + 17;
    return (value - y) / ((long long)(unsigned short)y + 1);
}

unsigned char outline_byte(unsigned char x, unsigned char y)
{
    return (unsigned char)((x + y) * 3);
}

unsigned outline_select(unsigned x, unsigned y)
{
    return x ? y / x + 1u : y * 3u;
}

int outline_logical(int x, int y)
{
    return x && y / x > 1;
}

unsigned outline_buffer(unsigned char *out, const unsigned char *in,
                        unsigned count, unsigned seed, void (*observe)(unsigned))
{
    for (unsigned i = 0; i < count; ++i) {
        unsigned value = seed + in[i];
        unsigned mixed = (value ^ (value >> 7)) + i;
        out[i] = (unsigned char)mixed;
        observe(mixed);
        seed = value * 3u + i;
    }
    return seed * 5u + count;
}

unsigned outline_shadow(unsigned x, unsigned y)
{
    unsigned value = x + 3u * y;
    {
        unsigned x = value + 5u;
        value = x * 3u - y;
    }
    return value - x + y;
}
