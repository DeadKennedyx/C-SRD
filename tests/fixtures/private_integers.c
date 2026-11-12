#include <stdint.h>

extern uint32_t next_value(uint32_t value);
extern void record_event(uint32_t value);

/* Native LP64 test workload. Signed narrowing and negative right shift use the
 * declared GCC/Clang two's-complement model, not a universal C11 claim. */
uint32_t region_pipeline(uint32_t *buffer, uint32_t x, int limit)
{
    uint32_t y = buffer[0];
    unsigned char byte = (unsigned char)x;
    signed char small = (signed char)y;
    short half = (short)(x >> 8);
    int delta = (int)byte + (int)small + (int)half;
    long wide = 3L * delta - 5L;
    long long adjusted = (long long)wide + 4294967297LL;
    unsigned long long packed = ((unsigned long long)x << 32) | (unsigned long long)y;
    packed = 7ULL * packed + 0xfedcba9876543210ULL;
    _Bool negative = delta < 0;
    int magnitude = negative ? -delta : delta;
    uint32_t result = (uint32_t)(packed >> 32) + (uint32_t)adjusted + (uint32_t)magnitude;
    record_event(result);
    if (limit < 0) return result;
    while (limit-- > 0) {
        y = next_value(result);
        int step = (int)(signed char)y;
        long long blended = (long long)step + (long long)magnitude;
        packed = packed + ((unsigned long long)y << 17);
        packed = 3ULL * packed + 11ULL;
        long long shifted = blended >> 2;
        result = (uint32_t)(packed >> 32) + (uint32_t)shifted;
        buffer[0] = result;
        buffer[2] = (uint32_t)packed;
        record_event(y);
    }
    return result;
}

int region_outputs(uint32_t *buffer, uint32_t x, uint32_t y)
{
    unsigned char byte = (unsigned char)x;
    unsigned short half = (unsigned short)y;
    _Bool flag = byte + half;
    int small = (int)(signed char)byte;
    int ordered = small < half;
    unsigned int mixed = (unsigned int)small + x;
    long long extended = (long long)(short)half;
    unsigned long long packed = ((unsigned long long)mixed << 32) | (unsigned long long)half;
    packed = packed + 9ULL;
    uint32_t result = (uint32_t)(packed >> 32) + (uint32_t)(extended >> 3) + flag + ordered;
    record_event(result);
    buffer[0] = (uint32_t)packed;
    buffer[1] = result;
    buffer[2] = (uint32_t)extended;
    return flag == ordered;
}
