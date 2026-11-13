#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint32_t (*io_operation)(FILE *, FILE *, uint32_t *, uint32_t);
struct io_snapshot {
    uint32_t result, memory[64];
    int saved_errno, end[2], error[2], flush_result, flush_errno, close_result[2];
    long position[2];
    unsigned char contents[2][64];
    size_t sizes[2];
};

/* Real C stdio. Linux additionally supplies a readable directory and /dev/full
   for actual read/write/flush failures. No invalid stream mode is exercised. */
static int io_execute(io_operation operation, const uint32_t initial[64], uint32_t x,
                      unsigned scenario, unsigned at_end, struct io_snapshot *result)
{
    const unsigned lengths[] = {0u, 1u, 3u, 8u};
    FILE *files[2] = {NULL, NULL};
    memset(result, 0, sizeof *result);
#ifdef __linux__
    files[0] = scenario == 4u ? fopen("/", "rb") : tmpfile();
    files[1] = scenario >= 5u ? fopen("/dev/full", "wb") : tmpfile();
#else
    if (scenario >= 4u) return 0;
    files[0] = tmpfile(); files[1] = tmpfile();
#endif
    if (!files[0] || !files[1]) goto failed;
    if (scenario == 5u && setvbuf(files[1], NULL, _IONBF, 0) != 0) goto failed;
    if (scenario == 6u && setvbuf(files[1], NULL, _IOFBF, BUFSIZ) != 0) goto failed;
    if (scenario != 4u) {
        unsigned char bytes[8];
        for (unsigned i = 0; i < 8u; ++i) bytes[i] = (unsigned char)initial[8u+i];
        const unsigned length = scenario < 4u ? lengths[scenario] : 8u;
        if (fwrite(bytes, 1, length, files[0]) != length || fseek(files[0], 0, SEEK_SET) != 0) goto failed;
    }
    if (at_end) {
        /* An update stream may switch from input to output after reaching EOF. */
        while (fgetc(files[0]) != EOF) {}
    }
    memcpy(result->memory, initial, sizeof result->memory);
    errno = 0;
    result->result = operation(files[0], files[1], result->memory+4, x);
    result->saved_errno = errno;
    for (unsigned i = 0; i < 2u; ++i) {
        result->end[i] = feof(files[i]); result->error[i] = ferror(files[i]);
        result->position[i] = ftell(files[i]);
    }
    if (scenario >= 5u) {
        /* Include errors deferred by buffering, after saving the root result. */
        errno = 0; result->flush_result = fflush(files[1]); result->flush_errno = errno;
    }
    for (unsigned i = 0; i < 2u; ++i) {
        if ((i == 0u && scenario == 4u) || (i == 1u && scenario >= 5u)) continue;
        if (fseek(files[i], 0, SEEK_SET) != 0) goto failed;
        result->sizes[i] = fread(result->contents[i], 1, sizeof result->contents[i], files[i]);
        if (ferror(files[i]) || result->sizes[i] == sizeof result->contents[i]) goto failed;
    }
    result->close_result[0] = fclose(files[0]);
    result->close_result[1] = fclose(files[1]);
    return 1;
failed:
    if (files[0]) (void)fclose(files[0]);
    if (files[1]) (void)fclose(files[1]);
    return 0;
}

static int io_equal(const struct io_snapshot *a, const struct io_snapshot *b)
{
    if (a->result != b->result || a->saved_errno != b->saved_errno ||
        a->flush_result != b->flush_result || a->flush_errno != b->flush_errno ||
        memcmp(a->memory, b->memory, sizeof a->memory)) return 0;
    for (unsigned i = 0; i < 2u; ++i) {
        if (a->end[i] != b->end[i] || a->error[i] != b->error[i] ||
            a->position[i] != b->position[i] || a->sizes[i] != b->sizes[i] ||
            a->close_result[i] != b->close_result[i] ||
            memcmp(a->contents[i], b->contents[i], a->sizes[i])) return 0;
    }
    return 1;
}
