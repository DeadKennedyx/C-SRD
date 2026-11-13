#include "pipeline.h"
uint32_t adjust(uint32_t value)
{
    uint32_t scaled = value * PROJECT_FACTOR;
    scaled = scaled + PROJECT_OFFSET;
    return scaled;
}
void map_values(uint32_t *values, size_t count)
{
    for (size_t i = 0; i < count; ++i)
        values[i] = adjust(values[i]);
}
