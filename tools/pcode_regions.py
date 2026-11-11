"""Effect-ordered, cyclic high-P-code reconstruction for a declared public ABI.

This observer emits runnable C, not a proof. It does not consume reference source,
frame reports or encoding parameters. Unknown operations/effects fail closed.
"""
import argparse
import json
from pathlib import Path
import re

from pcode_cfg import Graph, CONTROL, LIMITS, index
from pcode_values import Unsupported, SCALAR, BINARY, COUNTED, shape

EXTRA = {"INT_SLESS", "INT_SLESSEQUAL", "BOOL_AND", "BOOL_OR", "BOOL_XOR"}
EFFECTS = {"LOAD", "STORE", "CALL"}
POINTER = {"PTRADD", "PTRSUB"}


class RegionGraph(Graph):
    def __init__(self, export):
        if export.get("schema_version") != 5 or export.get("memory_model") != "ordered-u32-regions-v1":
            raise Unsupported("requires ordered region export schema 5")
        if export.get("status") != "decompiled" or export.get("operation_order") != "basic-block-live-order":
            raise Unsupported("requires completed ordered decompilation")
        self.nodes, self.ops, self.parameters = export["nodes"], export["operations"], export["parameters"]
        if not isinstance(self.nodes, list) or not isinstance(self.ops, list): raise Unsupported("invalid graph lists")
        if len(self.nodes) > LIMITS["nodes"] or len(self.ops) > LIMITS["operations"]: raise Unsupported("P-code budget exceeded")
        if export["arity"] != 3 or [p["kind"] for p in self.parameters] not in (["uint32-buffer", "uint32", "int32"], ["uint32-buffer", "uint32", "uint32"]):
            raise Unsupported("requires one writable u32 buffer and two 32-bit scalars")
        if any(p["read_only"] for p in self.parameters): raise Unsupported("read-only interface unsupported")
        space = export["address_space"]
        if space["pointer_bytes"] not in (4, 8) or space["addressable_unit_bytes"] != 1:
            raise Unsupported("requires byte-addressed 32/64-bit pointer ABI")
        self.pointer_bits, self.space = space["pointer_bytes"]*8, space["id"]
        self.initial, self.definitions, self.constants, self.pointers, self.opaque = {}, {}, {}, {}, set()
        for i, node in enumerate(self.nodes):
            size = node["size"]
            if type(size) is not int or size not in (1, 2, 4, 8): raise Unsupported("unsupported varnode width")
            if "constant" in node:
                number = node["constant"]
                if (not isinstance(number, str) or not number.isascii() or not number.isdecimal() or len(number) > 20
                        or node.get("input") or "parameter" in node): raise Unsupported("invalid constant")
                number = int(number)
                if not 0 <= number < 1 << (size*8): raise Unsupported("constant out of range")
                self.constants[i] = number
                self.initial[i] = f"UINT64_C({number})"
            elif "parameter" in node:
                slot = index(node["parameter"], 3, "parameter")
                if node.get("input") is not True or size != (space["pointer_bytes"] if slot == 0 else 4):
                    raise Unsupported("parameter storage disagrees with ABI")
                self.initial[i] = f"((uint64_t)(uint32_t)p{slot})" if slot else None
                if slot == 0: self.pointers[i] = 0
        for oi, op in enumerate(self.ops):
            code, inputs = op["opcode"], op["inputs"]
            if not isinstance(inputs, list): raise Unsupported("invalid inputs")
            for v in inputs: index(v, len(self.nodes), "varnode")
            if code not in SCALAR | EXTRA | EFFECTS | POINTER | CONTROL | {"MULTIEQUAL"}:
                raise Unsupported("unsupported P-code operation: " + code)
            if code in CONTROL | {"CALL"}:
                if not inputs: raise Unsupported("missing code address")
                v = inputs[0]
                if v not in self.initial:
                    if self.nodes[v].get("input"): raise Unsupported("unresolved indirect control target")
                    self.initial[v] = None
                    self.opaque.add(v)
            out = op.get("output")
            if out is not None:
                index(out, len(self.nodes), "varnode")
                if out in self.definitions or out in self.initial or self.nodes[out].get("input"):
                    raise Unsupported("multiple definitions or assignment to input/constant")
                self.definitions[out] = oi
            if code in CONTROL:
                if out is not None or len(inputs) != (1 if code == "BRANCH" else 2): raise Unsupported("invalid terminator")
                if code == "RETURN" and self.width(inputs[1]) != 32: raise Unsupported("return must be 32 bits")
                if code == "CBRANCH" and self.width(inputs[1]) != 8: raise Unsupported("condition must be byte")
            elif code == "CALL":
                name = op.get("callee")
                if name not in ("record_event", "next_value") or len(inputs) != 2 or self.width(inputs[1]) != 32:
                    raise Unsupported("unknown callback or signature")
                if (out is not None) != (name == "next_value") or (out is not None and self.width(out) != 32):
                    raise Unsupported("callback return signature mismatch")
            elif code in ("LOAD", "STORE"):
                if len(inputs) != (2 if code == "LOAD" else 3) or self.constants.get(inputs[0]) != self.space:
                    raise Unsupported("memory space/interface mismatch")
                if (out is not None) != (code == "LOAD") or self.width(out if out is not None else inputs[2]) != 32:
                    raise Unsupported("requires exact u32 load/store")
            else:
                if out is None: raise Unsupported("missing data output")
                bits, widths = self.width(out), [self.width(v) for v in inputs]
                if code == "MULTIEQUAL":
                    if not inputs or any(w != bits for w in widths): raise Unsupported("invalid phi widths")
                elif code in POINTER:
                    if len(inputs) != (3 if code == "PTRADD" else 2) or bits != self.pointer_bits or widths[0] != bits:
                        raise Unsupported("invalid pointer interface")
                elif code in EXTRA:
                    if len(inputs) != 2 or widths[0] != widths[1] or bits != 8 or (code.startswith("BOOL") and widths[0] != 8):
                        raise Unsupported("invalid signed comparison/boolean shape")
                else:
                    shape(code, bits, widths)
                    if code in COUNTED:
                        if inputs[1] not in self.constants: raise Unsupported("nonconstant shift/subpiece")
                        if code == "SUBPIECE" and self.constants[inputs[1]]*8 + bits > widths[0]: raise Unsupported("subpiece out of range")
        # Opaque code addresses are never admitted as data. Even malformed uses
        # on an unreachable branch fail, before any dynamic grading takes place.
        for op in self.ops:
            data = op["inputs"][1:] if op["opcode"] in CONTROL | {"CALL"} else op["inputs"]
            if any(i in self.opaque for i in data): raise Unsupported("code address used as data")
        self.cfg(export)  # Reciprocal edges, complete ownership, SSA dominance.
        self.infer_pointers()

    def infer_pointers(self):
        changed = True
        while changed:
            changed = False
            for op in self.ops:
                out, ins, code = op.get("output"), op["inputs"], op["opcode"]
                if out is None or out in self.pointers: continue
                value = None
                if code in ("COPY", "CAST") and ins[0] in self.pointers: value = self.pointers[ins[0]]
                elif code == "MULTIEQUAL" and all(i in self.pointers for i in ins):
                    if len({self.pointers[i] for i in ins}) != 1: raise Unsupported("variable pointer merge")
                    value = self.pointers[ins[0]]
                elif code in ("PTRSUB", "PTRADD", "INT_ADD", "INT_SUB"):
                    args = ins
                    if code == "INT_ADD" and args[1] in self.pointers: args = args[::-1]
                    if args[0] in self.pointers and all(i in self.constants for i in args[1:]):
                        offset = self.constants[args[1]]
                        if code == "PTRADD": offset *= self.constants[args[2]]
                        if code == "INT_SUB": offset = -offset
                        value = (self.pointers[args[0]] + offset) % (1 << self.pointer_bits)
                if value is not None:
                    if self.width(out) != self.pointer_bits: raise Unsupported("pointer width changed")
                    self.pointers[out], changed = value, True
        for op in self.ops:
            code, ins, out = op["opcode"], op["inputs"], op.get("output")
            if code in ("LOAD", "STORE"):
                if ins[1] not in self.pointers or self.pointers[ins[1]] not in (0, 4, 8):
                    raise Unsupported("memory outside three-word fixed public buffer")
                if code == "STORE" and ins[2] in self.pointers: raise Unsupported("pointer escapes into data")
            elif out in self.pointers:
                if code not in ("COPY", "CAST", "PTRSUB", "PTRADD", "INT_ADD", "INT_SUB", "MULTIEQUAL"):
                    raise Unsupported("unsupported pointer operation")
            elif code in POINTER or any(v in self.pointers for v in ins):
                raise Unsupported("pointer escapes or unsupported pointer computation")

    def atom(self, v):
        if v in self.pointers or v in self.opaque: raise Unsupported("non-scalar data expression")
        return self.initial[v] if v in self.initial else f"v{v}"

    def scalar(self, op):
        code, ins = op["opcode"], op["inputs"]
        args = [self.atom(i) for i in ins]
        a, bits = args[0], self.width(ins[0])
        sign = f"UINT64_C({1 << (bits-1)})"
        if code in BINARY: return f"({a} {BINARY[code]} {args[1]})"
        if code in ("INT_SLESS", "INT_SLESSEQUAL"):
            return f"(({a} ^ {sign}) {'<' if code == 'INT_SLESS' else '<='} ({args[1]} ^ {sign}))"
        if code in ("BOOL_AND", "BOOL_OR", "BOOL_XOR"):
            return f"(({a} != 0) " + {"BOOL_AND":"&&", "BOOL_OR":"||", "BOOL_XOR":"!="}[code] + f" ({args[1]} != 0))"
        if code in ("COPY", "CAST", "INT_ZEXT"): return a
        if code == "INT_SEXT": return f"(({a} ^ {sign}) - {sign})"
        if code == "INT_NEGATE": return f"~{a}"
        if code == "INT_2COMP": return f"(UINT64_C(0) - {a})"
        if code == "BOOL_NEGATE": return f"({a} == 0)"
        if code == "PIECE": return f"(({a} << {self.width(ins[1])}) | {args[1]})"
        if code in COUNTED:
            count = self.constants[ins[1]] * (8 if code == "SUBPIECE" else 1)
            if count == 0: return a
            fill = f"(UINT64_C(0) - ({a} >> {bits-1}))"
            if count >= bits: return fill if code == "INT_SRIGHT" else "UINT64_C(0)"
            if code == "INT_SRIGHT": return f"(({a} >> {count}) | ({fill} << {bits-count}))"
            return f"({a} {'<<' if code == 'INT_LEFT' else '>>'} {count})"
        raise Unsupported("missing scalar rule: " + code)


