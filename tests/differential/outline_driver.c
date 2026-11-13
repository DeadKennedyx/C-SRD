#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define DECLARE(prefix) \
uint32_t prefix##_outline_calculate(uint32_t, uint32_t); \
long long prefix##_outline_signed(int, short); \
unsigned char prefix##_outline_byte(unsigned char, unsigned char); \
unsigned prefix##_outline_select(unsigned, unsigned); \
int prefix##_outline_logical(int, int); \
unsigned prefix##_outline_buffer(unsigned char *, const unsigned char *, unsigned, unsigned, void (*)(unsigned)); \
unsigned prefix##_outline_shadow(unsigned, unsigned)
DECLARE(original);
DECLARE(variant);

static unsigned events[32], saved[32], event_count;
static void observe(unsigned value) { events[event_count++] = value; }
static int compare(uint32_t x, uint32_t y)
{
    if (original_outline_calculate(x,y) != variant_outline_calculate(x,y)) return 1;
    if (original_outline_byte((unsigned char)x,(unsigned char)y) != variant_outline_byte((unsigned char)x,(unsigned char)y)) return 2;
    if (original_outline_select(x,y) != variant_outline_select(x,y)) return 3;
    if (original_outline_shadow(x,y) != variant_outline_shadow(x,y)) return 4;
    unsigned char input[32], a[32], b[32];
    for (unsigned i = 0; i < 32; ++i) input[i] = (unsigned char)(x+i*y);
    memset(a,0xa5,sizeof a); memset(b,0xa5,sizeof b);
    unsigned count=y%33u;
    event_count=0;
    unsigned ar=original_outline_buffer(a,input,count,x,observe);
    if (event_count!=count) return 5;
    memcpy(saved,events,sizeof saved);
    event_count=0;
    unsigned br=variant_outline_buffer(b,input,count,x,observe);
    if (event_count!=count || ar!=br || memcmp(a,b,sizeof a) || memcmp(saved,events,count*sizeof *events)) return 6;
    return 0;
}
int main(void)
{
    const uint32_t edges[]={0,1,2,255,256,65535,65536,2147483647u,2147483648u,4294967295u};
    for (unsigned i=0;i<sizeof edges/sizeof *edges;++i)
        for (unsigned j=0;j<sizeof edges/sizeof *edges;++j)
            if (compare(edges[i],edges[j])) return 1;
    uint32_t x=42;
    for (unsigned i=0;i<4096;++i) {
        x=x*1664525u+1013904223u;
        if (compare(x,i*2654435761u)) return 2;
    }
    const int integers[]={INT_MIN,-65536,-1,0,1,65535,INT_MAX};
    const short shorts[]={SHRT_MIN,-1,0,1,SHRT_MAX};
    for (unsigned i=0;i<sizeof integers/sizeof *integers;++i)
        for (unsigned j=0;j<sizeof shorts/sizeof *shorts;++j)
            if (original_outline_signed(integers[i],shorts[j]) != variant_outline_signed(integers[i],shorts[j])) return 3;
    for (int a=-15;a<=15;++a) for (int b=-15;b<=15;++b)
        if (original_outline_logical(a,b)!=variant_outline_logical(a,b)) return 4;
    puts("PASS outlined values, buffer writes and callback traces");
    return 0;
}
