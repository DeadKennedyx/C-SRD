#include <stdint.h>

extern uint32_t next_value(uint32_t value);
extern void record_event(uint32_t value);

uint32_t region_pipeline(uint32_t *buffer, uint32_t x, int limit)
{
    uint32_t y = buffer[0];
    x = x + y;
    x = 3u * x + 11u;
    record_event(x);
    if (limit < 0) return x;
    while (limit-- > 0) {
        y = next_value(x);
        x = x + y;
        x = 5u * x - 7u;
        buffer[0] = x;
        record_event(y);
    }
    return x;
}

int region_outputs(uint32_t *buffer, uint32_t x, uint32_t y)
{
    uint32_t pending;
    pending = 17u;
    pending = pending + x;
    x = 3u * pending + y;
    y = x - pending;
    record_event(x);
    buffer[0] = y;
    buffer[1] = pending;
    return x == y;
}
