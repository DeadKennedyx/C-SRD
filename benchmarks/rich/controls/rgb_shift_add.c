#include <stdint.h>

/* Algebraic positive control; this is not claimed as a different algorithm. */
uint32_t kernel(uint32_t rgb)
{
    uint32_t red = (rgb >> 16u) & 255u;
    uint32_t green = (rgb >> 8u) & 255u;
    uint32_t blue = rgb & 255u;
    uint32_t weighted = (red << 6u) + (red << 3u) + (red << 2u) + red;
    weighted = weighted + (green << 7u) + (green << 4u) + (green << 2u) + (green << 1u);
    weighted = weighted + (blue << 5u) - (blue << 1u) - blue;
    return weighted >> 8u;
}
