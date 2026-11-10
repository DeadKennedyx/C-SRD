#include <stdint.h>
uint32_t kernel(uint32_t x) {
    uint32_t rotated = (x << 7u) | (x >> 25u);
    return 5u * rotated + 17u;
}
