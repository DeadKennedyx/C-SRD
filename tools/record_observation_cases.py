"""Independent record/global effects; C harnesses use genuine typed objects."""
from pathlib import Path
from byte_observation_cases import cases, MASK

ROOT=Path(__file__).resolve().parents[1]
HEADER=ROOT/"tests/fixtures/records.h"
FUNCTIONS={"records_pair","records_alias","records_index","records_union","records_counter","records_state","records_mode"}
# Last layout selects global aliases for stateful fixtures, another caller
# location for other fixtures. p is a byte offset; q is a word offset.
LAYOUTS=[(16,4),(16,5),(16,20),(256,64)]
GLOBALS={"csrd_counter":4,"csrd_state":8,"csrd_mode":4}


def signature(function,parameters):
    if function not in FUNCTIONS or [p["kind"] for p in parameters]!=["record-buffer","uint32-buffer","uint32"]:
        raise ValueError("record corpus requires declared three-parameter ABI")
    union=function in ("records_union","records_mode")
    tag="csrd_word" if union else "csrd_pair"
    if parameters[0]["record"]["tag"]!=tag or parameters[0]["record"]["union"]!=union:
        raise ValueError("record corpus layout mismatch")
    ctype=("union " if union else "struct ")+tag
    return ctype,f"uint32_t {function}({ctype}*,uint32_t*,uint32_t);"


def expected(function,initial,p,q,x,**unused):
    memory=bytearray().join(word.to_bytes(4,"little") for word in [*initial,initial[61],initial[62],initial[63],initial[60]])
    if p==256:
        p={"records_state":260,"records_mode":268}.get(function,32)
        q={"records_counter":256,"records_state":260,"records_mode":268}.get(function,32)
    else:q*=4
    def word(at):return int.from_bytes(memory[at:at+4],"little")
    def put(at,value):memory[at:at+4]=(value&MASK).to_bytes(4,"little")
    targets={}
    if function=="records_pair":
        before=(word(p)+x)&MASK;stored=(3*before+11)&MASK;put(p+4,stored);put(q,word(p+4)+x)
        result=word(p)+word(p+4);targets.update(before=before,stored=stored)
    elif function=="records_alias":
        before=(word(q)+x)&MASK;put(p,5*before+7);put(q,word(q)+3);stored=(word(p)+word(q))&MASK;put(p+4,stored)
        result=word(p+4)-before;targets.update(before=before,stored=stored)
    elif function=="records_index":
        view=p+(x&1)*8;x=(x+1)&MASK;total=(word(view)+x)&MASK;stored=(7*total+19)&MASK
        put(view+4,stored);put(q,word(view+4));result=word(p+(x&1)*8)+total;targets.update(total=total,stored=stored)
    elif function=="records_union":
        before=(word(p)+x)&MASK;stored=(3*before+5)&MASK;put(p,stored);put(q,word(p)+1)
        result=word(p)+before;targets.update(before=before,stored=stored)
    elif function=="records_counter":
        before=(word(256)+x)&MASK;stored=(3*before+11)&MASK;put(256,stored);put(q,word(256))
        result=word(256)+word(p);targets.update(before=before,stored=stored)
    elif function=="records_state":
        before=(word(260)+x)&MASK;stored=(5*before+7)&MASK;put(264,stored);put(q,word(264));put(p,word(260)+word(q))
        result=word(p)+word(264);targets.update(before=before,stored=stored)
    elif function=="records_mode":
        before=(word(268)+x)&MASK;stored=(7*before+19)&MASK;put(268,stored);put(q,word(268));put(p,word(q)+x)
        result=word(p)+word(268);targets.update(before=before,stored=stored)
    else:raise ValueError("unknown record fixture")
    return {"return_value":result&MASK,"final_memory":[word(i) for i in range(0,256,4)],
            "persistent_state":[word(i) for i in range(256,272,4)],"targets":targets}


