#!/usr/bin/env python3
"""Real binary streams, EOF/status state, deferred writes and host I/O failures."""
import argparse
import hashlib
import platform
import buffers

NAMES=('io_read_mix','io_write_mix','io_transfer','io_status','io_branch_stream','io_emit_pair')
CASES=16


def harness():
    declarations=[f'uint32_t {prefix}_{name}(FILE*,FILE*,uint32_t*,uint32_t);'
                  for name in NAMES for prefix in ('original','candidate')]
    pairs=','.join('{'+','.join(prefix+'_'+name for prefix in ('original','candidate'))+'}' for name in NAMES)
    return (buffers.ROOT/'tests/fixtures/stdio_execution.h').read_text()+'\n'+'\n'.join(declarations)+f'''
static uint32_t random_word(uint32_t*s){{*s^=*s<<13;*s^=*s>>17;*s^=*s<<5;return *s;}}
int main(void){{
 const io_operation pairs[][2]={{{pairs}}};
 const uint32_t edges[]={{0u,1u,2u,3u,2147483647u,2147483648u,2147483649u,4294967294u,4294967295u}};
 uint32_t state=0x43535244u, initial[64];unsigned comparisons=0;
#ifdef __linux__
 const unsigned scenarios=7;
#else
 const unsigned scenarios=4;
#endif
 for(unsigned iteration=0;iteration<{CASES};++iteration){{
  uint32_t x=iteration<9u?edges[iteration]:random_word(&state);
  for(unsigned i=0;i<64u;++i)initial[i]=iteration<9u?edges[(i+iteration)%9u]:random_word(&state);
  for(unsigned scenario=0;scenario<scenarios;++scenario)for(unsigned at_end=0;at_end<2u;++at_end){{
   for(unsigned function=0;function<{len(NAMES)}u;++function){{
    /* io_branch_stream can write either handle; a directory is input-only. */
    if(scenario==4u && function==4u)continue;
    struct io_snapshot original,candidate;
    if(!io_execute(pairs[function][0],initial,x,scenario,at_end,&original) ||
       !io_execute(pairs[function][1],initial,x,scenario,at_end,&candidate)){{
     fprintf(stderr,"stream harness setup/capture failed function=%u scenario=%u\\n",function,scenario);return 2;
    }}
    if(!io_equal(&original,&candidate)){{
     fprintf(stderr,"stream mismatch function=%u scenario=%u iteration=%u at_end=%u\\n",function,scenario,iteration,at_end);return 1;
    }}
    ++comparisons;
   }}
  }}
 }}
 printf("PASS %u real-stream return/memory/contents/position/flags/errno/flush/close comparisons\\n",comparisons);
 return 0;
}}
'''


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--csrd',required=True);p.add_argument('--report',required=True);p.add_argument('--output-dir')
    args=p.parse_args();contracts=buffers.ROOT/'tests/fixtures/stdio_calls.json';linux=platform.system()=='Linux'
    comparisons=CASES*2*((7*len(NAMES)-1) if linux else 4*len(NAMES))
    buffers.run_fixture(args,buffers.ROOT/'tests/fixtures/stdio_calls.c',NAMES,harness(),'ordered-stdio-c11-v1',comparisons,
        {'stream_scenarios':['empty','one-byte','three-bytes','eight-bytes']+(['directory-read-error','unbuffered-full-device','buffered-full-device'] if linux else []),
         'initial_eof_states':['clear','pre-read-to-EOF/error'],'storage_words':64,'iterations':CASES,
         'call_contracts_sha256':hashlib.sha256(contracts.read_bytes()).hexdigest(),
         'effects_checked':'returns, all user memory, both binary file contents/positions/EOF/error flags, errno, deferred flush and close status'},
        transform_flags=('--call-contracts',contracts))
