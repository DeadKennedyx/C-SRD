#include <stdint.h>
uint32_t kernel(uint32_t x) {
    return (x & 255u) + ((x >> 8u) & 255u) + ((x >> 16u) & 255u) + (x >> 24u);
}
