#include <stdint.h>

/* Same CRC update, using two four-bit table steps rather than eight bit steps. */
uint32_t kernel(uint32_t state, uint32_t byte)
{
    const uint32_t table[16] = {
        0x00000000u, 0x1db71064u, 0x3b6e20c8u, 0x26d930acu,
        0x76dc4190u, 0x6b6b51f4u, 0x4db26158u, 0x5005713cu,
        0xedb88320u, 0xf00f9344u, 0xd6d6a3e8u, 0xcb61b38cu,
        0x9b64c2b0u, 0x86d3d2d4u, 0xa00ae278u, 0xbdbdf21cu
    };
    uint32_t crc = (state ^ 0xffffffffu) ^ (byte & 255u);
    crc = (crc >> 4u) ^ table[crc & 15u];
    crc = (crc >> 4u) ^ table[crc & 15u];
    return crc ^ 0xffffffffu;
}
