"""Independent callback/recursion effects; no source or encoding hints for fits."""
from pathlib import Path
import random

ROOT=Path(__file__).resolve().parents[1]
MASK=0xffffffff
INITIAL_STATE=0x12345678
ENVIRONMENT=ROOT/'tests/fixtures/dispatch_environment.h'
INDIRECT={'dispatch_choice','dispatch_sequence','dispatch_loop'}
RECURSIVE={'recursive_fold','recursive_branch'}
FUNCTIONS=INDIRECT|RECURSIVE|{'guarded_direct'}
LAYOUTS=[(4,4),(4,5)]


def cases(protocol='basis-parity-v2'):
    if protocol!='basis-parity-v2':raise ValueError('dispatch corpus requires basis-parity-v2')
    rng=random.Random(20261118);result=[]
    for split in ('training','heldout'):
        for i,x in enumerate([*range(10),MASK,0x80000000]):
            memory=[rng.getrandbits(32) for _ in range(64)]
            # A separate public input selects all four target equality patterns.
            memory[63]=(memory[63]&~3)|(i&3)
            result.append({'split':split,'x':x,'memory':memory})
    return result


def parameters(function):
    params=[{'kind':k,'read_only':False} for k in ('uint32-buffer','uint32-buffer','uint32')]
    if function in INDIRECT:
        params += [{'kind':'function-pointer','name':name,'read_only':False,
                    'returns':'uint32','parameters':[dict(p) for p in params]} for name in ('first','second')]
    return params


def signature(function,params):
    kinds=['uint32-buffer','uint32-buffer','uint32']+(['function-pointer']*2 if function in INDIRECT else [])
    if function not in FUNCTIONS or [p['kind'] for p in params]!=kinds:
        raise ValueError('dispatch corpus requires its declared pointer/scalar/callback ABI')
    callback=',uint32_t(*)(uint32_t*,uint32_t*,uint32_t)'*2 if function in INDIRECT else ''
    return 'uint32_t',f'uint32_t {function}(uint32_t*,uint32_t*,uint32_t{callback});'


def expected(function,initial,p,q,x,**unused):
    memory=list(initial);state=INITIAL_STATE;events=[];targets={}
    binding=initial[63]&3
    def call(kind,a,b,v):
        nonlocal state
        v&=MASK;events.append([kind,v,a,b,state,*memory])
        state=(state+v+kind)&MASK
        state^=(state<<13)&MASK;state^=state>>17;state^=(state<<5)&MASK
        if kind==1:
            memory[a]=(memory[a]+v+state)&MASK;memory[b+1]=(memory[b+1]+3*v)&MASK
            return (memory[a]+memory[b]+state)&MASK
        memory[b]^=v^state;memory[a+1]=(memory[a+1]+5*v)&MASK
        return memory[a]^memory[b]^state
    first,second=1+(binding&1),1+((binding>>1)&1)
    if function=='dispatch_choice':
        argument=(3*x+11)&MASK
        reply=call(first,p,q,argument) if x&1 else call(second,q,p,argument+1)
        value=(reply+(7 if x&1 else 13))&MASK;result=value+memory[p]
        targets={'argument':argument,'reply':reply,'result':value}
    elif function=='dispatch_sequence':
        before=memory[p];value=call(first,p,q,x+before)
        if value&1:value=(call(second,p,q,value)+3)&MASK
        else:memory[p]=(value+5)&MASK
        last=call(second,q,p,value+before);result=last+before
        targets={'before':before,'result':value,'last':last}
    elif function=='dispatch_loop':
        total=x
        for i in range((x&3)+1):total=(call(first,p,q,total+i)+3)&MASK
        last=call(second,q,p,total);result=last+total;targets={'sum':total,'last':last}
    elif function=='guarded_direct':
        value=(x+1)&MASK
        value=call(1,p,q,value) if x&1 else call(2,q,p,value+3)
        for i in range(x&3):value=call(1,p,q,value+i)
        result=value+memory[q];targets={'result':value}
    elif function in RECURSIVE:
        targets={'before':None,'child':None}
        def recurse(a,b,depth,root=False):
            if depth>8:return ((memory[a]+101) if function=='recursive_fold' else (memory[b]+103))&MASK
            if not depth:return (memory[a]+3)&MASK if function=='recursive_fold' else memory[a]^memory[b]
            before=memory[a] if function=='recursive_fold' else memory[b]
            step=2 if function=='recursive_branch' and depth>1 and memory[a]&1 else 1
            memory[a]=(memory[a]+3*depth)&MASK
            child=recurse(a,b,depth-1) if function=='recursive_fold' else recurse(b,a,depth-step)
            if root:targets.update(before=before,child=child)
            if function=='recursive_fold':memory[b]=(child+5)&MASK;return (child+before+7)&MASK
            memory[a]=(child+before)&MASK;return (memory[a]+5)&MASK
        result=recurse(p,q,x,True)
    else:raise ValueError('unknown dispatch fixture')
    targets['public_return']=result&MASK
    return {'return_value':result&MASK,'final_memory':memory,'targets':targets,
            'external_state':state,'events':events}


def invocation(function,p='memory+p',q='memory+q',x='x',selector='memory[63]'):
    callbacks=f',({selector}&1u)?dispatch_xor:dispatch_add,({selector}&2u)?dispatch_xor:dispatch_add' if function in INDIRECT else ''
    return f'{function}({p},{q},{x}{callbacks})'


def driver(function,params):
    _,declaration=signature(function,params)
    return r'''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
uint32_t csrd_observation_memory[64];
'''+ENVIRONMENT.read_text()+'\n'+declaration+r'''
int main(void){
 unsigned p,q;uint32_t x;
 if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3 || p>48u || q>48u)return 2;
 for(unsigned i=0;i<64;i++)if(scanf("%" SCNu32,&csrd_observation_memory[i])!=1)return 3;
'''+f' reset(csrd_observation_memory,{INITIAL_STATE}u);\n uint32_t result='+invocation(function,'csrd_observation_memory+p','csrd_observation_memory+q',selector='csrd_observation_memory[63]')+r''';
 printf("%" PRIu32 "\n",result);
 for(unsigned i=0;i<64;i++)printf("%" PRIu32 "\n",csrd_observation_memory[i]);
 printf("%" PRIu32 " %u\n",external_state,event_count);
 for(unsigned i=0;i<event_count;i++){
  const struct event*e=events+i;
  printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 "\n",e->kind,e->x,e->p,e->q,e->state);
  for(unsigned j=0;j<64;j++)printf("%" PRIu32 "\n",e->memory[j]);
 }
 return 0;
}
'''
