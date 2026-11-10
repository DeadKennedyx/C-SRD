"""Executed inside GDB's Python interpreter by observe_runtime.py."""
import collections
import json
import shlex
from pathlib import Path
import gdb


def collect(config):
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    gdb.execute("set disable-randomization off")
    gdb.execute("set print thread-events off")
    gdb.Breakpoint("*" + config["function"])
    gdb.execute("run < " + shlex.quote(config["input_file"]))
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
        raise RuntimeError("observer supports only AArch64 and x86-64")
    if "little endian" not in gdb.execute("show endian", to_string=True):
        raise RuntimeError("observer requires little-endian target")
    entry = int(gdb.parse_and_eval("$pc"))
    visits, samples, stack_failures = collections.Counter(), [], 0
    finished = False
    for _ in range(config["step_limit"]):
        pc = int(gdb.parse_and_eval("$pc"))
        if pc == return_address:
            finished = True
            break
        offset = pc - entry
        visit = visits[offset]
        visits[offset] += 1
        values = {"reg:" + name: int(gdb.parse_and_eval("$" + name)) & 0xffffffff for name in registers}
        try:
            sp = int(gdb.parse_and_eval("$sp"))
            memory = gdb.selected_inferior().read_memory(sp, 64).tobytes()
            values.update({f"stack+{i}": int.from_bytes(memory[i:i+4], "little") for i in range(0, 64, 4)})
        except gdb.MemoryError:
            stack_failures += 1
        samples.append({"offset": offset, "visit": visit, "values": values})
        gdb.execute("stepi", to_string=True)
    return {"status": "completed" if finished else "step-limit", "architecture": architecture,
            "samples": samples, "steps": len(samples), "stack_read_failures": stack_failures,
            "scope": "lower 32 bits of general registers and 64 bytes at SP before each instruction; excludes SIMD/heap"}


def main(config_path):
    config = json.loads(Path(config_path).read_text())
    result = {"status": "failed"}
    try:
        result = collect(config)
    except Exception as error:
        result["error"] = str(error)
    Path(config["output"]).write_text(json.dumps(result, indent=2) + "\n")
    gdb.execute("quit")
