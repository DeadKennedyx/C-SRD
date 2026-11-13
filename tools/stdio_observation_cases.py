"""Finite real-stream corpus and independent arithmetic/stream oracle.

The runtime protocol is Linux glibc: EOF=-1, feof returns 1 on end-of-file.
The harness checks those values instead of silently assuming a portable ABI.
Only successful temporary files and EOF are measured here; real device/directory
errors are exercised separately by the transformation differential matrix.
"""
import random

MASK=0xffffffff
FUNCTIONS={'io_read_mix','io_write_mix','io_transfer','io_status','io_branch_stream','io_emit_pair'}
LAYOUTS=[(4,0),(4,1)]  # caller word offset, initial EOF state (not two buffer bases).
STATE_WORDS=139
KINDS={'fgetc':1,'fputc':2,'fflush':3,'feof':4,'ferror':5,'clearerr':6}


def cases(protocol='basis-parity-v2'):
    if protocol!='basis-parity-v2':raise ValueError('stdio corpus requires basis-parity-v2')
    rng=random.Random(20261119);result=[]
    for split in ('training','heldout'):
        for i,x in enumerate([0,1,2,3,4,5,127,128,255,256,0x80000000,MASK]):
            memory=[rng.getrandbits(32) for _ in range(64)]
            memory[62]=(memory[62]&~3)|(i%4)
            result.append({'split':split,'x':x,'memory':memory})
    return result


def signature(function,params):
    if function not in FUNCTIONS or [p['kind'] for p in params]!=['file-stream','file-stream','uint32-buffer','uint32']:
        raise ValueError('stdio corpus requires its declared FILE/word/scalar ABI')
    return 'uint32_t',f'uint32_t {function}(FILE*,FILE*,uint32_t*,uint32_t);'


def expected(function,initial,p,q,x,**unused):
    if function not in FUNCTIONS or not 0<=p<64 or q not in (0,1):raise ValueError('invalid stdio fixture/input')
    memory=list(initial);length=(0,1,3,8)[initial[62]&3]
    contents=[[v&255 for v in initial[8:8+length]],[]]
    position=[length if q else 0,0];end=[1 if q else 0,0]
    events=[];targets={}
    def call(name,stream,arg=0):
        before=list(memory)
        if name=='fgetc':
            if end[stream] or position[stream]>=len(contents[stream]):end[stream]=1;answer=MASK
            else:answer=contents[stream][position[stream]];position[stream]+=1
        elif name=='fputc':
            answer=arg&255
            if position[stream]==len(contents[stream]):contents[stream].append(answer)
            else:contents[stream][position[stream]]=answer
            position[stream]+=1
        elif name=='feof':answer=end[stream]
        elif name=='clearerr':end[stream]=0;answer=0
        else:answer=0  # fflush success and no stream errors in this protocol.
        events.append([KINDS[name],stream,arg,answer,*before]);return answer
    if function=='io_read_mix':
        c=call('fgetc',0);targets={'c':c,'sum':None}
        if c>255:memory[p]=(call('ferror',0)+3*call('feof',0))&MASK;result=memory[p]+101
        else:total=(c+3*x+memory[p])&MASK;targets['sum']=total;memory[p]=total;result=total+7
    elif function=='io_write_mix':
        value=(3*x+memory[p]+11)&MASK;written=call('fputc',1,value&255)
        flushed=call('fflush',1);memory[p]=(value+7*written)&MASK;result=memory[p]+flushed
        targets={'value':value,'written':written}
    elif function=='io_transfer':
        count=(x&3)+1;total=memory[p];result=None
        for i in range(count):
            c=call('fgetc',0)
            if c>255:
                end_value=call('feof',0);error=call('ferror',0);memory[p]=total;result=total+3*end_value+5*error;break
            call('fputc',1,(c+3*x+i)&255);total=(3*total+c+1)&MASK
        if result is None:flushed=call('fflush',1);memory[p]=total;result=total+flushed
        targets={'count':count,'sum':total}
    elif function=='io_status':
        error=call('ferror',0);end_value=call('feof',0);call('clearerr',0)
        after_error=call('ferror',0);after_end=call('feof',0)
        total=(3*error+end_value+5*after_error+7*after_end+x)&MASK
        memory[p]=total;result=total+17;targets={'end':end_value,'sum':total}
    elif function=='io_branch_stream':
        written=call('fputc',1 if x&1 else 0,x&255);result=written+memory[p]+7*x
        targets={'written':written}
    else:
        value=(7*x+memory[p])&MASK;first=call('fputc',1,value&255);second=call('fputc',1,(value>>8)&255)
        memory[p]=(value+first)&MASK;result=memory[p]+3*second
        targets={'value':value,'first':first,'second':second}
    targets['public_return']=result&MASK
    state=[0] # errno, before the harness captures stream state.
    for i in range(2):state.extend([end[i],0,position[i],len(contents[i]),*contents[i],*([0]*(64-len(contents[i])))])
    state.extend([0,0]) # fclose results.
    assert len(state)==STATE_WORDS
    return {'return_value':result&MASK,'final_memory':memory,'stdio_state':state,'stdio_events':events,'targets':targets}


