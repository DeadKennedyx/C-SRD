"""Independent effects/intermediate oracles for contracted direct-call fixtures."""
from pathlib import Path
from byte_observation_cases import cases, MASK

ROOT=Path(__file__).resolve().parents[1]
LAYOUTS=[(16,4),(16,5),(20,4),(16,20)]  # byte offset, word offset
FUNCTIONS={"calls_scalar","calls_buffer","calls_sequence","calls_view","calls_discard","calls_tail","calls_bytes"}
ENVIRONMENT=ROOT/"tests/fixtures/call_environment.h"
INITIAL_STATE=0x12345678


def signature(function,parameters):
    kind="unsigned-char-buffer" if function=="calls_bytes" else "uint32-buffer"
    if function not in FUNCTIONS or [p["kind"] for p in parameters]!=[kind,"uint32-buffer","uint32"]:
        raise ValueError("call corpus requires declared three-parameter ABI")
    byte_type="unsigned char" if function=="calls_bytes" else "uint32_t"
    return byte_type,f"uint32_t {function}({byte_type}*,uint32_t*,uint32_t);"


def expected(function,initial,p,q,x,**unused):
    memory=bytearray().join(word.to_bytes(4,"little") for word in initial)
    state=INITIAL_STATE;events=[];targets={};q*=4
    def word(at):return int.from_bytes(memory[at:at+4],"little")
    def put(at,value):memory[at:at+4]=(value&MASK).to_bytes(4,"little")
    def words():return [word(i) for i in range(0,256,4)]
    def record(kind,value,a=MASK,b=MASK):
        nonlocal state
        value&=MASK;events.append([kind,value,a,b,state,*words()])
        state=(state+value+kind)&MASK
        state^=(state<<13)&MASK;state^=state>>17;state^=(state<<5)&MASK
    def value(v):
        v&=MASK;record(1,v);return (v+state)&MASK if state&7 else 0
    def note(v):record(2,v)
    def mix(a,b,v):
        v&=MASK;record(3,v,a,b);put(a,word(a)+v+state);put(b+4,word(b+4)^(state>>1))
        return (word(a)+word(b)+state)&MASK
    if function=="calls_scalar":
        before=(3*x+11)&MASK;reply=value(before);after=(5*reply+before)&MASK;note(after)
        targets.update(before=before,reply=reply,after=after);result=after-7
    elif function=="calls_buffer":
        total=(word(p)+x)&MASK;put(p+4,total);reply=mix(p,q,3*total+11);put(p,reply+x)
        targets.update(sum=total,reply=reply);result=word(p)+word(q)
    elif function=="calls_sequence":
        a=value(x+1);b=mix(p,q,a+3);note(b);reply=value(b)
        targets.update(a=a,b=b,reply=reply);result=reply+b
    elif function=="calls_view":
        offset=(x&3)*4;x=(x+1)&MASK;reply=mix(p+offset,q,7*x+19)
        targets.update(reply=reply);result=reply+word(p)
    elif function=="calls_discard":note(x);value(x+5);mix(p,q,x);result=x;targets["input"]=x
    elif function=="calls_tail":
        argument=(3*x+5)&MASK;result=value(argument);targets.update(argument=argument,reply=result)
    elif function=="calls_bytes":
        i=x&3;v=(7*x+19)&MASK;record(4,v,p+i);memory[p+i]=(v+state)&255;memory[p+i+1]=(v>>8)&255
        reply=mix(q,q,v);result=reply+memory[p+i]+v;targets.update(value=v,reply=reply)
    else:raise ValueError("unknown call fixture")
    return {"return_value":result&MASK,"final_memory":words(),"targets":targets,
            "external_state":state,"events":events}


def driver(function,parameters):
    pointer,declaration=signature(function,parameters)
    return '''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
uint32_t csrd_observation_memory[64];
'''+ENVIRONMENT.read_text()+"\n"+declaration+'''
int main(void){
 unsigned int p,q;uint32_t x;
 if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3 || p>224u || p%4u || q>60u)return 2;
 for(unsigned int i=0;i<64u;++i)if(scanf("%" SCNu32,&csrd_observation_memory[i])!=1)return 3;
'''+f" reset(csrd_observation_memory,{INITIAL_STATE}u);\nuint32_t result={function}(({pointer}*)((unsigned char*)csrd_observation_memory+p),csrd_observation_memory+q,x);\n"+'''
 printf("%" PRIu32 "\\n",result);
 for(unsigned int i=0;i<64u;++i)printf("%" PRIu32 "\\n",csrd_observation_memory[i]);
 printf("%" PRIu32 " %u\\n",external_state,event_count);
 for(unsigned int i=0;i<event_count;++i){
  const struct event*e=events+i;
  printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 "\\n",e->kind,e->x,e->p,e->q,e->state);
  for(unsigned int j=0;j<64u;++j)printf("%" PRIu32 "\\n",e->memory[j]);
 }
 return 0;
}
'''
