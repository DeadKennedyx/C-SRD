"""GDB-side bounded observation of registers, stack and a declared caller buffer.

Executed only against the controlled three-word private-region harness. No anti-debugging
or observer interference; full snapshots remain evidence for later analysis.
"""
import collections
import json
import gzip
from pathlib import Path
import re
import shlex
import gdb


def collect(config):
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    gdb.execute("set disable-randomization off")
    gdb.execute("set print thread-events off")
    # Resolve PLT slots before target entry; dynamic-loader internals are not
    # part of this controlled application-observation protocol.
    gdb.execute("set environment LD_BIND_NOW 1")
    # Starting at main loads the shared library before resolving its symbol.
    gdb.execute("start < " + shlex.quote(config["input_file"]))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", config["function"]):
        raise ValueError("invalid function symbol")
    gdb.Breakpoint("*" + config["function"], temporary=True)
    gdb.execute("continue", to_string=True)
    architecture = gdb.selected_frame().architecture().name()
    if "aarch64" in architecture:
        registers = [f"x{i}" for i in range(31)]
        return_address = int(gdb.parse_and_eval("$x30"))
    elif "x86-64" in architecture:
        registers = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp",
                     "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
        sp = int(gdb.parse_and_eval("$sp"))
        return_address = int.from_bytes(gdb.selected_inferior().read_memory(sp, 8).tobytes(), "little")
    else:
        raise RuntimeError("observer requires AArch64 or x86-64")
    if "little endian" not in gdb.execute("show endian", to_string=True):
        raise RuntimeError("observer requires little-endian target")
    memory_address = int(gdb.parse_and_eval("(unsigned long)&csrd_observation_memory"))
    events_address = int(gdb.parse_and_eval("(unsigned long)&csrd_events"))
    entry_sp = int(gdb.parse_and_eval("$sp"))
    visits, samples, failures = collections.Counter(), [], 0
    for _ in range(config["step_limit"]):
        pc = int(gdb.parse_and_eval("$pc"))
        if pc == return_address: break
        # Stable symbol+offset survives independent shared-library ASLR. The
        # callback and target locations remain distinct. No source debug data
        # for the protected library is loaded.
        offset = gdb.execute("info symbol " + str(pc), to_string=True).split(" in section ")[0].strip()
        if offset.startswith("No symbol"):
            raise RuntimeError("instruction location cannot be normalized to a symbol")
        visit = visits[offset]; visits[offset] += 1
        full = {name: int(gdb.parse_and_eval("$" + name)) & ((1<<64)-1) for name in registers}
        values = {"reg:" + name: value & 0xffffffff for name,value in full.items()}
        if config.get("wide_values"): values.update({"reg64:"+name:value for name,value in full.items()})
        memory = gdb.selected_inferior().read_memory(memory_address, 3*4).tobytes()
        values.update({f"caller:{i}": int.from_bytes(memory[4*i:4*i+4], "little") for i in range(3)})
        try:
            sp = int(gdb.parse_and_eval("$sp"))
            stack = gdb.selected_inferior().read_memory(sp, 64).tobytes()
            values.update({f"stack+{i}": int.from_bytes(stack[i:i+4], "little") for i in range(0, 64, 4)})
            if config.get("wide_values"):
                values.update({f"stack64+{i}":int.from_bytes(stack[i:i+8],"little") for i in range(0,57,4)})
        except gdb.MemoryError:
            failures += 1
        samples.append({"offset": offset, "visit": visit, "values": values,
                        "stack_depth_bytes": entry_sp - sp})
        gdb.execute("stepi", to_string=True)
    complete = int(gdb.parse_and_eval("$pc")) == return_address
    result = {"status": "completed" if complete else "step-limit", "architecture": architecture,
              "samples": samples, "steps": len(samples), "stack_read_failures": failures,
              "max_observed_stack_depth_bytes": max((s["stack_depth_bytes"] for s in samples), default=0),
              "stack_depth_scope": "additional sampled stack depth from target entry, including callbacks; excludes caller frame and non-stack memory",
              "scope": "low32 general registers, 64 bytes at SP, all3 caller words before each instruction; no SIMD coverage"}
    if complete:
        memory = gdb.selected_inferior().read_memory(memory_address, 3*4).tobytes()
        result["final_memory"] = [int.from_bytes(memory[4*i:4*i+4], "little") for i in range(3)]
        count = int(gdb.parse_and_eval("csrd_event_count"))
        if not 0 <= count <= 128: raise RuntimeError("event buffer bounds")
        raw = gdb.selected_inferior().read_memory(events_address, count*4).tobytes()
        result["events"] = [int.from_bytes(raw[4*i:4*i+4], "little") for i in range(count)]
        result["return_value"] = int(gdb.parse_and_eval("$x0" if "aarch64" in architecture else "$rax")) & 0xffffffff
        gdb.execute("continue", to_string=True)
    if config.get("wide_values"):
        result["scope"]="low32 and full64 general registers, 4/8-byte views within 64 bytes at SP, all3 caller words; no SIMD/heap coverage"
    return result


def main(config_path):
    config = json.loads(Path(config_path).read_text())
    try:
        result = collect(config)
    except Exception as error:
        result = {"status": "error", "error": str(error)}
    with gzip.open(config["output"], "wt") as output:
        json.dump(result, output, separators=(",", ":"))
    gdb.execute("quit")
