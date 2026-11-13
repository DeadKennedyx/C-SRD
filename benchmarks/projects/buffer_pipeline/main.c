#include "pipeline.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    if (argc != 5) return 2;
    uint32_t seed = (uint32_t)strtoul(argv[1], NULL, 10);
    size_t count = (size_t)strtoul(argv[2], NULL, 10);
    size_t repeats = (size_t)strtoul(argv[3], NULL, 10);
    if (count > 64u || repeats > 10000000u) return 3;
    uint32_t *values = malloc((count + 1u) * sizeof(*values));
    if (!values) return 4;
    for (size_t i = 0; i < count; ++i)
        values[i] = seed + (uint32_t)i;
    values[count] = 0x12345678u;
    uint32_t result = 0u;
    for (size_t j = 0; j < repeats; ++j) {
        map_values(values, count);
        result = result + reduce_values(values, count);
    }
    FILE *stream = fopen(argv[4], "wb");
    if (!stream) { free(values); return 5; }
    int failed = fprintf(stream, "%u\n", (unsigned)result) < 0;
    for (size_t i = 0; i <= count; ++i)
        if (fprintf(stream, "%u\n", (unsigned)values[i]) < 0) failed = 1;
    if (fclose(stream)) failed = 1;
    printf("%s:%u:%u\n", __FILE__, (unsigned)PROJECT_OFFSET, (unsigned)result);
    free(values);
    return failed ? 6 : 0;
}
