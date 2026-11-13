#include <stdint.h>
#include <stdio.h>

uint32_t io_read_mix(FILE *input, FILE *output, uint32_t *p, uint32_t x)
{
    (void)output;
    uint32_t c = (uint32_t)fgetc(input);
    if (c > 255u) {
        uint32_t error = (uint32_t)ferror(input);
        uint32_t end = (uint32_t)feof(input);
        p[0] = error + 3u * end;
        return p[0] + 101u;
    }
    uint32_t sum = c + 3u * x + p[0];
    p[0] = sum;
    return sum + 7u;
}

uint32_t io_write_mix(FILE *input, FILE *output, uint32_t *p, uint32_t x)
{
    (void)input;
    uint32_t value = 3u * x + p[0] + 11u;
    uint32_t written = (uint32_t)fputc((int)(value & 255u), output);
    if (written > 255u) {
        uint32_t error = (uint32_t)ferror(output);
        p[0] = error + 5u;
        return p[0] + 211u;
    }
    uint32_t flushed = (uint32_t)fflush(output);
    p[0] = value + 7u * written;
    return p[0] + flushed;
}

uint32_t io_transfer(FILE *input, FILE *output, uint32_t *p, uint32_t x)
{
    uint32_t count = (x & 3u) + 1u;
    uint32_t sum = p[0];
    for (uint32_t i = 0u; i < count; ++i) {
        uint32_t c = (uint32_t)fgetc(input);
        if (c > 255u) {
            uint32_t end = (uint32_t)feof(input);
            uint32_t error = (uint32_t)ferror(input);
            p[0] = sum;
            return sum + 3u * end + 5u * error;
        }
        uint32_t written = (uint32_t)fputc((int)((c + 3u * x + i) & 255u), output);
        if (written > 255u) {
            p[0] = sum;
            return sum + 257u;
        }
        sum = 3u * sum + c + 1u;
    }
    uint32_t flushed = (uint32_t)fflush(output);
    p[0] = sum;
    return sum + flushed;
}

uint32_t io_status(FILE *input, FILE *output, uint32_t *p, uint32_t x)
{
    (void)output;
    uint32_t error = (uint32_t)ferror(input);
    uint32_t end = (uint32_t)feof(input);
    clearerr(input);
    uint32_t after_error = (uint32_t)ferror(input);
    uint32_t after_end = (uint32_t)feof(input);
    uint32_t sum = 3u * error + end + 5u * after_error + 7u * after_end + x;
    p[0] = sum;
    return sum + 17u;
}

uint32_t io_branch_stream(FILE *input, FILE *output, uint32_t *p, uint32_t x)
{
    uint32_t written = 0u;
    if (x & 1u) written = (uint32_t)fputc((int)(x & 255u), output);
    else written = (uint32_t)fputc((int)(x & 255u), input);
    return written + p[0] + 7u * x;
}

uint32_t io_emit_pair(FILE *input, FILE *output, uint32_t *p, uint32_t x)
{
    (void)input;
    uint32_t value = 7u * x + p[0];
    uint32_t first = (uint32_t)fputc((int)(value & 255u), output);
    if (first > 255u) return first + value;
    uint32_t second = (uint32_t)fputc((int)((value >> 8u) & 255u), output);
    p[0] = value + first;
    return p[0] + 3u * second;
}
