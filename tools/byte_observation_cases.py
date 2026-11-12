"""Withheld byte/word effect oracles and known intermediate tasks for the pilot."""
import random

MASK=0xffffffff
LAYOUTS=[(16,4),(17,4),(13,4),(32,4)]  # byte offset, word offset in shared storage
FUNCTIONS={"bytes_mix","bytes_alias","bytes_word","bytes_view","bytes_promotions","bytes_signed","bytes_string"}


def cases(protocol="basis-parity-v2"):
    if protocol!="basis-parity-v2": raise ValueError("byte corpus requires basis-parity-v2")
    rng=random.Random(20261112)
    result=[{"split":"training" if i<4 else "heldout","x":rng.getrandbits(32),
             "memory":[rng.getrandbits(32) for _ in range(64)]} for i in range(12)]
    result[1]["memory"]=list(result[0]["memory"]);result[1]["x"]=(result[0]["x"]+1)&MASK
    # Perturb every byte, not just each word's low byte. Otherwise targets at
    # offsets 1..3 can lack the odd difference needed by the affine fitter.
    result[2]["memory"]=[sum((((x>>(8*i))+1)&255)<<(8*i) for i in range(4))
                         for x in result[0]["memory"]]
    result[2]["x"]=result[0]["x"]
    for row,x in zip(result[8:],(0,1,0x80000000,MASK)):row["x"]=x
    return result


def expected(function,initial,p,q,x,*,plain_char_signed=True):
    memory=bytearray().join(word.to_bytes(4,"little") for word in initial)
    targets={}
    def word():return int.from_bytes(memory[4*q:4*q+4],"little")
    def signed(value):return value-256 if value>=128 else value
    if function=="bytes_mix":
        i=x&7;targets["sum"]=(memory[p+i]+x)&MASK;targets["scaled"]=(3*targets["sum"]+11)&MASK
        memory[p+i+1]=targets["scaled"]&255;result=targets["scaled"]+memory[p+i+1]
    elif function=="bytes_alias":
        targets["before"]=word();memory[p+(x&3)]=x&255;targets["after"]=word()
        result=targets["before"]+targets["after"]+memory[p]
    elif function=="bytes_word":
        targets["scaled"]=(7*x+19)&MASK;memory[4*q:4*q+4]=targets["scaled"].to_bytes(4,"little")
        memory[p+(x&3)]=(x>>8)&255;result=word()
    elif function=="bytes_view":
        offset=x&3;x=(x+1)&MASK;targets["scaled"]=(5*x+13)&MASK
        memory[p+offset+1]=targets["scaled"]&255;result=memory[p]+memory[p+offset+1]
    elif function=="bytes_promotions":
        targets["sum"]=memory[p]+3*memory[p+1]+(memory[p+2]<<8);result=targets["sum"]+x
    elif function=="bytes_signed":
        targets["before"]=signed(memory[p])&MASK;memory[p+1]=x&255
        result=targets["before"]+signed(memory[p+1])
    elif function=="bytes_string":
        interpret=signed if plain_char_signed else lambda value:value
        targets["a"]=interpret(memory[p+(x&3)])&MASK;targets["b"]=interpret(memory[p+4])&MASK
        result=3*targets["a"]+targets["b"]+11
    else:raise ValueError("unknown byte observation function")
    return {"return_value":result&MASK,"final_memory":[int.from_bytes(memory[i:i+4],"little") for i in range(0,256,4)],"targets":targets}


def signature(function,parameters):
    kind="char-buffer" if function=="bytes_string" else "signed-char-buffer" if function=="bytes_signed" else "unsigned-char-buffer"
    if function not in FUNCTIONS or [p["kind"] for p in parameters]!=[kind,"uint32-buffer","uint32"]:
        raise ValueError("byte corpus requires its declared byte-pointer,word-pointer,uint32 ABI")
    byte_type={"char-buffer":"const char","signed-char-buffer":"signed char","unsigned-char-buffer":"unsigned char"}[kind]
    return byte_type,f"uint32_t {function}({byte_type}*,uint32_t*,uint32_t);"


def driver(function,parameters):
    byte_type,declaration=signature(function,parameters)
    return '''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
uint32_t csrd_observation_memory[64];
'''+declaration+'''
int main(void){
 unsigned int p,q;uint32_t x;
 if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3 || p>240u || q>60u)return 2;
 for(unsigned int i=0;i<64u;++i)if(scanf("%" SCNu32,&csrd_observation_memory[i])!=1)return 3;
'''+f"uint32_t result={function}(({byte_type}*)((unsigned char*)csrd_observation_memory+p),csrd_observation_memory+q,x);\n"+'''
 printf("%" PRIu32 "\\n",result);
 for(unsigned int i=0;i<64u;++i)printf("%" PRIu32 "\\n",csrd_observation_memory[i]);
 return 0;
}
'''
