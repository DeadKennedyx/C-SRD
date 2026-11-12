"""Independent guarded-memory oracles; private and public-return tasks are named separately."""
import random
from buffer_observation_cases import MASK,LAYOUTS

FUNCTIONS={'control_branch','control_early','control_loop','control_nested','control_loop_exit','control_loop_local'}


def cases(protocol='basis-parity-v2'):
    if protocol!='basis-parity-v2':raise ValueError('control corpus requires basis-parity-v2')
    rng=random.Random(20261116)
    result=[{'split':'training' if i<8 else 'heldout','x':(rng.getrandbits(32)&~7)|(i&7),
             'memory':[rng.getrandbits(32) for _ in range(64)]} for i in range(16)]
    result[1]['memory']=list(result[0]['memory']);result[1]['x']=result[0]['x']+1
    result[2]['memory']=[(x+1)&MASK for x in result[0]['memory']];result[2]['x']=result[0]['x']+2
    for row,x in zip(result[12:],(0,1,0x80000000,MASK)):row['x']=x
    return result


def expected(function,initial,p,q,x,**unused):
    memory=list(initial);before=(memory[p]+x)&MASK;targets={};result=None
    if function=='control_branch':
        stored=((3*before+11) if x&1 else (5*before+7))&MASK
        memory[p+1]=stored;memory[q]=(memory[p+1]+1)&MASK;result=memory[p]+memory[p+1]
        targets={'before':before,'stored':stored}
    elif function=='control_early':
        targets={'before':before}
        if not x:result=before
        else:
            memory[p+1]=(3*before+11)&MASK
            if memory[q]&1:result=memory[p+1]
            else:memory[q]=(5*before+7)&MASK;result=memory[p]+memory[q]
        targets['public_return']=result&MASK
    elif function in ('control_loop','control_nested','control_loop_exit','control_loop_local'):
        n=((x>>1) if function=='control_loop_exit' else x)&3
        total=before if function in ('control_loop_exit','control_loop_local') else x
        for i in range(n):
            if function=='control_loop_local':
                v=(3*total+11)&MASK;memory[p+i]=v;total=(v+memory[q])&MASK
            elif function=='control_nested':
                odd=memory[p+i]&1
                total=(total+memory[p+i] if odd else total-memory[p+i])&MASK
                memory[p+i]=((3*total+7) if odd else (5*total+11))&MASK
            else:
                total=(total+memory[p+i])&MASK
                if function=='control_loop_exit' and total&1:
                    result=(total+7)&MASK;break
                memory[p+i]=(3*total+11)&MASK
        if result is None:
            if function=='control_loop_local':memory[q+1]=total;result=total+memory[q]
            else:memory[q]=total;result=total+memory[p]
        targets={'sum':total}
        if function=='control_loop_local':targets['before']=before
        else:targets['public_return']=result&MASK
    else:raise ValueError('unknown control fixture')
    return {'return_value':result&MASK,'final_memory':memory,'targets':targets}


def signature(function,parameters):
    if function not in FUNCTIONS or [p['kind'] for p in parameters]!=['uint32-buffer','uint32-buffer','uint32']:
        raise ValueError('control corpus requires pointer,pointer,uint32 ABI')
    return 'uint32_t',f'uint32_t {function}(uint32_t*,uint32_t*,uint32_t);'


def driver(function,parameters):
    _,declaration=signature(function,parameters)
    return r'''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
uint32_t csrd_observation_memory[64];
'''+declaration+r'''
int main(void){
 unsigned p,q;uint32_t x;
 if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3 || p>48u || q>48u)return 2;
 for(unsigned i=0;i<64;i++)if(scanf("%" SCNu32,&csrd_observation_memory[i])!=1)return 3;
'''+f' uint32_t result={function}(csrd_observation_memory+p,csrd_observation_memory+q,x);\n'+r'''
 printf("%" PRIu32 "\n",result);
 for(unsigned i=0;i<64;i++)printf("%" PRIu32 "\n",csrd_observation_memory[i]);
 return 0;
}
'''
