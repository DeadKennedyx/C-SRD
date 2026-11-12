#include "records.h"
uint32_t csrd_counter = 11u;
struct csrd_pair csrd_state = {3u, 7u};
union csrd_word csrd_mode = {19u};

uint32_t records_pair(struct csrd_pair *p, uint32_t *q, uint32_t x)
{
    uint32_t before = p->first + x;
    p->second = 3u * before + 11u;
    q[0] = p->second + x;
    return p->first + p->second;
}

uint32_t records_alias(struct csrd_pair *p, uint32_t *q, uint32_t x)
{
    uint32_t before = q[0] + x;
    p[0].first = 5u * before + 7u;
    q[0] = q[0] + 3u;
    p->second = p->first + q[0];
    return p->second - before;
}

uint32_t records_index(struct csrd_pair *p, uint32_t *q, uint32_t x)
{
    struct csrd_pair *view = p + (x & 1u);
    x = x + 1u;
    uint32_t total = (*view).first + x;
    view->second = 7u * total + 19u;
    q[0] = view->second;
    return p[x & 1u].first + total;
}

uint32_t records_union(union csrd_word *p, uint32_t *q, uint32_t x)
{
    uint32_t before = p->value + x;
    p->alternate = 3u * before + 5u;
    q[0] = p->value + 1u;
    return p->alternate + before;
}

uint32_t records_counter(struct csrd_pair *p, uint32_t *q, uint32_t x)
{
    uint32_t before = csrd_counter + x;
    csrd_counter = 3u * before + 11u;
    q[0] = csrd_counter;
    return csrd_counter + p->first;
}

uint32_t records_state(struct csrd_pair *p, uint32_t *q, uint32_t x)
{
    uint32_t before = csrd_state.first + x;
    csrd_state.second = 5u * before + 7u;
    q[0] = csrd_state.second;
    p->first = csrd_state.first + q[0];
    return p->first + csrd_state.second;
}

uint32_t records_mode(union csrd_word *p, uint32_t *q, uint32_t x)
{
    uint32_t before = csrd_mode.value + x;
    csrd_mode.alternate = 7u * before + 19u;
    q[0] = csrd_mode.value;
    p->alternate = q[0] + x;
    return p->value + csrd_mode.alternate;
}
