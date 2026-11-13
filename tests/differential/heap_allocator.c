/* Test-only allocator environment. The transformed fixture still uses the
 * standard C API; compiler command-line renaming binds it to these wrappers.
 * Record logical object identities, never read an old pointer after realloc. */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

struct heap_event { unsigned kind, id, success; size_t count, width; };
struct heap_slot { void *pointer; size_t bytes; unsigned id, live; };
static struct heap_slot heap_slots[16];
static struct heap_event heap_events[64];
static unsigned heap_event_count, heap_request, heap_failures, heap_move;

static void heap_reset(unsigned failures, unsigned move)
{
    for (unsigned i=0;i<16;i++) if (heap_slots[i].live) { fputs("leaked heap object\n",stderr); exit(2); }
    memset(heap_slots,0,sizeof heap_slots);
    memset(heap_events,0,sizeof heap_events);
    heap_event_count=heap_request=0; heap_failures=failures; heap_move=move;
}

static unsigned heap_slot(void *pointer)
{
    for (unsigned i=0;i<16;i++)
        if (heap_slots[i].live && heap_slots[i].pointer==pointer) return i;
    fputs("invalid owned base\n",stderr); exit(2);
}

static void heap_record(unsigned kind,unsigned id,size_t count,size_t width,unsigned success)
{
    if (heap_event_count>=64) { fputs("allocator trace overflow\n",stderr); exit(2); }
    struct heap_event *e=&heap_events[heap_event_count++];
    e->kind=kind; e->id=id; e->count=count; e->width=width; e->success=success;
}

static void *heap_allocate(unsigned kind, void *old, size_t count, size_t width)
{
    unsigned request=heap_request++, slot=0, old_id=0;
    if (request>=16) { fputs("allocation request overflow\n",stderr); exit(2); }
    if (old) { slot=heap_slot(old); old_id=heap_slots[slot].id; }
    if (heap_failures & (1u<<request)) {
        heap_record(kind,old_id,count,width,0); return 0;
    }
    size_t bytes=count*width;
    void *result;
    if (kind==3 && old) {
        if (heap_move) {
            result=malloc(bytes);
            if (result) {
                size_t keep=heap_slots[slot].bytes<bytes ? heap_slots[slot].bytes : bytes;
                memcpy(result,old,keep); free(old);
            }
        } else result=realloc(old,bytes);
        /* old is indeterminate after success; use the saved slot and id. */
        if (result) heap_slots[slot].live=0;
    } else result=kind==2 ? calloc(count,width) : malloc(bytes);
    if (!result) { fputs("unexpected real allocation failure\n",stderr); exit(2); }
    for (slot=0;slot<16 && heap_slots[slot].live;slot++) {}
    if (slot==16) { fputs("allocator slot overflow\n",stderr); exit(2); }
    heap_slots[slot]=(struct heap_slot){result,bytes,request+1,1};
    heap_record(kind,old_id,count,width,1);
    return result;
}

static void heap_release(void *pointer)
{
    unsigned id=0;
    if (pointer) {
        unsigned slot=heap_slot(pointer); id=heap_slots[slot].id;
        free(pointer); heap_slots[slot].live=0;
    }
    heap_record(4,id,0,0,1);
}

#define WRAPPERS(prefix) \
void *prefix##_malloc(size_t n){return heap_allocate(1,0,n,1);} \
void *prefix##_calloc(size_t n,size_t w){return heap_allocate(2,0,n,w);} \
void *prefix##_realloc(void*p,size_t n){return heap_allocate(3,p,n,1);} \
void prefix##_free(void*p){heap_release(p);}
WRAPPERS(original)
WRAPPERS(candidate)
