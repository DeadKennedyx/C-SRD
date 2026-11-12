#!/usr/bin/env python3
"""Compare return, full memory, state and ordered call events across C compilers."""
import argparse
import hashlib
from pathlib import Path

from buffers import run_fixture, ROOT, CASES, LAYOUTS

NAMES = ("calls_scalar", "calls_buffer", "calls_sequence", "calls_view", "calls_discard", "calls_tail", "calls_bytes")


def harness():
    declarations, checks = [], []
    for name in NAMES:
        pointer = "unsigned char" if name == "calls_bytes" else "uint32_t"
        declarations += [f"uint32_t {prefix}_{name}({pointer}*,uint32_t*,uint32_t);" for prefix in ("original", "candidate")]
        checks.append(f'''memcpy(a,initial,sizeof a);memcpy(b,initial,sizeof b);
        reset(a,seed);
        uint32_t r_{name}=original_{name}(({pointer}*)(a+po),a+qo,x);
        uint32_t s_{name}=external_state;unsigned n_{name}=event_count;
        memcpy(saved,events,sizeof events);
        reset(b,seed);
        if(r_{name}!=candidate_{name}(({pointer}*)(b+po),b+qo,x) || memcmp(a,b,sizeof a) ||
           s_{name}!=external_state || n_{name}!=event_count || memcmp(saved,events,sizeof events)) {{
            fprintf(stderr,"call mismatch {name} layout=%u iteration=%u\\n",layout,iteration);return 1;
        }}''')
    offsets = ",".join(f"{{{p},{q}}}" for p,q in LAYOUTS)
    return r'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
''' + (ROOT/"tests/fixtures/call_environment.h").read_text()+"\nstatic struct event saved[8];\n"+"\n".join(declarations) + f'''
int main(void) {{
 const uint32_t edges[]={{0u,1u,2u,3u,2147483647u,2147483648u,2147483649u,4294967294u,4294967295u}};
 const unsigned offsets[][2]={{{offsets}}};
 uint32_t initial[64],a[64],b[64],rng=0x43535244u;
 for(unsigned layout=0;layout<{len(LAYOUTS)};layout++)for(unsigned iteration=0;iteration<{CASES};iteration++){{
  rng=step(rng);uint32_t x=iteration<9 ? edges[iteration] : rng;
  rng=step(rng);uint32_t seed=rng;
  for(unsigned i=0;i<64;i++){{rng=step(rng);initial[i]=iteration<9 ? edges[(i+iteration)%9] : rng;}}
  unsigned po=offsets[layout][0],qo=offsets[layout][1];
  {chr(10).join(checks)}
 }}
 puts("PASS returns, entire memory, external state and ordered calls");return 0;
}}
'''


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--csrd",required=True)
    p.add_argument("--report",required=True);p.add_argument("--output-dir");args=p.parse_args()
    contracts=ROOT/"tests/fixtures/calls.json"
    run_fixture(args,ROOT/"tests/fixtures/calls.c",NAMES,harness(),"ordered-calls-byte-c11-v1",
                len(NAMES)*len(LAYOUTS)*CASES,
                {"pointer_offsets":LAYOUTS,"storage_words":64,"call_contracts_sha256":hashlib.sha256(contracts.read_bytes()).hexdigest(),
                 "effects_checked":"ordered callees, argument values, pre-call memory, final memory, external state and return"},
                transform_flags=("--call-contracts",contracts))
