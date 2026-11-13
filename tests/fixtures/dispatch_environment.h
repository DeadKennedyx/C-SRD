/* Benign stateful callbacks. Python implements a separate execution oracle. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
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
 storage=memory;external_state=state;event_count=0;memset(events,0,sizeof events);
}
static uint32_t step(uint32_t x) { x^=x<<13;x^=x>>17;x^=x<<5;return x; }
static void record(uint32_t kind,uint32_t x,uint32_t*p,uint32_t*q) {
#if CSRD_RECORD_CALLS
 if(event_count>=8u)exit(98);
 struct event *e=events+event_count++;
 e->kind=kind;e->x=x;e->state=external_state;
 e->p=(uint32_t)(p-storage);e->q=(uint32_t)(q-storage);
 memcpy(e->memory,storage,sizeof e->memory);
#else
 (void)p;(void)q;
#endif
 external_state=step(external_state+x+kind);
}
uint32_t dispatch_add(uint32_t*p,uint32_t*q,uint32_t x) {
 record(1u,x,p,q);p[0]=p[0]+x+external_state;q[1]=q[1]+3u*x;
 return p[0]+q[0]+external_state;
}
uint32_t dispatch_xor(uint32_t*p,uint32_t*q,uint32_t x) {
 record(2u,x,p,q);q[0]=q[0]^x^external_state;p[1]=p[1]+5u*x;
 return p[0]^q[0]^external_state;
}
