"""GDB-side bounded observation of registers, stack and a declared caller buffer.

Executed only against the controlled buffer_update harness. No anti-debugging
or observer interference; full snapshots remain evidence for later analysis.
"""
import collections
import json
from pathlib import Path
import re
import shlex
import gdb


def collect(config):
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    gdb.execute("set disable-randomization off")
    gdb.execute("set print thread-events off")
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
    globals_=[]
    for name,size in config.get("persistent_objects",{}).items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*",name) or size not in (4,8):raise ValueError("invalid persistent observation extent")
        globals_.append((name,int(gdb.parse_and_eval("(unsigned long)&"+name)),size))
    def global_words():
        words={}
        for name,at,size in globals_:
            raw=gdb.selected_inferior().read_memory(at,size).tobytes()
            words.update({f"global:{name}:{i//4}":int.from_bytes(raw[i:i+4],"little") for i in range(0,size,4)})
        return words
    entry = int(gdb.parse_and_eval("$pc"))
    call_scope = config.get("call_scope",False)
    function_bytes = config.get("function_bytes",0)
    if call_scope and (type(function_bytes) is not int or function_bytes<1):raise ValueError("missing function extent")
    tail_transfers=0
    visits, samples, failures = collections.Counter(), [], 0
    for _ in range(config["step_limit"]):
        pc = int(gdb.parse_and_eval("$pc"))
        if pc == return_address: break
        if call_scope and not entry<=pc<entry+function_bytes:
            # A tail transfer leaves the caller permanently under this corpus's
            # no-reentry contract. Do not mix ASLR-dependent external PCs into
            # the caller's location-fitting task.
            gdb.Breakpoint("*"+str(return_address),temporary=True)
            gdb.execute("continue",to_string=True);tail_transfers+=1;break
        offset = pc - entry; visit = visits[offset]; visits[offset] += 1
        values = {"reg:" + name: int(gdb.parse_and_eval("$" + name)) & 0xffffffff for name in registers}
        memory = gdb.selected_inferior().read_memory(memory_address, 64*4).tobytes()
        values.update({f"caller:{i}": int.from_bytes(memory[4*i:4*i+4], "little") for i in range(64)})
        values.update(global_words())
        if config.get("sample_bytes"):
            values.update({f"caller-byte:{i}":value for i,value in enumerate(memory)})
        try:
            sp = int(gdb.parse_and_eval("$sp"))
            stack = gdb.selected_inferior().read_memory(sp, 64).tobytes()
            values.update({f"stack+{i}": int.from_bytes(stack[i:i+4], "little") for i in range(0, 64, 4)})
        except gdb.MemoryError:
            failures += 1
        samples.append({"offset": offset, "visit": visit, "values": values})
        gdb.execute("nexti" if call_scope else "stepi", to_string=True)
    complete = int(gdb.parse_and_eval("$pc")) == return_address
    result = {"status": "completed" if complete else "step-limit", "architecture": architecture,
              "samples": samples, "steps": len(samples), "stack_read_failures": failures,
              "scope": "low32 general registers, 64 bytes at SP, all64 caller words before each instruction; no SIMD coverage" +
                       ("; all256 caller bytes also sampled" if config.get("sample_bytes") else "")}
    if call_scope:
        result.update(tail_transfers_skipped=tail_transfers,
                      call_observation_scope="caller instructions only; nexti steps over callees; tail transfers run to caller return; callee interiors unmeasured")
    if complete:
        memory = gdb.selected_inferior().read_memory(memory_address, 64*4).tobytes()
        result["final_memory"] = [int.from_bytes(memory[4*i:4*i+4], "little") for i in range(64)]
        result["return_value"] = int(gdb.parse_and_eval("$x0" if "aarch64" in architecture else "$rax")) & 0xffffffff
        if globals_:
            result["persistent_state"]=list(global_words().values())
            result["scope"]+="; declared persistent globals sampled before every instruction and at return"
        if call_scope:
            def word_symbol(name):
                at=int(gdb.parse_and_eval("(unsigned long)&"+name))
                return int.from_bytes(gdb.selected_inferior().read_memory(at,4).tobytes(),"little")
            count=word_symbol("event_count")
            if count>8:raise ValueError("call event budget exceeded")
            at=int(gdb.parse_and_eval("(unsigned long)&events"))
            raw=gdb.selected_inferior().read_memory(at,count*69*4).tobytes() if count else b""
            result["external_state"]=word_symbol("external_state")
            result["events"]=[[int.from_bytes(raw[(i*69+j)*4:(i*69+j+1)*4],"little") for j in range(69)] for i in range(count)]
        gdb.execute("continue", to_string=True)
    return result


def main(config_path):
    config = json.loads(Path(config_path).read_text())
    try:
        result = collect(config)
    except Exception as error:
        result = {"status": "error", "error": str(error)}
    Path(config["output"]).write_text(json.dumps(result, indent=2) + "\n")
    gdb.execute("quit")
