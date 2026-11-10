#include <stdint.h>
uint32_t kernel(uint32_t x) {
    uint32_t rotated = (x << 13u) | (x >> 19u);
    return 7u * rotated - 31u;
}
