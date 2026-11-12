"""Ordered byte/word buffer reconstruction from binary-only high P-code.

The public signature supplies types, not memory footprints or algorithm facts.
Parameter-relative pointers remain symbolic, so emitted C retains all alias
relationships. Every load is snapshotted at its instruction position; stores
are never pruned just because the returned value does not depend on them.
"""
from dataclasses import dataclass
import re

from pcode_values import Builder, Unsupported, Value, literal, SCALAR, COMPARE
from pcode_cfg import LIMITS, index


@dataclass(frozen=True)
class Pointer:
    bits: int
    slot: int
    offset: int | Value = 0  # byte offset modulo pointer width


TYPES = {"uint32": "unsigned int", "uint32-buffer": "unsigned int",
         "unsigned-char-buffer": "unsigned char", "signed-char-buffer": "signed char", "char-buffer": "char"}


def reconstruct(export, *, metrics=None, result_offset=0, store_offset=0, final_store_offset=0, call_argument_offset=0):
    try:
        return _reconstruct(export, {} if metrics is None else metrics, result_offset, store_offset, final_store_offset, call_argument_offset)
    except Unsupported:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise Unsupported(f"malformed memory P-code: {error}") from error


def _reconstruct(export, metrics, result_offset, store_offset, final_store_offset, call_argument_offset):
    calls = export.get("schema_version") == 7 and export.get("memory_model") == "ordered-calls-buffers-v1"
    extended = calls or (export.get("schema_version") == 5 and export.get("memory_model") == "ordered-byte-buffers-v2")
    if not extended and (export.get("schema_version") != 4 or export.get("memory_model") != "ordered-u32-buffers-v1"):
        raise Unsupported("requires ordered buffer export schema 4 or 5")
    name, arity, parameters = export["function"], export["arity"], export["parameters"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise Unsupported("invalid function symbol")
    if type(arity) is not int or not 1 <= arity <= 8 or len(parameters) != arity:
        raise Unsupported("invalid public buffer interface")
    for p in parameters:
        if p["kind"] not in (TYPES if extended else ("uint32", "uint32-buffer")) or type(p["read_only"]) is not bool:
            raise Unsupported("invalid parameter kind or constness")
        if p["kind"] == "uint32" and p["read_only"]:
            raise Unsupported("const scalar parameters are outside the contract")
    if not calls and not any(p["kind"] != "uint32" for p in parameters):
        raise Unsupported("buffer observer requires at least one pointer")
    signatures = export.get("call_signatures", {}) if calls else {}
    if not isinstance(signatures,dict) or len(signatures)>64:raise Unsupported("invalid call signatures")
    declarations=[]
    for callee,spec in signatures.items():
        if (not isinstance(callee,str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*",callee) or
            re.fullmatch(r"[pv][0-9]+",callee) or callee==name):raise Unsupported("invalid or conflicting external call symbol")
        if spec["returns"] not in ("void","uint32") or not isinstance(spec["parameters"],list) or len(spec["parameters"])>8:
            raise Unsupported("invalid call ABI")
        types=[]
        for p in spec["parameters"]:
            if p["kind"] not in TYPES or type(p["read_only"]) is not bool or (p["kind"]=="uint32" and p["read_only"]):
                raise Unsupported("invalid call parameter type")
            types.append(("const " if p["read_only"] else "")+TYPES[p["kind"]]+("*" if p["kind"]!="uint32" else ""))
        declarations.append(("void" if spec["returns"]=="void" else "unsigned int")+" "+callee+"("+(",".join(types) or "void")+");")
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
    diamonds=0
    if export.get("operation_order") != "basic-block-live-order":
        raise Unsupported("requires ordered basic-block instructions")
    if extended:
        from pcode_memory_cfg import linearize
        ops,diamonds=linearize(export)
        blocks=[{"id":0,"incoming":[],"outgoing":[],"operations":list(range(len(ops)))}]
    if len(blocks) != 1:
        raise Unsupported("buffer observer currently requires one ordered basic block")
    block = blocks[0]
    if (type(block["id"]) is not int or (not extended and export["entry_block"] != block["id"]) or
            block["incoming"] or block["outgoing"] or block["operations"] != list(range(len(ops)))):
        raise Unsupported("inconsistent straight-line block membership")
    if not ops or ops[-1]["opcode"] != "RETURN" or any(o["opcode"] == "RETURN" for o in ops[:-1]):
        raise Unsupported("requires one final return")
    metrics.update(observer="ordered-calls-buffers-v1" if calls else "ordered-byte-buffers-v2" if extended else "ordered-u32-buffers-v1", evaluated_operations=0,
                   emitted_statements=0, loads=0, stores=0, pointer_operations=0,
                   calls=0,
                   scalar_diamonds=diamonds,
                   footprint_elements={str(i): 0 for i, p in enumerate(parameters) if p["kind"] != "uint32"})
    builder, values, definitions = Builder(metrics), {}, set()
    bounds, predicates, multiples, origins = {}, {}, {}, {}

    def multiple(value):
        if value.known is not None:return (value.known & -value.known) if value.known else (1<<value.bits)
        return multiples.get(value,1)

    def bound(value):
        if value.known is not None: return value.known
        if value in bounds: return bounds[value]
        if value.parts: return sum(bound(part) << (i*32) for i,part in enumerate(value.parts))
        return (1 << value.bits)-1

    def operation(code, bits, args):
        value = builder.operation(code, bits, args)
        maximum = (1 << bits)-1
        a, b = bound(args[0]), bound(args[1]) if len(args)>1 else 0
        if code in ("COPY", "CAST", "INT_ZEXT"): maximum = min(maximum,a)
        elif code == "INT_SEXT" and a < (1 << (args[0].bits-1)): maximum = a
        elif code == "INT_ADD" and a+b <= maximum: maximum = a+b
        elif code == "INT_MULT" and a*b <= maximum: maximum = a*b
        elif code == "INT_AND": maximum = min(a,b)
        elif code in ("INT_OR","INT_XOR"): maximum = (1 << max(a,b).bit_length())-1
        elif code in COMPARE or code == "BOOL_NEGATE": maximum = 1
        elif code == "INT_LEFT" and args[1].known is not None:
            shift=args[1].known
            if shift>=bits: maximum=0
            elif a<<shift <= maximum: maximum=a<<shift
        elif code in ("INT_RIGHT","SUBPIECE") and args[1].known is not None:
            maximum=min(maximum,a >> (args[1].known*(8 if code=="SUBPIECE" else 1)))
        bounds[value]=maximum
        m=1
        if code in ("COPY","CAST","INT_ZEXT","INT_SEXT"):m=multiple(args[0])
        elif code=="INT_MULT":m=multiple(args[0])*multiple(args[1])
        elif code in ("INT_ADD","INT_SUB","INT_OR","INT_XOR"):m=min(multiple(args[0]),multiple(args[1]))
        elif code=="INT_AND":m=max(multiple(args[0]),multiple(args[1]))
        elif code=="INT_LEFT" and args[1].known is not None:m=multiple(args[0])<<min(args[1].known,bits)
        multiples[value]=min(1<<bits,m)
        if value.known is None and value not in args:origins[value]=(code,bits,tuple(args))
        if value.known is None:
            if code in COMPARE:predicates[value]=(code,args[0],args[1],False)
            elif code=="BOOL_NEGATE" and args[0] in predicates:
                code,a,b,negated=predicates[args[0]];predicates[value]=(code,a,b,not negated)
        return value

    def select(condition,yes,no):
        if condition.bits!=8 or yes.bits!=no.bits:raise Unsupported("invalid scalar diamond values")
        if condition.known is not None:return yes if condition.known else no
        if yes.bits>32:
            if len(yes.parts)!=len(no.parts):raise Unsupported("inconsistent wide scalar merge")
            result=Value(yes.bits,"",parts=tuple(select(condition,a,b) for a,b in zip(yes.parts,no.parts)))
        else:result=builder.emit(yes.bits,f"({condition.atom} ? {yes.atom} : {no.atom})")
        cache={}
        def branch_bound(value,truth,depth=0):
            key=(value,truth)
            if key in cache:return cache[key]
            maximum=bound(value)
            if condition in predicates:
                code,a,b,negated=predicates[condition];holds=truth!=negated
                if code in ("INT_LESS","INT_LESSEQUAL"):
                    if value==a and b.known is not None and holds:
                        maximum=min(maximum,max(0,b.known-(code=="INT_LESS")))
                    if value==b and a.known is not None and not holds:
                        maximum=min(maximum,max(0,a.known-(code=="INT_LESSEQUAL")))
            # A compiler may move widening/scaling into a branch before its
            # phi. Propagate the condition through those total operations.
            # Depth exhaustion only loses precision; it never invents a bound.
            if value in origins and depth<64:
                code,bits,args=origins[value];mask=(1<<bits)-1
                a=branch_bound(args[0],truth,depth+1)
                b=branch_bound(args[1],truth,depth+1) if len(args)>1 else 0
                inferred=mask
                if code in ("COPY","CAST","INT_ZEXT"):inferred=min(mask,a)
                elif code=="INT_SEXT" and a<(1<<(args[0].bits-1)):inferred=a
                elif code=="INT_AND":inferred=min(a,b)
                elif code=="INT_ADD" and a+b<=mask:inferred=a+b
                elif code=="INT_MULT" and a*b<=mask:inferred=a*b
                elif code in ("INT_LEFT","INT_RIGHT","SUBPIECE") and args[1].known is not None:
                    shift=args[1].known*(8 if code=="SUBPIECE" else 1)
                    if shift>=args[0].bits:inferred=0
                    elif code!="INT_LEFT":inferred=a>>shift
                    elif a<<shift<=mask:inferred=a<<shift
                maximum=min(maximum,inferred)
            cache[key]=maximum
            return maximum
        bounds[result]=max(branch_bound(yes,True),branch_bound(no,False))
        multiples[result]=min(multiple(yes),multiple(no))
        return result
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
            pointer = parameters[slot]["kind"] != "uint32"
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

    def address(pointer, bits=32, write=False, argument=False):
        if not isinstance(pointer, Pointer) or pointer.bits != pointer_bits:
            raise Unsupported("memory address is not derived from a public pointer")
        element_bytes = 4 if parameters[pointer.slot]["kind"] == "uint32-buffer" else 1
        if bits != element_bytes*8: raise Unsupported("memory access width differs from public pointee type")
        if isinstance(pointer.offset,int):
            if pointer.offset % element_bytes or not 0 <= pointer.offset <= (255 if extended else 15)*element_bytes:
                raise Unsupported("unaligned or out-of-contract fixed memory offset")
            element = pointer.offset // element_bytes
            expression = str(element)
        else:
            maximum=bound(pointer.offset)
            if maximum>255*element_bytes or multiple(pointer.offset)<element_bytes:
                raise Unsupported("dynamic observer offset must be bounded and element-aligned")
            low=pointer.offset.parts[0] if pointer.offset.parts else pointer.offset
            if element_bytes==4:low=operation("INT_RIGHT",32,[low,literal(32,2)]);maximum//=4
            # Abstract interval reasoning proves this clamp is a no-op in the
            # P-code. Source grading checks it independently before crediting it.
            captured=builder.emit(32,low.atom)
            element=maximum
            expression=f"({captured.atom} <= {maximum}u ? {captured.atom} : {maximum}u)"
        if write and parameters[pointer.slot]["read_only"]:
            raise Unsupported("store through a read-only public parameter")
        footprint = metrics["footprint_elements"]
        footprint[str(pointer.slot)] = max(footprint[str(pointer.slot)], element + 1)
        if argument:return f"p{pointer.slot}" if isinstance(pointer.offset,int) and pointer.offset==0 else f"(p{pointer.slot}+{expression})"
        return f"p{pointer.slot}[{expression}]"

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
        elif out is None and not (calls and code=="CALL"):
            raise Unsupported("missing data instruction output")
        bits = nodes[out]["size"] * 8 if out is not None else None
        # Return input 0 is an instruction address, not a value computation.
        args = [read(i) for i in inputs[1:]] if code in ("RETURN","CALL") else [read(i) for i in inputs]
        if code == "RETURN":
            result = args[0]
            if not isinstance(result, Value) or result.bits != 32:
                raise Unsupported("return must be uint32")
        elif calls and code=="CALL":
            spec=signatures.get(op.get("callee"))
            if not spec or len(args)!=len(spec["parameters"]) or not inputs:
                raise Unsupported("unknown or mismatched direct call ABI")
            if (spec["returns"]=="void" and out is not None) or (out is not None and bits!=32):
                raise Unsupported("call return storage disagrees with public ABI")
            arguments=[]
            for value,p in zip(args,spec["parameters"]):
                if p["kind"]=="uint32":
                    if not isinstance(value,Value) or value.bits!=32:raise Unsupported("call scalar argument is not uint32")
                    atom=value.atom
                    if call_argument_offset:
                        atom=f"({atom}+{call_argument_offset & 0xffffffff}u)";call_argument_offset=0
                    arguments.append(atom)
                else:
                    if not isinstance(value,Pointer) or parameters[value.slot]["kind"]!=p["kind"] or (parameters[value.slot]["read_only"] and not p["read_only"]):
                        raise Unsupported("call pointer argument type/constness mismatch")
                    arguments.append(address(value,32 if p["kind"]=="uint32-buffer" else 8,argument=True))
            invocation=op["callee"]+"("+", ".join(arguments)+")"
            if out is not None:values[out]=builder.emit(32,invocation)
            else:builder.lines.append("    "+invocation+";")
            metrics["calls"]+=1
        elif code in ("LOAD", "STORE"):
            if len(args) != (2 if code == "LOAD" else 3) or constant(args[0]) != space["id"]:
                raise Unsupported("invalid load/store address space or arity")
            if code == "LOAD":
                if bits != 32 and not (extended and bits == 8):
                    raise Unsupported("only exact uint32 loads are supported")
                values[out] = builder.emit(bits, "((unsigned int)(" + address(args[1],bits) + "))" if extended else address(args[1]))
                metrics["loads"] += 1
            else:
                value = args[2]
                if not isinstance(value, Value) or (value.bits != 32 and not (extended and value.bits == 8)):
                    raise Unsupported("only exact uint32 stores are supported")
                expression = value.atom
                # Legacy all-store mutation is retained for historical replay.
                # Mutating only the final store avoids cancellations across
                # earlier stores and guarantees an observable memory change.
                offset = store_offset + (final_store_offset if oi == final_store else 0)
                if offset:
                    expression = f"({expression} + {offset & 0xffffffff}u)"
                destination=address(args[1], value.bits, write=True)
                builder.lines.append(f"    {destination} = {expression};")
                metrics["stores"] += 1
        elif code=="CSRD_SELECT":
            if len(args)!=3 or any(not isinstance(a,Value) for a in args) or bits!=args[1].bits:
                raise Unsupported("pointer or malformed scalar merge")
            values[out]=select(*args)
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
            if extended and ((isinstance(base.offset,Value)) or any(a.known is None for a in args[1:])):
                if code == "PTRADD" and len(args)==3:
                    delta=operation("INT_MULT",pointer_bits,args[1:])
                elif code in ("PTRSUB","INT_ADD") and len(args)==2: delta=args[1]
                else: raise Unsupported("unsupported dynamic pointer operation")
                if any(a.bits!=pointer_bits for a in args): raise Unsupported("pointer arithmetic width mismatch")
                initial=base.offset if isinstance(base.offset,Value) else literal(pointer_bits,base.offset)
                values[out]=Pointer(pointer_bits,base.slot,operation("INT_ADD",pointer_bits,[initial,delta]))
                continue
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
            if extended and code in SCALAR:
                values[out]=operation(code,bits,args)
            elif code == "INT_LEFT" and len(args) == 2 and bits == args[0].bits == 32:
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
    signature = ", ".join(("const " if p["read_only"] else "") + TYPES[p["kind"]] +
                          (" *" if p["kind"] != "uint32" else " ") + f"p{i}"
                          for i, p in enumerate(parameters))
    lines = builder.lines + [f"    (void)v{i};" for i in range(builder.serial)] + [f"    (void)p{i};" for i in range(arity)] + [f"    return {expression};"]
    source = ("\n".join(declarations)+"\n" if declarations else "")+f"unsigned int {name}({signature}) {{\n" + "\n".join(lines) + "\n}\n"
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
