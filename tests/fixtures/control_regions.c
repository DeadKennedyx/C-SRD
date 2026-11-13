#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>

unsigned flow_mix(unsigned x, unsigned count)
{
    unsigned i, result = x;
    for (i = 0; i < (count & 31u); ++i) {
        if ((result & 7u) == 0u) { result += 3u; continue; }
        if ((result & 127u) == 17u) break;
        result = (result ^ i) * 1664525u + 1013904223u;
    }
    do { result ^= count; count >>= 1u; } while (count > 1u);
    return result;
}

unsigned flow_buffer(unsigned *values, unsigned count, unsigned bias,
                     int (*step)(unsigned, unsigned *))
{
    unsigned total = 0u, i = 0u;
    if (count > 64u) return 0u;
    while (i < count) {
        if (values[i] & 1u) values[i] += bias;
        else values[i] ^= bias;
        total += values[i];
        if (step(values[i], values)) break;
        ++i;
    }
    return total;
}

unsigned flow_scopes(unsigned x, unsigned n)
{
    unsigned result = x;
    for (unsigned i = 0u; i < (n & 31u); ++i) {
        unsigned x = result + i;
        if (x & 1u) { result = x ^ 17u; continue; }
        result += x;
        if (result == 0u) break;
    }
    switch (n & 3u) {
    case 0: { unsigned x = result; x += 7u; result = x; break; }
    case 1: result ^= 3u; result += 9u; break;
    default: result += n;
    }
    result += 1u;
    return result;
}

unsigned flow_recursive(unsigned n, unsigned value)
{
    if (n == 0u) return value;
    if (n > 16u) return value ^ n;
    return flow_recursive(n - 1u, value * 3u + 11u);
}

double flow_floating(double value, unsigned mode)
{
    double result;
    if (mode & 1u) result = -value;
    else result = value;
    if (mode & 2u) result += 0.0;
    return result;
}

unsigned flow_heap(unsigned count, unsigned seed)
{
    unsigned *values;
    unsigned i, result = 0u;
    if (count > 64u) return 0u;
    values = malloc((count + 1u) * sizeof(*values));
    if (!values) return 0u;
    for (i = 0u; i < count; ++i) values[i] = seed + i;
    for (i = 0u; i < count; ++i) result = result * 5u + values[i];
    free(values);
    return result;
}

int flow_stream(FILE *input, FILE *output, unsigned limit)
{
    unsigned i = 0u;
    int value;
    while (i < limit && (value = fgetc(input)) >= 0) {
        ++i;
        if (value == 10) continue;
        if (fputc(value ^ 7, output) < 0) return -1;
    }
    if (ferror(input)) return -2;
    if (fflush(output)) return -3;
    return (int)i;
}

/* Line preservation must also cover code outside selected regions. */
unsigned flow_line(void) { return __LINE__; }
