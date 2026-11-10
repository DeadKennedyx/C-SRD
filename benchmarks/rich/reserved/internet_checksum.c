#include <stdint.h>

/* Internet checksum of two packed 32-bit words, in network byte order. */
uint32_t kernel(uint32_t first, uint32_t second)
{
    uint32_t sum = (first >> 16u) + (first & 65535u);
    sum = sum + (second >> 16u) + (second & 65535u);
    sum = (sum & 65535u) + (sum >> 16u);
    sum = (sum & 65535u) + (sum >> 16u);
    return (~sum) & 65535u;
}
