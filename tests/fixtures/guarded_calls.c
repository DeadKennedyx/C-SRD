#include <stdint.h>

typedef uint32_t (*dispatch_op)(uint32_t *, uint32_t *, uint32_t);
uint32_t dispatch_add(uint32_t *, uint32_t *, uint32_t);
uint32_t dispatch_xor(uint32_t *, uint32_t *, uint32_t);

uint32_t dispatch_choice(uint32_t *p, uint32_t *q, uint32_t x, dispatch_op first, dispatch_op second)
{
    uint32_t result = 3u * x + 11u;
    if (x & 1u) {
        uint32_t left = first(p, q, result);
        result = left + 7u;
    } else {
        uint32_t right = second(q, p, result + 1u);
        result = right + 13u;
    }
    return result + p[0];
}

uint32_t dispatch_sequence(uint32_t *p, uint32_t *q, uint32_t x, dispatch_op first, dispatch_op second)
{
    uint32_t before = p[0];
    uint32_t result = first(p, q, x + before);
    if (result & 1u) {
        uint32_t next = second(p, q, result);
        result = next + 3u;
    } else {
        p[0] = result + 5u;
    }
    uint32_t last = second(q, p, result + before);
    return last + before;
}

uint32_t dispatch_loop(uint32_t *p, uint32_t *q, uint32_t x, dispatch_op first, dispatch_op second)
{
    uint32_t sum = x;
    uint32_t count = (x & 3u) + 1u;
    for (uint32_t i = 0u; i < count; ++i) {
        uint32_t value = first(p, q, sum + i);
        sum = value + 3u;
    }
    uint32_t last = second(q, p, sum);
    return last + sum;
}

uint32_t recursive_fold(uint32_t *p, uint32_t *q, uint32_t depth)
{
    if (depth > 8u) return p[0] + 101u;
    if (depth == 0u) return p[0] + 3u;
    uint32_t before = p[0];
    p[0] = before + 3u * depth;
    uint32_t child = recursive_fold(p, q, depth - 1u);
    q[0] = child + 5u;
    return child + before + 7u;
}

uint32_t recursive_branch(uint32_t *p, uint32_t *q, uint32_t depth)
{
    if (depth > 8u) return q[0] + 103u;
    if (depth == 0u) return p[0] ^ q[0];
    uint32_t before = q[0];
    uint32_t step = 1u;
    if (depth > 1u) {
        if (p[0] & 1u) step = 2u;
    }
    p[0] = p[0] + 3u * depth;
    uint32_t child = recursive_branch(q, p, depth - step);
    p[0] = child + before;
    return p[0] + 5u;
}

uint32_t guarded_direct(uint32_t *p, uint32_t *q, uint32_t x)
{
    uint32_t result = x + 1u;
    if (x & 1u) {
        result = dispatch_add(p, q, result);
    } else {
        result = dispatch_xor(q, p, result + 3u);
    }
    uint32_t count = x & 3u;
    for (uint32_t i = 0u; i < count; ++i) {
        result = dispatch_add(p, q, result + i);
    }
    return result + q[0];
}
