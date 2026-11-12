/* Deterministic benign environment shared by execution/observation harnesses.
 * These callees are ordinary C; the transformer receives only their contracts.
 * The Python oracle implements their effects independently. */
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#ifndef CSRD_RECORD_CALLS
#define CSRD_RECORD_CALLS 1
#endif
struct event { uint32_t kind,x,p,q,state,memory[64]; };
_Static_assert(sizeof(struct event)==69u*sizeof(uint32_t),"call trace layout");
struct event events[8];
uint32_t external_state;
unsigned event_count;
static uint32_t *storage;
static void reset(uint32_t *memory,uint32_t state) {
 storage=memory;external_state=state;event_count=0;
 memset(events,0,sizeof events);
}
static uint32_t step(uint32_t x) { x^=x<<13;x^=x>>17;x^=x<<5;return x; }
static void record(uint32_t kind,uint32_t x,const void*p,const void*q) {
#if CSRD_RECORD_CALLS
 if(event_count>=8u)exit(98);
 struct event *e=events+event_count++;
 e->kind=kind;e->x=x;e->state=external_state;
 e->p=p ? (uint32_t)((const unsigned char*)p-(const unsigned char*)storage) : UINT32_MAX;
 e->q=q ? (uint32_t)((const unsigned char*)q-(const unsigned char*)storage) : UINT32_MAX;
 memcpy(e->memory,storage,sizeof e->memory);
#else
 (void)p;(void)q;
#endif
 external_state=step(external_state+x+kind);
}
uint32_t effect_value(uint32_t x) {
 record(1u,x,0,0);return (external_state&7u) ? x+external_state : 0u;
}
void effect_note(uint32_t x) { record(2u,x,0,0); }
uint32_t effect_mix(uint32_t*p,uint32_t*q,uint32_t x) {
 record(3u,x,p,q);p[0]=p[0]+x+external_state;q[1]=q[1]^(external_state>>1);
 return p[0]+q[0]+external_state;
}
void effect_bytes(unsigned char*p,uint32_t x) {
 record(4u,x,p,0);p[0]=(unsigned char)(x+external_state);p[1]=(unsigned char)(x>>8);
}