def driver(function,params):
    _,declaration=signature(function,params)
    return r'''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
uint32_t csrd_observation_memory[64],csrd_stream_observation[139];
FILE *csrd_input,*csrd_output;
/* The marker belongs to the harness, after target execution and state capture. */
__attribute__((noinline)) void csrd_snapshot_marker(void){__asm__ volatile("" ::: "memory");}
'''+declaration+r'''
int main(void){
 unsigned p,q;uint32_t x;
 if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3 || p>=64u || q>1u)return 2;
 for(unsigned i=0;i<64u;++i)if(scanf("%" SCNu32,&csrd_observation_memory[i])!=1)return 3;
 memset(csrd_stream_observation,0,sizeof csrd_stream_observation);
 csrd_input=tmpfile();csrd_output=tmpfile();
 if(!csrd_input || !csrd_output)return 4;
 /* Check the explicit Linux/glibc return-value assumptions of the oracle. */
 if((uint32_t)EOF!=UINT32_MAX || fgetc(csrd_input)!=EOF || feof(csrd_input)!=1)return 5;
 clearerr(csrd_input);
 const unsigned lengths[]={0u,1u,3u,8u};
 for(unsigned i=0;i<lengths[csrd_observation_memory[62]&3u];++i)
  if(fputc((int)(csrd_observation_memory[8u+i]&255u),csrd_input)==EOF)return 6;
 if(fseek(csrd_input,0,SEEK_SET))return 7;
 if(q)while(fgetc(csrd_input)!=EOF){}
 errno=0;
'''+f' uint32_t result={function}(csrd_input,csrd_output,csrd_observation_memory+p,x);\n'+r'''
 csrd_stream_observation[0]=(uint32_t)errno;
 FILE*files[]={csrd_input,csrd_output};unsigned j=1;
 for(unsigned i=0;i<2u;++i){
  csrd_stream_observation[j++]=(uint32_t)feof(files[i]);
  csrd_stream_observation[j++]=(uint32_t)ferror(files[i]);
  long position=ftell(files[i]);if(position<0 || position>64)return 8;
  csrd_stream_observation[j++]=(uint32_t)position;
  if(fseek(files[i],0,SEEK_SET))return 9;
  unsigned char bytes[64]={0};size_t size=fread(bytes,1,64,files[i]);
  if(size==64 || ferror(files[i]))return 10;
  csrd_stream_observation[j++]=(uint32_t)size;
  for(unsigned k=0;k<64u;++k)csrd_stream_observation[j++]=bytes[k];
 }
 csrd_stream_observation[j++]=(uint32_t)fclose(files[0]);
 csrd_stream_observation[j++]=(uint32_t)fclose(files[1]);
 csrd_snapshot_marker();
 printf("%" PRIu32 "\n",result);
 for(unsigned i=0;i<64u;++i)printf("%" PRIu32 "\n",csrd_observation_memory[i]);
 for(unsigned i=0;i<139u;++i)printf("%" PRIu32 "\n",csrd_stream_observation[i]);
 return 0;
}
'''


def cost_driver(function,params):
    _,declaration=signature(function,params)
    # Every fixture has its own streams. Preparation/closing are outside the
    # clock; real stdio calls and any target-requested flush remain inside it.
    return r'''#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <sys/resource.h>
'''+declaration+r'''
static uint32_t next(uint32_t*s){*s^=*s<<13;*s^=*s>>17;*s^=*s<<5;return *s;}
static double elapsed(struct timespec a,struct timespec b){return (double)(b.tv_sec-a.tv_sec)+(double)(b.tv_nsec-a.tv_nsec)*1e-9;}
int main(int argc,char**argv){
 if(argc!=3)return 2;
 unsigned long n=strtoul(argv[1],0,10);uint32_t state=(uint32_t)strtoul(argv[2],0,10);
 if(n>10000000ul)return 2;
 FILE *input=tmpfile(),*output=tmpfile();if(!input || !output)return 3;
 unsigned char bytes[4096];for(unsigned i=0;i<4096u;++i)bytes[i]=(unsigned char)i;
 for(unsigned long written=0;written<4*n;written+=4096)
  if(fwrite(bytes,1,sizeof bytes,input)!=sizeof bytes)return 4;
 if(fseek(input,0,SEEK_SET))return 5;
 uint32_t memory[64];for(unsigned i=0;i<64u;++i)memory[i]=next(&state);
 uint64_t checksum=0;struct timespec a,b,c,d;
 if(clock_gettime(CLOCK_MONOTONIC,&a)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&c))return 6;
 for(unsigned long i=0;i<n;++i){
  uint32_t x=next(&state);memory[4]=x;memory[5]=next(&state);
'''+f'  checksum+={function}(input,output,memory+4,x);\n'+r'''
 }
 if(clock_gettime(CLOCK_MONOTONIC,&b)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&d))return 6;
 for(unsigned i=0;i<64u;++i)checksum=(checksum*33u)^memory[i];
 if(ferror(input)||ferror(output))return 7;
 for(unsigned i=0;i<2u;++i){
  FILE*f=i?output:input;
  long position=ftell(f);if(position<0 || fseek(f,0,SEEK_SET))return 8;
  checksum=checksum*33u+(uint64_t)position;
  size_t count;while((count=fread(bytes,1,sizeof bytes,f))!=0)
   for(size_t j=0;j<count;++j)checksum=(checksum*33u)^bytes[j];
  if(ferror(f)||fclose(f))return 9;
 }
 struct rusage usage;if(getrusage(RUSAGE_SELF,&usage))return 10;
 printf("%.9f %.9f %lu %" PRIu64 "\n",elapsed(a,b),elapsed(c,d),(unsigned long)usage.ru_maxrss*1024ul,checksum);
 return 0;
}
'''
