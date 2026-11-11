"""Independent scalar/effect oracle and public ABI for two benign region fixtures."""
import random

MASK = 2**32 - 1
FIXTURES = {"assignments": "private_regions.c", "declarations": "private_declarations.c"}
FUNCTIONS = {"region_pipeline": "p,u,s", "region_outputs": "p,u,u"}


def oracle(fixture, function, vector):
    """Finite test oracle, not a proof. mode varies the external callback behavior."""
    if fixture not in FIXTURES or function not in FUNCTIONS:
        raise ValueError("unknown fixture/function")
    x, arg, memory, mode = vector["x"], vector["arg"], vector["memory"][:], vector.get("mode", 0)
    if len(memory) != 3 or mode not in (0, 1, 2): raise ValueError("bad memory/callback mode")
    events, targets = [], {}
    def u(x): return x & MASK
    def event(value): events.append(value)
    def next_value(value):
        event(value)
        if mode == 0:
            memory[1] = u(memory[1] + value)
            return u(value + memory[1])
        if mode == 1:
            memory[1] = u(memory[1] ^ value)
            return u(3 * value + memory[1] + 1)
        memory[1] = u(memory[1] - value)
        return u((value >> 3) ^ memory[1])
    if function == "region_outputs":
        y = arg
        pending = 17 if fixture == "declarations" else u(17 + x)
        mix = u(17 + x)
        x = u(3 * mix + y)
        y = u(x - pending)
        event(x)
        if fixture == "declarations": memory[2] = u(x + 7)
        memory[0], memory[1] = y, pending
        targets.update(mix=mix, result_x=x, result_y=y)
        result = int(x == y)
    else:
        if not -1 <= arg <= 16: raise ValueError("oracle loop-count domain is -1..16")
        y = memory[0]
        summed = u(x + y)
        bias = u(3 * summed + 11)
        x = bias if fixture == "assignments" else u(bias - y)
        targets.update(sum=summed, initial_x=x)
        if fixture == "declarations": targets["initial_bias"] = bias
        event(x if fixture == "assignments" else summed)
        for iteration in range(max(0, arg)):
            y = next_value(x)
            summed_loop = u(x + y)
            if fixture == "assignments":
                x = u(5 * summed_loop - 7)
                memory[0] = x
            else:
                shadow = u(bias + 5 * y)
                local = u(shadow - y)
                bias = u(local + summed)
                event(shadow)
                memory[0] = u(shadow + 7)
                x = u(summed_loop + bias)
                targets.update({f"loop{iteration}.shadow": shadow, f"loop{iteration}.local": local,
                                f"loop{iteration}.bias": bias})
            event(y)
            targets.update({f"loop{iteration}.y": y, f"loop{iteration}.sum": summed_loop,
                            f"loop{iteration}.x": x})
        result = x
    return {"return_value": result, "final_memory": memory, "events": events, "targets": targets}


def vectors(function, count=128, seed=20261110, loop_count=None):
    rng = random.Random(seed)
    # x+17==0 is a rare, true return path in assignment region_outputs.
    edges = [0, 1, 2, 3, 0x7fffffff, 0x80000000, 0xfffffffe, MASK, MASK-16]
    result = []
    for i in range(count):
        x = edges[i] if i < len(edges) else rng.getrandbits(32)
        memory = [edges[(i+j+1) % len(edges)] if i < len(edges) else rng.getrandbits(32) for j in range(3)]
        arg = edges[(i+3) % len(edges)] if i < len(edges) else rng.getrandbits(32)
        if function == "region_pipeline": arg = loop_count if loop_count is not None else [-1, 0, 1, 2, 3, 7, 16][i % 7]
        result.append({"x": x, "arg": arg, "memory": memory, "mode": i % 3})
    return result


def input_text(vector):
    return " ".join(map(str, [vector["x"], vector["arg"], *vector["memory"], vector.get("mode", 0)])) + "\n"


def driver(function):
    if function not in FUNCTIONS: raise ValueError("unknown function")
    signature = "uint32_t region_pipeline(uint32_t*,uint32_t,int);" if function == "region_pipeline" else "int region_outputs(uint32_t*,uint32_t,uint32_t);"
    argument = "(int)arg" if function == "region_pipeline" else "(uint32_t)arg"
    return r'''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
''' + signature + r'''
uint32_t csrd_observation_memory[3], csrd_events[128], csrd_event_count, csrd_mode;
void record_event(uint32_t value){
    if(csrd_event_count>=128u)exit(70);
    csrd_events[csrd_event_count++]=value;
}
uint32_t next_value(uint32_t value){
    record_event(value);
    if(csrd_mode==0u){csrd_observation_memory[1]+=value;return value+csrd_observation_memory[1];}
    if(csrd_mode==1u){csrd_observation_memory[1]^=value;return 3u*value+csrd_observation_memory[1]+1u;}
    csrd_observation_memory[1]-=value;return (value>>3)^csrd_observation_memory[1];
}
int main(void){
    uint32_t x; int64_t arg;
    while(scanf("%" SCNu32 " %" SCNd64 " %" SCNu32 " %" SCNu32 " %" SCNu32 " %" SCNu32,
        &x,&arg,&csrd_observation_memory[0],&csrd_observation_memory[1],&csrd_observation_memory[2],&csrd_mode)==6){
        csrd_event_count=0u;
        uint32_t result=(uint32_t)''' + function + "(csrd_observation_memory,x," + argument + r''');
        printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32,result,
            csrd_observation_memory[0],csrd_observation_memory[1],csrd_observation_memory[2],csrd_event_count);
        for(uint32_t i=0;i<csrd_event_count;++i)printf(" %" PRIu32,csrd_events[i]);
        putchar('\n');
    }
    return 0;
}
'''


def parse_output(line):
    values = list(map(int, line.split()))
    if len(values) < 5 or len(values) != 5 + values[4]: raise ValueError("invalid effect output")
    return {"return_value": values[0], "final_memory": values[1:4], "events": values[5:]}


def effects(expected):
    return {k: expected[k] for k in ("return_value", "final_memory", "events")}
