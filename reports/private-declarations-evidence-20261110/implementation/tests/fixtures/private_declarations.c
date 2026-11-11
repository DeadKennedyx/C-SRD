#include <stdint.h>

extern uint32_t next_value(uint32_t value);
extern void record_event(uint32_t value);

uint32_t region_pipeline(uint32_t *buffer, uint32_t x, int limit)
{
    uint32_t y = buffer[0];
    register uint32_t sum = x + y;
    uint32_t bias = 3u * sum + 11u;
    x = bias - y;
    record_event(sum);
    if (limit < 0) return x;
    while (limit-- > 0) {
        y = next_value(x);
        {
            x = x + y;
            uint32_t x = bias + 5u * y;
            uint32_t local = x - y;
            bias = local + sum;
            record_event(x);
            x = x + 7u;
            buffer[0] = x;
        }
        x = x + bias;
        record_event(y);
    }
    return x;
}

int region_outputs(uint32_t *buffer, uint32_t x, uint32_t y)
{
    register uint32_t pending = 17u;
    uint32_t mix = pending + x;
    x = 3u * mix + y;
    y = x - pending;
    record_event(x);
    {
        uint32_t y = x + 7u;
        buffer[2] = y;
    }
    buffer[0] = y;
    buffer[1] = pending;
    return x == y;
}
