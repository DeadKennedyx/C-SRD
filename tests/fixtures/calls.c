#include <stdint.h>

uint32_t effect_value(uint32_t);
void effect_note(uint32_t);
uint32_t effect_mix(uint32_t *, uint32_t *, uint32_t);
void effect_bytes(unsigned char *, uint32_t);

uint32_t calls_scalar(uint32_t *p, uint32_t *q, uint32_t x) {
    (void)p; (void)q;
    uint32_t before = 3u*x+11u;
    uint32_t reply = effect_value(before);
    uint32_t after = 5u*reply+before;
    effect_note(after);
    return after-7u;
}

uint32_t calls_buffer(uint32_t *p, uint32_t *q, uint32_t x) {
    uint32_t sum = p[0]+x;
    p[1] = sum;
    uint32_t reply = effect_mix(p, q, 3u*sum+11u);
    p[0] = reply+x;
    return p[0]+q[0];
}

uint32_t calls_sequence(uint32_t *p, uint32_t *q, uint32_t x) {
    uint32_t a = effect_value(x+1u);
    uint32_t b = effect_mix(p, q, a+3u);
    effect_note(b);
    x = effect_value(b);
    return x+b;
}

uint32_t calls_view(uint32_t *p, uint32_t *q, uint32_t x) {
    uint32_t *view = p+(x&3u);
    x = x+1u;
    uint32_t reply = effect_mix(view, q, 7u*x+19u);
    return reply+p[0];
}

uint32_t calls_discard(uint32_t *p, uint32_t *q, uint32_t x) {
    effect_note(x);
    (void)effect_value(x+5u);
    effect_mix(p, q, x);
    return x;
}

uint32_t calls_tail(uint32_t *p, uint32_t *q, uint32_t x) {
    (void)p; (void)q;
    return effect_value(3u*x+5u);
}

uint32_t calls_bytes(unsigned char *p, uint32_t *q, uint32_t x) {
    uint32_t i = x&3u;
    uint32_t value = 7u*x+19u;
    effect_bytes(p+i, value);
    uint32_t reply = effect_mix(q, q, value);
    return reply+p[i]+value;
}
