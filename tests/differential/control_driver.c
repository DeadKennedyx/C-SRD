#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DECL(P) \
unsigned P##flow_mix(unsigned,unsigned); \
unsigned P##flow_scopes(unsigned,unsigned); \
unsigned P##flow_recursive(unsigned,unsigned); \
unsigned P##flow_buffer(unsigned*,unsigned,unsigned,int(*)(unsigned,unsigned*)); \
unsigned P##flow_heap(unsigned,unsigned); \
double P##flow_floating(double,unsigned); \
int P##flow_stream(FILE*,FILE*,unsigned); \
unsigned P##flow_line(void)
DECL(original_);
DECL(variant_);

static unsigned allocation_fail, allocations, frees, callbacks, trace;
void *csrd_test_malloc(size_t size)
{
    ++allocations;
    return allocation_fail ? 0 : malloc(size);
}
void csrd_test_free(void *value)
{
    ++frees;
    free(value);
}
static int step(unsigned value, unsigned *memory)
{
    trace = trace * 17u + value;
    ++callbacks;
    memory[0] ^= callbacks;
    return (value & 7u) == 5u;
}
struct stream_result {
    int result, error, eof, output_error, saved_errno;
    long position;
    size_t length;
    unsigned char bytes[128];
};
static struct stream_result stream_case(int candidate, unsigned seed, unsigned count, unsigned limit,
                                        int failure, const char *path)
{
    struct stream_result answer;
    memset(&answer, 0, sizeof(answer));
    FILE *input = tmpfile(), *output = tmpfile();
    if (!input || !output) exit(80);
    for (unsigned i = 0; i < count; ++i) if (fputc((int)((seed+i*13u)&255u), input)<0) exit(81);
    rewind(input);
    if (failure) {
        FILE *setup = fopen(path, "wb");
        if (!setup || fputs("fixture", setup)<0 || fclose(setup)) exit(82);
        if (failure == 1) { fclose(output); output=fopen(path,"rb"); }
        else { fclose(input); input=fopen(path,"wb"); }
        if (!input || !output) exit(83);
    }
    errno=0;
    answer.result = candidate ? variant_flow_stream(input,output,limit) : original_flow_stream(input,output,limit);
    answer.saved_errno=errno;
    answer.position=ftell(input);
    answer.error=ferror(input);answer.eof=feof(input);answer.output_error=ferror(output);
    if (fseek(output,0,SEEK_SET)) exit(84);
    answer.length=fread(answer.bytes,1,sizeof(answer.bytes),output);
    if (fclose(input) || fclose(output)) exit(85);
    return answer;
}
int main(int argc,char **argv)
{
    _Static_assert(sizeof(double)==8,"floating observation requires IEEE-size double");
    if(argc!=2)return 79;
    unsigned state=42u;
    for(unsigned sample=0;sample<2000;++sample) {
        state=state*1664525u+1013904223u;
        unsigned n=sample%80u;
        if(original_flow_mix(state,n)!=variant_flow_mix(state,n))return 1;
        if(original_flow_scopes(state,n)!=variant_flow_scopes(state,n))return 2;
        if(original_flow_recursive(n,state)!=variant_flow_recursive(n,state))return 3;
        unsigned left[66],right[66];
        for(unsigned i=0;i<66;++i)left[i]=right[i]=state+i;
        callbacks=trace=0;
        unsigned a=original_flow_buffer(left,n,state>>9,step), ac=callbacks, at=trace;
        callbacks=trace=0;
        unsigned b=variant_flow_buffer(right,n,state>>9,step);
        if(a!=b || ac!=callbacks || at!=trace || memcmp(left,right,sizeof(left)))return 4;
        for(allocation_fail=0;allocation_fail<2;++allocation_fail) {
            allocations=frees=0;
            a=original_flow_heap(n,state);ac=allocations;at=frees;
            allocations=frees=0;
            b=variant_flow_heap(n,state);
            if(a!=b || ac!=allocations || at!=frees)return 5;
        }
    }
    const uint64_t bits[]={0,UINT64_C(0x8000000000000000),UINT64_C(0x3ff0000000000000),UINT64_C(0xbff0000000000000),
        UINT64_C(0x7ff0000000000000),UINT64_C(0xfff0000000000000),UINT64_C(0x7ff8000000000042),1,
        UINT64_C(0x0010000000000000),UINT64_C(0x7fefffffffffffff)};
    for(unsigned i=0;i<sizeof(bits)/sizeof(bits[0]);++i)for(unsigned mode=0;mode<4;++mode) {
        double input,left,right;memcpy(&input,&bits[i],8);
        left=original_flow_floating(input,mode);right=variant_flow_floating(input,mode);
        if(memcmp(&left,&right,8))return 6;
    }
    if(original_flow_line()!=variant_flow_line())return 7;
    for(unsigned count=0;count<=64;count+=8)for(unsigned limit=0;limit<=80;limit+=10) {
        struct stream_result a=stream_case(0,37,count,limit,0,argv[1]);
        struct stream_result b=stream_case(1,37,count,limit,0,argv[1]);
        if(memcmp(&a,&b,sizeof(a)))return 8;
    }
    for(int failure=1;failure<=2;++failure) {
        struct stream_result a=stream_case(0,37,8,16,failure,argv[1]);
        struct stream_result b=stream_case(1,37,8,16,failure,argv[1]);
        if(memcmp(&a,&b,sizeof(a)))return 9;
    }
    puts("PASS 12000 integer/memory/callback/heap comparisons, 40 floating-bit comparisons, 83 stream cases and line preservation");
    return 0;
}
