"""GDB-side observation of a controlled pure-u32 kernel and its callees.

Only the binary interface and observation budget are supplied. No source debug
variables, reference implementation, known values or encoding seeds are read.
"""
import collections
import gzip
import json
from pathlib import Path
import re
import shlex
import gdb


def collect(config):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", config["function"]):
        raise ValueError("invalid target symbol")
    for setting in ("pagination off", "confirm off", "disable-randomization off", "print thread-events off"):
        gdb.execute("set "+setting)
    gdb.Breakpoint("*"+config["function"], temporary=True)
    gdb.execute("run < "+shlex.quote(config["input_file"]), to_string=True)
    architecture = gdb.selected_frame().architecture().name()
    if "little endian" not in gdb.execute("show endian", to_string=True):
        raise RuntimeError("little-endian target required")
    if "aarch64" in architecture:
        registers, vectors = [f"x{i}" for i in range(31)], [f"v{i}" for i in range(32)]
        result_register = "x0"
        return_address = int(gdb.parse_and_eval("$x30"))
    elif "x86-64" in architecture:
        registers = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", *[f"r{i}" for i in range(8, 16)]]
        vectors, result_register = [f"xmm{i}" for i in range(16)], "rax"
        sp = int(gdb.parse_and_eval("$sp"))
        return_address = int.from_bytes(gdb.selected_inferior().read_memory(sp, 8).tobytes(), "little")
    else:
        raise RuntimeError("AArch64 or x86-64 required")
    entry = int(gdb.parse_and_eval("$pc"))
    entry_sp = int(gdb.parse_and_eval("$sp"))
    visits, samples = collections.Counter(), []
    stack_failures, vector_failures = 0, 0
    vector_errors = {}
    for _ in range(config["step_limit"]):
        pc = int(gdb.parse_and_eval("$pc"))
        if pc == return_address:
            break
        offset = pc-entry
        visit = visits[offset]; visits[offset] += 1
        values = {"reg:"+name: int(gdb.parse_and_eval("$"+name)) & 0xffffffff for name in registers}
        for name in vectors:
            try:
                raw = bytes(gdb.parse_and_eval("$"+name).bytes)
                if len(raw) != 16:
                    raise RuntimeError("unexpected 128-bit register width")
                values.update({f"simd:{name}:{i//4}": int.from_bytes(raw[i:i+4], "little") for i in range(0, 16, 4)})
            except Exception as error:
                vector_failures += 1
                vector_errors.setdefault(name, str(error))
        sp = int(gdb.parse_and_eval("$sp"))
        try:
            raw = gdb.selected_inferior().read_memory(sp, 64).tobytes()
            values.update({f"stack+{i}": int.from_bytes(raw[i:i+4], "little") for i in range(0, 64, 4)})
        except gdb.MemoryError:
            stack_failures += 1
        symbol = gdb.execute("info symbol "+str(pc), to_string=True).split(" in section ")[0].strip()
        code_scope = ("target" if symbol == config["function"] or symbol.startswith(config["function"]+" +")
                      else "unknown" if symbol.startswith("No symbol") else "callee-or-other")
        samples.append({"offset": offset, "visit": visit, "values": values,
                        "code_scope": code_scope, "stack_depth_bytes": entry_sp-sp})
        gdb.execute("stepi", to_string=True)
    complete = int(gdb.parse_and_eval("$pc")) == return_address
    result = {"status": "completed" if complete else "step-limit", "architecture": architecture,
              "samples": samples, "steps": len(samples), "stack_read_failures": stack_failures,
              "vector_read_failures": vector_failures,
              "vector_failure_reasons": vector_errors,
              "max_observed_stack_depth_bytes": max((s["stack_depth_bytes"] for s in samples), default=0),
              "scope": "before each instruction: low32 general registers; 32-bit lanes of 128-bit SIMD registers; 64 bytes at SP; includes callees; excludes heap, unobserved stack, wider vectors and unrelated threads"}
    if complete:
        result["return_value"] = int(gdb.parse_and_eval("$"+result_register)) & 0xffffffff
    return result


def main(config_path):
    config = json.loads(Path(config_path).read_text())
    try:
        result = collect(config)
    except Exception as error:
        result = {"status": "error", "error": str(error)}
    with gzip.open(config["output"], "wt") as stream:
        json.dump(result, stream, separators=(",", ":"))
    gdb.execute("quit")