def reconstruct(export, metrics=None, mutation=None):
    try:
        return _reconstruct(export, {} if metrics is None else metrics, mutation)
    except Unsupported: raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as error:
        raise Unsupported("malformed region P-code: " + str(error)) from error


def _reconstruct(export, metrics, mutation):
    name = export["function"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name): raise Unsupported("invalid symbol")
    if mutation not in (None, "return", "store", "call-argument", "drop-call", "branch"): raise ValueError("unknown control mutation")
    graph = RegionGraph(export)
    signed = export.get("return_type", "uint32") == "int32"
    if export.get("return_type", "uint32") not in ("uint32", "int32"): raise Unsupported("unknown return type")
    scalars = [v for v in graph.definitions if v not in graph.pointers]
    phi = [op for op in graph.ops if op["opcode"] == "MULTIEQUAL" and op["output"] not in graph.pointers]
    lines = ["#include <stdint.h>", "#include <stdlib.h>", "#include <limits.h>",
             "_Static_assert(sizeof(int)==4, \"32-bit int ABI required\");",
             "extern uint32_t next_value(uint32_t);", "extern void record_event(uint32_t);",
             ("int32_t " if signed else "uint32_t ") + name + "(uint32_t *p0,uint32_t p1," +
             ("int32_t" if graph.parameters[2]["kind"] == "int32" else "uint32_t") + " p2){",
             "    unsigned steps=0, incoming=0;", "    (void)p0;(void)p1;(void)p2;(void)incoming;"]
    lines += [f"    uint64_t v{v}=0; (void)v{v};" for v in scalars]
    lines += [f"    uint64_t phi{op['output']}=0;" for op in phi]
    lines.append(f"    goto b{graph.entry};")
    mutated = False
    for bid, block in graph.blocks.items():
        lines += [f"b{bid}:", "    if(++steps>10000u)exit(71);"]
        operations = [graph.ops[i] for i in block["operations"]]
        for op in operations:
            if op["opcode"] != "MULTIEQUAL" or op["output"] in graph.pointers: continue
            lines.append("    switch(incoming){")
            lines += [f"    case {slot}:phi{op['output']}={graph.atom(v)};break;" for slot, v in enumerate(op["inputs"])]
            lines.append("    default:exit(72);}")
        lines += [f"    v{op['output']}=phi{op['output']};" for op in operations if op["opcode"] == "MULTIEQUAL" and op["output"] not in graph.pointers]
        for op in operations:
            code, ins, out = op["opcode"], op["inputs"], op.get("output")
            if code in {"MULTIEQUAL", "BRANCH", "CBRANCH"} or out in graph.pointers: continue
            if code == "RETURN":
                expr = graph.atom(ins[1]) + (" + UINT64_C(1)" if mutation == "return" else "")
                if signed:
                    lines += [f"    {{uint32_t r=(uint32_t)({expr});", "    return r<=INT32_MAX?(int32_t)r:INT32_MIN+(int32_t)(r-UINT32_C(2147483648));}"]
                else: lines.append(f"    return (uint32_t)({expr});")
                continue
            if code == "STORE":
                expr = graph.atom(ins[2]) + (" + UINT64_C(1)" if mutation == "store" else "")
                lines.append(f"    p0[{graph.pointers[ins[1]]//4}]=(uint32_t)({expr});")
                continue
            if code == "CALL":
                expr = graph.atom(ins[1])
                if mutation == "call-argument" and not mutated: expr += " + UINT64_C(1)"; mutated = True
                if mutation == "drop-call" and op["callee"] == "record_event" and not mutated:
                    mutated = True
                    continue
                expr = f"{op['callee']}((uint32_t)({expr}))"
                if out is None: lines.append("    " + expr + ";"); continue
            elif code == "LOAD": expr = f"p0[{graph.pointers[ins[1]]//4}]"
            else: expr = graph.scalar(op)
            lines.append(f"    v{out}=({expr}) & UINT64_C({(1 << graph.width(out))-1});")
        if block["outgoing"]:
            def jump(edge): return f"incoming={edge['reverse_index']};goto b{edge['block']};"
            if len(block["outgoing"]) == 1: lines.append("    " + jump(block["outgoing"][0]))
            else:
                condition = graph.atom(operations[-1]["inputs"][1])
                if mutation == "branch" and not mutated: condition = "!("+condition+")"; mutated = True
                # Ghidra basic-block successor slot 0 is false; slot 1 is true.
                lines.append(f"    if({condition}){{{jump(block['outgoing'][1])}}}else{{{jump(block['outgoing'][0])}}}")
    lines.append("}")
    source = "\n".join(lines)+"\n"
    if len(source) > LIMITS["generated_bytes"]: raise Unsupported("generated byte budget exceeded")
    metrics.update(observer="ordered-u32-regions-v1", operations=len(graph.ops), blocks=len(graph.blocks),
                   loads=sum(o["opcode"] == "LOAD" for o in graph.ops), stores=sum(o["opcode"] == "STORE" for o in graph.ops),
                   calls=sum(o["opcode"] == "CALL" for o in graph.ops), generated_bytes=len(source),
                   block_entry_budget=10000, mutation=mutation)
    return source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("export"); p.add_argument("output"); p.add_argument("--mutation", choices=("return", "store", "call-argument", "drop-call", "branch"))
    args = p.parse_args()
    metrics = {}
    try:
        source = reconstruct(json.loads(Path(args.export).read_text()), metrics, args.mutation)
        Path(args.output).write_text(source)
        metrics["status"] = "reconstructed"
    except Unsupported as error: metrics.update(status="unsupported", reason=str(error))
    Path(args.output + ".json").write_text(json.dumps(metrics, indent=2)+"\n")
    return int(metrics["status"] != "reconstructed")


if __name__ == "__main__": raise SystemExit(main())
