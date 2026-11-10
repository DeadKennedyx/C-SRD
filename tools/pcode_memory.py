"""Ordered uint32 buffer reconstruction from binary-only high P-code.

The public signature supplies types, not memory footprints or algorithm facts.
Parameter-relative pointers remain symbolic, so emitted C retains all alias
relationships. Every load is snapshotted at its instruction position; stores
are never pruned just because the returned value does not depend on them.
"""
from dataclasses import dataclass
import re

from pcode_values import Builder, Unsupported, Value, literal
from pcode_cfg import LIMITS, index


@dataclass(frozen=True)
class Pointer:
    bits: int
    slot: int
    offset: int = 0  # byte offset modulo pointer width


def reconstruct(export, *, metrics=None, result_offset=0, store_offset=0, final_store_offset=0):
    try:
        return _reconstruct(export, {} if metrics is None else metrics, result_offset, store_offset, final_store_offset)
    except Unsupported:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise Unsupported(f"malformed memory P-code: {error}") from error


def _reconstruct(export, metrics, result_offset, store_offset, final_store_offset):
    if export.get("schema_version") != 4 or export.get("memory_model") != "ordered-u32-buffers-v1":
        raise Unsupported("requires ordered buffer export schema 4")
    name, arity, parameters = export["function"], export["arity"], export["parameters"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise Unsupported("invalid function symbol")
    if type(arity) is not int or not 1 <= arity <= 8 or len(parameters) != arity:
        raise Unsupported("invalid public buffer interface")
    for p in parameters:
        if p["kind"] not in ("uint32", "uint32-buffer") or type(p["read_only"]) is not bool:
            raise Unsupported("invalid parameter kind or constness")
        if p["kind"] == "uint32" and p["read_only"]:
            raise Unsupported("const scalar parameters are outside the contract")
    if not any(p["kind"] == "uint32-buffer" for p in parameters):
        raise Unsupported("buffer observer requires at least one pointer")
    space = export["address_space"]
    if type(space["pointer_bytes"]) is not int or space["pointer_bytes"] not in (4, 8) or space["addressable_unit_bytes"] != 1:
        raise Unsupported("requires byte-addressed 32/64-bit pointers")
    if type(space["id"]) is not int or not 0 <= space["id"] <= 0xffffffff:
        raise Unsupported("invalid memory space identifier")
    pointer_bits = space["pointer_bytes"] * 8
    nodes, ops, blocks = export["nodes"], export["operations"], export["blocks"]
    if not all(isinstance(v, list) for v in (nodes, ops, blocks)):
        raise Unsupported("invalid graph lists")
    if len(nodes) > LIMITS["nodes"] or len(ops) > LIMITS["operations"]:
        raise Unsupported("P-code budget exceeded")
    if len(blocks) != 1 or export.get("operation_order") != "basic-block-live-order":
        raise Unsupported("buffer observer currently requires one ordered basic block")
    block = blocks[0]
    if (type(block["id"]) is not int or export["entry_block"] != block["id"] or
            block["incoming"] or block["outgoing"] or block["operations"] != list(range(len(ops)))):
        raise Unsupported("inconsistent straight-line block membership")
    if not ops or ops[-1]["opcode"] != "RETURN" or any(o["opcode"] == "RETURN" for o in ops[:-1]):
        raise Unsupported("requires one final return")
    metrics.update(observer="ordered-u32-buffers-v1", evaluated_operations=0,
                   emitted_statements=0, loads=0, stores=0, pointer_operations=0,
                   footprint_elements={str(i): 0 for i, p in enumerate(parameters) if p["kind"] == "uint32-buffer"})
    builder, values, definitions = Builder(metrics), {}, set()
    for i, node in enumerate(nodes):
        size = node["size"]
        if type(size) is not int or size not in (1, 2, 4, 8):
            raise Unsupported("unsupported storage width")
        if "constant" in node:
            number = node["constant"]
            if ("parameter" in node or node.get("input") or not isinstance(number, str) or
                    not number.isascii() or not number.isdecimal() or len(number) > 20):
                raise Unsupported("invalid constant or input flags")
            values[i] = literal(size * 8, int(number))
        elif "parameter" in node:
            slot = index(node["parameter"], arity, "parameter")
            pointer = parameters[slot]["kind"] == "uint32-buffer"
            if node.get("input") is not True or size != (space["pointer_bytes"] if pointer else 4):
                raise Unsupported("parameter storage disagrees with public ABI")
            values[i] = Pointer(pointer_bits, slot) if pointer else Value(32, f"p{slot}")

    def read(i):
        if i not in values:
            raise Unsupported("unresolved input or definition used before its instruction")
        return values[i]

    def constant(value):
        if not isinstance(value, Value) or value.known is None:
            raise Unsupported("requires a constant pointer offset/stride")
        return value.known

    def address(pointer, write=False):
        if not isinstance(pointer, Pointer) or pointer.bits != pointer_bits:
            raise Unsupported("memory address is not derived from a public pointer")
        if pointer.offset % 4 or not 0 <= pointer.offset <= 60:
            raise Unsupported("unaligned or out-of-contract fixed memory offset")
        if write and parameters[pointer.slot]["read_only"]:
            raise Unsupported("store through a read-only public parameter")
        element = pointer.offset // 4
        footprint = metrics["footprint_elements"]
        footprint[str(pointer.slot)] = max(footprint[str(pointer.slot)], element + 1)
        return f"p{pointer.slot}[{element}]"

    result = None
    final_store = max((i for i, op in enumerate(ops) if op["opcode"] == "STORE"), default=-1) if final_store_offset else -1
    for oi, op in enumerate(ops):
        code, inputs = op["opcode"], op["inputs"]
        if op.get("block") != block["id"] or not isinstance(inputs, list):
            raise Unsupported("invalid instruction block or inputs")
        for i in inputs:
            index(i, len(nodes), "varnode")
        out = op.get("output")
        if out is not None:
            index(out, len(nodes), "varnode")
            if out in values or out in definitions or nodes[out].get("input"):
                raise Unsupported("multiple definitions or overwriting input/constant")
            definitions.add(out)
        if code in ("STORE", "RETURN"):
            if out is not None or len(inputs) != (3 if code == "STORE" else 2):
                raise Unsupported("invalid store/return interface")
        elif out is None:
            raise Unsupported("missing data instruction output")
        bits = nodes[out]["size"] * 8 if out is not None else None
        # Return input 0 is an instruction address, not a value computation.
        args = [read(i) for i in inputs[1:]] if code == "RETURN" else [read(i) for i in inputs]
        if code == "RETURN":
            result = args[0]
            if not isinstance(result, Value) or result.bits != 32:
                raise Unsupported("return must be uint32")
        elif code in ("LOAD", "STORE"):
            if len(args) != (2 if code == "LOAD" else 3) or constant(args[0]) != space["id"]:
                raise Unsupported("invalid load/store address space or arity")
            if code == "LOAD":
                if bits != 32:
                    raise Unsupported("only exact uint32 loads are supported")
                values[out] = builder.emit(32, address(args[1]))
                metrics["loads"] += 1
            else:
                value = args[2]
                if not isinstance(value, Value) or value.bits != 32:
                    raise Unsupported("only exact uint32 stores are supported")
                expression = value.atom
                # Legacy all-store mutation is retained for historical replay.
                # Mutating only the final store avoids cancellations across
                # earlier stores and guarantees an observable memory change.
                offset = store_offset + (final_store_offset if oi == final_store else 0)
                if offset:
                    expression = f"({expression} + {offset & 0xffffffff}u)"
                builder.lines.append(f"    {address(args[1], write=True)} = {expression};")
                metrics["stores"] += 1
        elif any(isinstance(a, Pointer) for a in args):
            metrics["pointer_operations"] += 1
            if bits != pointer_bits:
                raise Unsupported("pointer width changed or escaped to integer data")
            if code in ("COPY", "CAST") and len(args) == 1:
                values[out] = args[0]
                continue
            if code == "INT_ADD" and len(args) == 2 and isinstance(args[1], Pointer):
                args = [args[1], args[0]]
            if not isinstance(args[0], Pointer):
                raise Unsupported("unsupported pointer operation")
            base = args[0]
            if code == "PTRADD" and len(args) == 3:
                delta = constant(args[1]) * constant(args[2])
            elif code in ("PTRSUB", "INT_ADD", "INT_SUB") and len(args) == 2:
                delta = constant(args[1]) * (-1 if code == "INT_SUB" else 1)
                # PTRSUB denotes struct-field offset addition, not subtraction.
            else:
                raise Unsupported("unsupported pointer operation or arity")
            if any(a.bits != pointer_bits for a in args):
                raise Unsupported("pointer arithmetic width mismatch")
            values[out] = Pointer(pointer_bits, base.slot, (base.offset + delta) % (1 << pointer_bits))
        else:
            # Keep reconstructed C inside the buffer source verifier's arithmetic
            # contract. Shift-by-constant is exact uint32 scaling, including zero
            # for counts >=32 under P-code's total shift semantics.
            if code == "INT_LEFT" and len(args) == 2 and bits == args[0].bits == 32:
                count = constant(args[1])
                values[out] = builder.operation("INT_MULT", 32, [args[0], literal(32, (1 << count) if count < 32 else 0)])
            elif code == "INT_NEGATE" and len(args) == 1 and bits == args[0].bits == 32:
                values[out] = builder.operation("INT_SUB", 32, [literal(32, 0xffffffff), args[0]])
            elif code in ("COPY", "CAST", "INT_ADD", "INT_SUB", "INT_MULT", "INT_2COMP") and bits == 32:
                values[out] = builder.operation(code, bits, args)
            elif all(a.known is not None for a in args) and code in ("COPY", "CAST", "INT_ADD", "INT_SUB", "INT_MULT"):
                values[out] = builder.operation(code, bits, args)
            else:
                raise Unsupported(f"scalar operation outside buffer observer contract: {code}")
        if len(builder.lines) > LIMITS["emitted_statements"]:
            raise Unsupported("emitted statement budget exceeded")
    expression = result.atom
    if result_offset:
        expression = f"({expression} + {result_offset & 0xffffffff}u)"
    signature = ", ".join(("const " if p["read_only"] else "") + "unsigned int" +
                          (" *" if p["kind"] == "uint32-buffer" else " ") + f"p{i}"
                          for i, p in enumerate(parameters))
    lines = builder.lines + [f"    (void)p{i};" for i in range(arity)] + [f"    return {expression};"]
    source = f"unsigned int {name}({signature}) {{\n" + "\n".join(lines) + "\n}\n"
    if len(source.encode()) > LIMITS["generated_bytes"]:
        raise Unsupported("generated source budget exceeded")
    metrics.update(generated_bytes=len(source.encode()), emitted_statements=len(builder.lines))
    return source


def main():
    """One binary-only adapter attempt; grading runs in a separate process."""
    import argparse
    import json
    from pathlib import Path
    import resource
    import sys
    import time
    from audit_protection import file_hash, write_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "export_sha256": file_hash(args.export), "metrics": {}}
    try:
        data = json.loads(Path(args.export).read_text())
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            source = reconstruct(data, metrics=report["metrics"])
        finally:
            report["reconstruction_wall_seconds"] = time.perf_counter() - wall
            report["reconstruction_cpu_seconds"] = time.process_time() - cpu
        (root / "recovered.c").write_text(source)
        report.update(status="candidate", recovered_sha256=file_hash(root / "recovered.c"))
    except Unsupported as error:
        report.update(status="unsupported", reason=str(error))
    except Exception as error:
        report.update(status="error", reason=str(error))
    report["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    report["rss_scope"] = "whole adapter process high-water mark, including Python/imports; not per-reconstruction allocation"
    if file_hash(args.export) != report["export_sha256"]:
        report.update(status="error", reason="export changed during reconstruction")
    write_json(root / "adapter.json", report)
    return {"candidate": 0, "unsupported": 2, "error": 1}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
