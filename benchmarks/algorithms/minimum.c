#include <stdint.h>
uint32_t kernel(uint32_t x, uint32_t y) {
    uint32_t result = x;
    if (y < x) { result = y; }
    return result;
}
