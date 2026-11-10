#include <stdint.h>

/* Reflected IEEE CRC-32 update of one low byte; zlib-style complemented state. */
uint32_t kernel(uint32_t state, uint32_t byte)
{
    uint32_t crc = (state ^ 0xffffffffu) ^ (byte & 255u);
    uint32_t mask = 0u;
    for (uint32_t i = 0u; i < 8u; ++i) {
        mask = 0u - (crc & 1u);
        crc = (crc >> 1u) ^ (0xedb88320u & mask);
    }
    return crc ^ 0xffffffffu;
}
