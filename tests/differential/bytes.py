#!/usr/bin/env python3
"""Byte/word aliasing, signed bytes, captured indexes and embedded NULs."""
import argparse
from buffers import ROOT, CASES, run_fixture

NAMES = ("bytes_mix", "bytes_alias", "bytes_word", "bytes_view", "bytes_promotions", "bytes_signed", "bytes_string")
LAYOUTS = ((16,4), (17,4), (19,4), (13,4), (32,4), (0,48), (192,0))


def harness():
    declarations, checks = [], []
    for name in NAMES:
        byte_type = "const char" if name == "bytes_string" else "signed char" if name == "bytes_signed" else "unsigned char"
        declarations += [f"uint32_t {v}_{name}({byte_type}*,uint32_t*,uint32_t);" for v in ("original","candidate")]
        checks.append(f'''memcpy(a,initial,sizeof a);memcpy(b,initial,sizeof b);
        if(original_{name}(({byte_type}*)((unsigned char*)a+po),a+qo,x)!=
           candidate_{name}(({byte_type}*)((unsigned char*)b+po),b+qo,x) || memcmp(a,b,sizeof a)){{
          fprintf(stderr,"mismatch {name} layout=%u iteration=%u\\n",layout,iteration);return 1;}}''')
    offsets = ",".join(f"{{{p},{q}}}" for p,q in LAYOUTS)
    return f'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
{chr(10).join(declarations)}
static uint32_t state=0x43535244u;
static uint32_t next(void){{state^=state<<13;state^=state>>17;state^=state<<5;return state;}}
int main(void){{
 const uint32_t edges[]={{0u,1u,127u,128u,255u,256u,2147483648u,4294967294u,4294967295u}};
 const unsigned offsets[][2]={{{offsets}}};
 uint32_t initial[64],a[64],b[64];
 for(unsigned layout=0;layout<{len(LAYOUTS)};++layout)for(unsigned iteration=0;iteration<{CASES};++iteration){{
  uint32_t x=iteration<9?edges[iteration]:next();
  for(unsigned i=0;i<64;++i)initial[i]=iteration<9?edges[(i+iteration)%9]:next();
  unsigned po=offsets[layout][0],qo=offsets[layout][1];
  {chr(10).join(checks)}
 }}
 const char text[]="A\\0B\\xff\\x80";
 for(unsigned i=0;i<4;++i)if(original_bytes_string(text,0,i)!=candidate_bytes_string(text,0,i))return 1;
 puts("PASS byte/word memory, char interpretation, embedded NUL and offsets");return 0;
}}
'''


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csrd",required=True);parser.add_argument("--report",required=True);parser.add_argument("--output-dir")
    run_fixture(parser.parse_args(), ROOT/"tests/fixtures/bytes.c", NAMES, harness(), "buffers-byte-c11-v2",
                len(NAMES)*len(LAYOUTS)*CASES+4, {"byte_and_word_offsets":LAYOUTS,"storage_words":64})
