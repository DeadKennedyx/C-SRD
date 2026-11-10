"""Independent, declared finite tasks for the seven benign buffer benchmarks.

These expected intermediates are supplied to the trace-fitting experiment;
learning an arbitrary algorithm or its intended intermediate meaning is outside
that experiment. Original source/representation constants are not fit inputs.
"""
import random

MASK = 0xffffffff
LAYOUTS = [(4, 4), (4, 5), (5, 4), (4, 20)]
FUNCTIONS = {"buffer_update", "buffer_mix", "buffer_store", "buffer_snapshot",
             "buffer_boundary", "buffer_unused", "buffer_const"}


def cases(protocol="basis-parity-v2"):
    rng = random.Random(20261110)
    result = []
    for i in range(12):
        memory = [rng.getrandbits(32) for _ in range(64)]
        x = rng.getrandbits(32) if i < 8 else (0, 1, 0x80000000, MASK)[i-8]
        result.append({"split": "training" if i < 4 else "heldout", "memory": memory, "x": x})
    if protocol == "seeded-v1":
        return result
    if protocol != "basis-parity-v2":
        raise ValueError("unknown runtime input protocol")
    # Four same-parity target labels cannot identify an invertible affine map
    # using an odd difference. A scalar perturbation and a memory perturbation
    # give every declared target an odd difference, without inspecting any
    # transformed trace or changing the heldout executions.
    result[1]["memory"] = list(result[0]["memory"])
    result[1]["x"] = (result[0]["x"] + 1) & MASK
    result[2]["memory"] = [(word + 1) & MASK for word in result[0]["memory"]]
    result[2]["x"] = result[0]["x"]
    return result


def expected(function, initial, p, q, x):
    memory, targets = list(initial), {}
    if function == "buffer_update":
        targets["sum"] = (memory[q] + x) & MASK
        targets["scaled"] = (3 * targets["sum"] + 11) & MASK
        memory[p+1] = targets["scaled"]
        result = memory[p] + targets["scaled"]
    elif function == "buffer_mix":
        targets["sum"] = (memory[p] + x) & MASK
        targets["scaled"] = (3 * targets["sum"] + 11) & MASK
        memory[p+1] = targets["scaled"]
        after = (memory[q] - memory[p+1]) & MASK
        memory[q+1] = (after + x) & MASK
        result = memory[p] + memory[q+1]
    elif function == "buffer_store":
        targets["first_store"] = (x + 1) & MASK
        memory[p] = targets["first_store"]
        targets["second_store"] = (7 * memory[p] - 3) & MASK
        memory[q] = targets["second_store"]
        result = 19
    elif function == "buffer_snapshot":
        before = memory[p]
        memory[q] = x
        targets["scaled_snapshot"] = (3 * before) & MASK
        result = targets["scaled_snapshot"] + memory[p]
    elif function == "buffer_boundary":
        targets["last_plus_x"] = (memory[p+15] + x) & MASK
        memory[q+15] = (-targets["last_plus_x"] - 1) & MASK
        result = memory[q+15] + memory[p+15]
    elif function == "buffer_unused":
        targets["scaled_x"] = (3*x) & MASK
        result = targets["scaled_x"] + 11
    elif function == "buffer_const":
        targets["before"] = (memory[p] + x) & MASK
        memory[q] = (targets["before"] * 17) & MASK
        result = targets["before"] + memory[p]
    else:
        raise ValueError("function has no declared independent observation oracle")
    return {"return_value": result & MASK, "final_memory": memory, "targets": targets}


def driver(function, parameters):
    if function not in FUNCTIONS or [p["kind"] for p in parameters] != ["uint32-buffer", "uint32-buffer", "uint32"]:
        raise ValueError("runtime corpus requires its declared pointer,pointer,uint32 interface")
    signature = ",".join(("const " if p["read_only"] else "") + "uint32_t" +
                         ("*" if p["kind"] == "uint32-buffer" else "") for p in parameters)
    return r'''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
uint32_t csrd_observation_memory[64];
''' + f"uint32_t {function}({signature});\n" + r'''
int main(void){
    unsigned int p,q; uint32_t x;
    if(scanf("%u %u %" SCNu32,&p,&q,&x)!=3 || p>48u || q>48u)return 2;
    for(unsigned int i=0;i<64u;++i)if(scanf("%" SCNu32,&csrd_observation_memory[i])!=1)return 3;
''' + f"    uint32_t result={function}(csrd_observation_memory+p,csrd_observation_memory+q,x);\n" + r'''
    printf("%" PRIu32 "\n",result);
    for(unsigned int i=0;i<64u;++i)printf("%" PRIu32 "\n",csrd_observation_memory[i]);
    return 0;
}
'''
