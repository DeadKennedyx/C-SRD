#!/usr/bin/env python3
"""Record/member aliases and repeated persistent-state executions in real C."""
import argparse
from buffers import run_fixture, ROOT, CASES

NAMES=("records_pair","records_alias","records_index","records_union","records_counter","records_state","records_mode")
GLOBALS=("csrd_counter","csrd_state","csrd_mode")


def harness():
    header=(ROOT/"tests/fixtures/records.h").read_text()
    decls=[];checks=[]
    for prefix in ("original","candidate"):
        decls += [f"extern uint32_t {prefix}_csrd_counter;",
                  f"extern struct csrd_pair {prefix}_csrd_state;",
                  f"extern union csrd_word {prefix}_csrd_mode;"]
    for name in NAMES:
        union=name in ("records_union","records_mode")
        t="union csrd_word" if union else "struct csrd_pair"
        a,b=("a.words","b.words") if union else ("a.pairs","b.pairs")
        decls += [f"uint32_t {prefix}_{name}({t}*,uint32_t*,uint32_t);" for prefix in ("original","candidate")]
        q1,q2=("&a.words[qo].value","&b.words[qo].value") if union else ("(qo&1u ? &a.pairs[qo/2].second : &a.pairs[qo/2].first)","(qo&1u ? &b.pairs[qo/2].second : &b.pairs[qo/2].first)")
        init="for(unsigned k=0;k<64;k++)a.words[k].value=b.words[k].value=initial[k];" if union else "for(unsigned k=0;k<32;k++){a.pairs[k].first=b.pairs[k].first=initial[2*k];a.pairs[k].second=b.pairs[k].second=initial[2*k+1];}"
        # True typed aliases include same/different member, separate array and
        # pointers directly into persistent storage. No uint32-array punning.
        p1=f"{a}+po";p2=f"{b}+po"
        if name in ("records_state","records_mode"):
            g="csrd_mode" if union else "csrd_state"
            p1=f"(layout==4 ? &original_{g} : {p1})";p2=f"(layout==4 ? &candidate_{g} : {p2})"
        if name=="records_counter":
            q1=f"(layout==4 ? &original_csrd_counter : {q1})";q2=f"(layout==4 ? &candidate_csrd_counter : {q2})"
        if name=="records_state":
            q1=f"(layout==5 ? &original_csrd_state.first : {q1})";q2=f"(layout==5 ? &candidate_csrd_state.first : {q2})"
        if name=="records_mode":
            q1=f"(layout==5 ? &original_csrd_mode.value : {q1})";q2=f"(layout==5 ? &candidate_csrd_mode.value : {q2})"
        checks.append(f'''{{
 {init}
 original_csrd_counter=candidate_csrd_counter=initial[61];
 original_csrd_state.first=candidate_csrd_state.first=initial[62];
 original_csrd_state.second=candidate_csrd_state.second=initial[63];
 original_csrd_mode.value=candidate_csrd_mode.value=initial[60];
 for(unsigned repetition=0;repetition<3;repetition++){{
  uint32_t r=original_{name}({p1},{q1},x+repetition);
  uint32_t s=candidate_{name}({p2},{q2},x+repetition);
  if(r!=s || memcmp(&a,&b,sizeof a) || original_csrd_counter!=candidate_csrd_counter ||
     memcmp(&original_csrd_state,&candidate_csrd_state,sizeof original_csrd_state) ||
     original_csrd_mode.value!=candidate_csrd_mode.value){{
    fprintf(stderr,"record mismatch {name} layout=%u iteration=%u repetition=%u\\n",layout,iteration,repetition);return 1;
  }}
 }}
}}''')
    return header+'''\n#include <stdio.h>
#include <string.h>
_Static_assert(sizeof(struct csrd_pair)==8 && sizeof(union csrd_word)==4,"fixture layout");
union storage {struct csrd_pair pairs[32];union csrd_word words[64];};
'''+"\n".join(decls)+f'''
static uint32_t rng=0x43535244u;
static uint32_t next(void){{rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}}
int main(void){{
 uint32_t initial[64];union storage a,b;
 const uint32_t edges[]={{0u,1u,2u,3u,2147483647u,2147483648u,2147483649u,4294967294u,4294967295u}};
 for(unsigned layout=0;layout<6;layout++)for(unsigned iteration=0;iteration<{CASES};iteration++){{
  uint32_t x=iteration<9 ? edges[iteration] : next();
  for(unsigned k=0;k<64;k++)initial[k]=iteration<9 ? edges[(k+iteration)%9] : next();
  unsigned po=2,qo=layout==0 ? 4 : layout==1 ? 5 : layout==2 ? 6 : 20;
  {chr(10).join(checks)}
 }}
 puts("PASS return, entire typed storage and repeated persistent state");return 0;
}}
'''


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--csrd",required=True);p.add_argument("--report",required=True);p.add_argument("--output-dir")
    args=p.parse_args()
    run_fixture(args,ROOT/"tests/fixtures/records.c",NAMES,harness(),"records-state-byte-c11-v1",
                len(NAMES)*6*CASES*3,{"typed_alias_layouts":6,"consecutive_calls":3,"storage_bytes":256},rename_symbols=GLOBALS)
