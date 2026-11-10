#include <stdint.h>
uint32_t kernel(uint32_t x, uint32_t y) {
    uint32_t result = x;
    for (uint32_t i = 0; i < 4u; ++i) {
        result = 9u * result + y + i;
    }
    return result;
}
