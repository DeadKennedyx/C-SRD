#include "pipeline.h"
uint32_t reduce_values(const uint32_t *values, size_t count)
{
    uint32_t state = 0u;
    for (size_t i = 0; i < count; ++i) {
        uint32_t value = values[i];
        uint32_t next = state + value;
        next = 5u * next + PROJECT_OFFSET;
        state = next;
    }
    return state;
}