def storage(function):
    union=function in ("records_union","records_mode")
    definition=("union csrd_word csrd_observation_memory[64];" if union else "struct csrd_pair csrd_observation_memory[32];")
    cell="csrd_observation_memory[i].value" if union else "*(i&1u ? &csrd_observation_memory[i/2].second : &csrd_observation_memory[i/2].first)"
    q="&csrd_observation_memory[q].value" if union else "(q&1u ? &csrd_observation_memory[q/2].second : &csrd_observation_memory[q/2].first)"
    pointer="csrd_observation_memory+p/"+("4" if union else "8")
    return definition,cell,pointer,q


def driver(function,parameters):
    ctype,declaration=signature(function,parameters)
    definition,cell,pointer,qptr=storage(function)
    if function=="records_state":pointer="(global_alias ? &csrd_state : "+pointer+")";qptr="(global_alias ? &csrd_state.first : "+qptr+")"
    if function=="records_mode":pointer="(global_alias ? &csrd_mode : "+pointer+")";qptr="(global_alias ? &csrd_mode.value : "+qptr+")"
    if function=="records_counter":qptr="(global_alias ? &csrd_counter : "+qptr+")"
    return HEADER.read_text()+'''
#include <inttypes.h>
#include <stdio.h>
'''+definition+"\n"+declaration+'''
int main(void){
 unsigned p,q;uint32_t x,initial[64];
 if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3)return 2;
 unsigned global_alias=p==256u && q==64u;
 if(global_alias){p=32u;q=8u;}
 if(p>224u || p%8u || q>63u)return 2;
 (void)global_alias;
 for(unsigned i=0;i<64;i++){
  if(scanf("%" SCNu32,&initial[i])!=1)return 3;
'''+f"  {cell}=initial[i];\n"+'''
 }
 csrd_counter=initial[61];csrd_state.first=initial[62];csrd_state.second=initial[63];csrd_mode.value=initial[60];
'''+f" uint32_t result={function}({pointer},{qptr},x);\n"+'''
 printf("%" PRIu32 "\\n",result);
'''+f' for(unsigned i=0;i<64;i++)printf("%" PRIu32 "\\n",{cell});\n'+'''
 printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 "\\n",csrd_counter,csrd_state.first,csrd_state.second,csrd_mode.value);
 return 0;
}
'''


def cost_driver(function,parameters):
    _,declaration=signature(function,parameters)
    definition,cell,pointer,qptr=storage(function)
    return '''#define _POSIX_C_SOURCE 200809L
'''+HEADER.read_text()+'''
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <sys/resource.h>
'''+definition+"\n"+declaration+'''
static uint32_t next(uint32_t*s){*s^=*s<<13;*s^=*s>>17;*s^=*s<<5;return *s;}
static double elapsed(struct timespec a,struct timespec b){return (double)(b.tv_sec-a.tv_sec)+(double)(b.tv_nsec-a.tv_nsec)*1e-9;}
int main(int argc,char**argv){
 if(argc!=3)return 2;
 unsigned long n=strtoul(argv[1],0,10);uint32_t state=(uint32_t)strtoul(argv[2],0,10);
'''+f" for(unsigned i=0;i<64;i++){cell}=next(&state);\n"+'''
 csrd_counter=next(&state);csrd_state.first=next(&state);csrd_state.second=next(&state);csrd_mode.value=next(&state);
 uint64_t checksum=0;struct timespec a,b,c,d;
 if(clock_gettime(CLOCK_MONOTONIC,&a)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&c))return 3;
 for(unsigned long iteration=0;iteration<n;iteration++){
  uint32_t x=next(&state);unsigned p=16u+8u*(iteration&1u),q=4u;
'''+f"  for(unsigned i=4;i<6;i++){cell}=next(&state);\n  checksum+={function}({pointer},{qptr},x);\n"+'''
 }
 if(clock_gettime(CLOCK_MONOTONIC,&b)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&d))return 3;
 checksum+=csrd_counter;checksum+=csrd_state.first;checksum+=csrd_state.second;checksum+=csrd_mode.value;
'''+f" for(unsigned i=0;i<64;i++)checksum=(checksum*33u)^{cell};\n"+'''
 struct rusage usage;if(getrusage(RUSAGE_SELF,&usage))return 3;
 printf("%.9f %.9f %lu %" PRIu64 "\\n",elapsed(a,b),elapsed(c,d),(unsigned long)usage.ru_maxrss*1024ul,checksum);
 return 0;
}
'''
