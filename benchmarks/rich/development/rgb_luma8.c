#include <stdint.h>

/* Defined integer weighting of 0x??RRGGBB, not a color-management standard. */
uint32_t kernel(uint32_t rgb)
{
    uint32_t red = (rgb >> 16u) & 255u;
    uint32_t green = (rgb >> 8u) & 255u;
    uint32_t blue = rgb & 255u;
    uint32_t weighted = 77u * red + 150u * green + 29u * blue;
    return weighted >> 8u;
}
