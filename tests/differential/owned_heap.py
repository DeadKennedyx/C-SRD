#!/usr/bin/env python3
"""Real-library executions plus deterministic failure/moving-realloc controls."""
import argparse
from pathlib import Path
import buffers

NAMES=('heap_pair','heap_zero','heap_resize','heap_shrink','heap_nullable','heap_repeated')


def harness(injected):
    declarations='\n'.join(f'uint32_t {prefix}_{name}(uint32_t*,uint32_t);'
                           for prefix in ('original','candidate') for name in NAMES)
    functions='\n'.join('{original_'+name+',candidate_'+name+'},' for name in NAMES)
    allocator=(Path(__file__).with_name('heap_allocator.c').read_text() if injected else '')
    before='heap_reset(mask,move);' if injected else ''
    between='''
            struct heap_event expected[64];
            memcpy(expected,heap_events,sizeof expected);
            unsigned expected_count=heap_event_count;
            heap_reset(mask,move);
    ''' if injected else ''
    after='''
            if (heap_event_count!=expected_count || memcmp(expected,heap_events,sizeof expected)) {
                fprintf(stderr,"allocator event mismatch fn=%u mask=%u move=%u\\n",fn,mask,move); return 1;
            }
            heap_reset(mask,move);
    ''' if injected else ''
    return f'''#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
{allocator}
{declarations}
static uint32_t state=0x43535244u;
static uint32_t next(void){{state^=state<<13;state^=state>>17;state^=state<<5;return state;}}
int main(void){{
    uint32_t (*functions[][2])(uint32_t*,uint32_t)={{{functions}}};
    const uint32_t edges[]={{0u,1u,2u,3u,2147483647u,2147483648u,2147483649u,4294967294u,4294967295u}};
    for(unsigned mask=0;mask<{8 if injected else 1};mask++)
    for(unsigned move=0;move<{2 if injected else 1};move++)
    for(unsigned layout=0;layout<2;layout++)
    for(unsigned iteration=0;iteration<{buffers.CASES};iteration++){{
        uint32_t x=iteration<9 ? edges[iteration] : next();
        uint32_t initial[8],a[8],b[8];
        for(unsigned k=0;k<8;k++) initial[k]=next();
        for(unsigned fn=0;fn<{len(NAMES)};fn++){{
            memcpy(a,initial,sizeof a); memcpy(b,initial,sizeof b);
            {before}
            uint32_t left=functions[fn][0](a+7*layout,x);
            {between}
            uint32_t right=functions[fn][1](b+7*layout,x);
            {after}
            if(left!=right || memcmp(a,b,sizeof a)){{
                fprintf(stderr,"heap mismatch fn=%u x=%u mask=%u move=%u layout=%u\\n",fn,x,mask,move,layout);return 1;
            }}
        }}
    }}
    puts("PASS heap return, caller memory and {'allocator traces' if injected else 'real allocator'}");return 0;
}}
'''


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--csrd',required=True); p.add_argument('--report',required=True)
    p.add_argument('--output-dir'); p.add_argument('--inject-failures',action='store_true')
    args=p.parse_args()
    injected=args.inject_failures
    buffers.run_fixture(args,buffers.ROOT/'tests/fixtures/owned_heap.c',NAMES,harness(injected),'owned-heap-c11-v1',
        len(NAMES)*buffers.CASES*2*(16 if injected else 1),
        {'allocator_environment':'injected-failures-and-moving-realloc' if injected else 'real-standard-library',
         'failure_masks':list(range(8)) if injected else [], 'forced_move_modes':[False,True] if injected else [],
         'caller_storage_words':8,'output_offsets':[0,7],
         'allocator_trace_compared':injected},
        rename_symbols=('malloc','calloc','realloc','free') if injected else ())
