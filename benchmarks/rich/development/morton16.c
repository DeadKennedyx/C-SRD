#include <stdint.h>

/* Interleave the low 16 bits of x and y; x occupies the even output bits. */
uint32_t kernel(uint32_t x, uint32_t y)
{
    uint32_t a = x & 65535u;
    uint32_t b = y & 65535u;
    a = (a | (a << 8u)) & 0x00ff00ffu;
    b = (b | (b << 8u)) & 0x00ff00ffu;
    a = (a | (a << 4u)) & 0x0f0f0f0fu;
    b = (b | (b << 4u)) & 0x0f0f0f0fu;
    a = (a | (a << 2u)) & 0x33333333u;
    b = (b | (b << 2u)) & 0x33333333u;
    a = (a | (a << 1u)) & 0x55555555u;
    b = (b | (b << 1u)) & 0x55555555u;
    return a | (b << 1u);
}
