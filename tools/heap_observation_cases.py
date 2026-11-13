"""Independent heap fixture oracles; runtime measurements use real successful allocations."""
import random

MASK=(1<<32)-1
LAYOUTS=((0,0),(63,0))
FUNCTIONS={'heap_pair','heap_zero','heap_resize','heap_shrink','heap_nullable','heap_repeated'}


def cases(protocol='basis-parity-v2'):
    if protocol!='basis-parity-v2':raise ValueError('heap corpus requires basis-parity-v2')
    rng=random.Random(20261117)
    rows=[{'split':'training' if i<8 else 'heldout','x':(rng.getrandbits(32)&~3)|(i&3),
           'memory':[rng.getrandbits(32) for _ in range(64)]} for i in range(16)]
    for row,x in zip(rows[12:],(0,1,0x80000000,MASK)):row['x']=x
    return rows


def expected(function,initial,p,q,x,*,failures=0,**unused):
    memory=list(initial);targets={}
    first_failed=bool(failures&1)
    if function=='heap_pair':
        before=(x+3)&MASK;stored=(3*before+5)&MASK
        result=x+1 if first_failed else before+stored
        if not first_failed:memory[p]=stored;targets={'before':before,'stored':stored}
    elif function=='heap_zero':
        n=(x&3)+1;value=(3*x)&MASK
        result=x+7 if first_failed else value+n
        if not first_failed:memory[p]=(result+11)&MASK;targets={'first':value}
    elif function=='heap_resize':
        first=(x+3)&MASK;combined=(first+5*x+7)&MASK
        result=x+13 if first_failed else combined+17 if failures&2 else 3*combined+19
        if not first_failed:memory[p]=combined;targets={'first':first,'combined':combined}
    elif function=='heap_shrink':
        before=(x+29)&MASK;result=x+23 if first_failed else 4*before
        if not first_failed:
            targets={'before':before}
            if not failures&2:memory[p]=result&MASK
    elif function=='heap_nullable':
        result=x+31 if first_failed else 7*x+37
        if not first_failed:memory[p]=result&MASK
    elif function=='heap_repeated':
        result=x
        for i in range(3):
            if failures&(1<<i):break
            result=(result+3*i+41)&MASK
            if i<2:targets[f'sum_{i}']=result
        else:memory[p]=result
    else:raise ValueError('unknown heap fixture')
    targets['public_return']=result&MASK
    return {'return_value':result&MASK,'final_memory':memory,'targets':targets}


def signature(function,parameters):
    if function not in FUNCTIONS or [p['kind'] for p in parameters]!=['uint32-buffer','uint32']:
        raise ValueError('heap corpus requires pointer,uint32 ABI')
    return 'uint32_t',f'uint32_t {function}(uint32_t*,uint32_t);'


def driver(function,parameters):
    _,declaration=signature(function,parameters)
    return r'''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
uint32_t csrd_observation_memory[64];
'''+declaration+r'''
int main(void){
 unsigned p,q;uint32_t x;
 if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3 || p>63u || q!=0)return 2;
 for(unsigned i=0;i<64;i++)if(scanf("%" SCNu32,&csrd_observation_memory[i])!=1)return 3;
'''+f' uint32_t result={function}(csrd_observation_memory+p,x);\n'+r'''
 printf("%" PRIu32 "\n",result);
 for(unsigned i=0;i<64;i++)printf("%" PRIu32 "\n",csrd_observation_memory[i]);
 return 0;
}
'''
