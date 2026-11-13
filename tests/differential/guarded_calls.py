#!/usr/bin/env python3
"""Call identities/effects, recursion depths, alias layouts and compiler profiles."""
import argparse
import hashlib
import buffers
from dispatch_observation_cases import ENVIRONMENT,INDIRECT,RECURSIVE,FUNCTIONS,parameters,signature

NAMES=tuple(sorted(FUNCTIONS))


def harness():
    declarations=[];checks=[]
    for name in NAMES:
        for prefix in ('original','candidate'):
            declarations.append(signature(name,parameters(name))[1].replace(name+'(',prefix+'_'+name+'('))
        def invoke(prefix,storage):
            callbacks=',first,second' if name in INDIRECT else ''
            value='depth' if name in RECURSIVE else 'x'
            return f'{prefix}_{name}({storage}+po,{storage}+qo,{value}{callbacks})'
        checks.append(f'''memcpy(a,initial,sizeof a);memcpy(b,initial,sizeof b);
 reset(a,seed);uint32_t r_{name}={invoke('original','a')};
 uint32_t s_{name}=external_state;unsigned n_{name}=event_count;memcpy(saved,events,sizeof events);
 reset(b,seed);
 if(r_{name}!={invoke('candidate','b')} || memcmp(a,b,sizeof a) || s_{name}!=external_state ||
    n_{name}!=event_count || memcmp(saved,events,sizeof events)){{
  fprintf(stderr,"dispatch mismatch {name} layout=%u iteration=%u binding=%u\\n",layout,iteration,binding);return 1;
 }}''')
    offsets=','.join(f'{{{p},{q}}}' for p,q in buffers.LAYOUTS)
    return '#include <stdio.h>\n'+ENVIRONMENT.read_text()+'\nstatic struct event saved[8];\n'+'\n'.join(declarations)+f'''
int main(void){{
 const uint32_t edges[]={{0u,1u,2u,3u,2147483647u,2147483648u,2147483649u,4294967294u,4294967295u}};
 const unsigned offsets[][2]={{{offsets}}};uint32_t initial[64],a[64],b[64],rng=0x43535244u;
 for(unsigned layout=0;layout<{len(buffers.LAYOUTS)};layout++)for(unsigned iteration=0;iteration<{buffers.CASES};iteration++){{
  rng=step(rng);uint32_t x=iteration<9?edges[iteration]:rng;
  uint32_t depth=iteration%12u<10u?iteration%12u:x;rng=step(rng);uint32_t seed=rng;
  for(unsigned i=0;i<64;i++){{rng=step(rng);initial[i]=iteration<9?edges[(i+iteration)%9]:rng;}}
  unsigned po=offsets[layout][0],qo=offsets[layout][1];
  for(unsigned binding=0;binding<4;binding++){{
   uint32_t(*first)(uint32_t*,uint32_t*,uint32_t)=(binding&1u)?dispatch_xor:dispatch_add;
   uint32_t(*second)(uint32_t*,uint32_t*,uint32_t)=(binding&2u)?dispatch_xor:dispatch_add;
   {chr(10).join(checks)}
  }}
 }}
 puts("PASS guarded calls, target identities, recursion, entire memory and external state");return 0;
}}
'''


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--csrd',required=True);p.add_argument('--report',required=True);p.add_argument('--output-dir')
    args=p.parse_args();contracts=buffers.ROOT/'tests/fixtures/guarded_calls.json'
    buffers.run_fixture(args,buffers.ROOT/'tests/fixtures/guarded_calls.c',NAMES,harness(),'guarded-calls-c11-v2',
        len(NAMES)*len(buffers.LAYOUTS)*buffers.CASES*4,
        {'pointer_offsets':buffers.LAYOUTS,'callback_bindings':['add/add','xor/add','add/xor','xor/xor'],
         'recursive_ranks':'0..9 and full-width boundary/random values','storage_words':64,
         'call_contracts_sha256':hashlib.sha256(contracts.read_bytes()).hexdigest(),
         'effects_checked':'returns, entire memory, external state and executed callback identities/arguments/pre-call memory'},
        transform_flags=('--call-contracts',contracts))
