#include <stdint.h>
uint32_t kernel(uint32_t x, uint32_t y) {
    uint32_t result = x;
    for (uint32_t i = 0; i < 3u; ++i) {
        result = 13u * result - y;
        result = result ^ (result >> 5u);
    }
    return result;
}
