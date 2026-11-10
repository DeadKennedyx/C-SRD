"""Bounded, fail-closed high P-code expression reconstruction; no source input.

Only one unconditional return and a side-effect-free expression DAG are admitted.
Widths are explicit; unsupported nodes are evidence gaps, never protection scores.
This adapter and Ghidra are trusted interpretations, not verified binary lifters.
"""
import re


class Unsupported(ValueError):
    pass


def reconstruct(export, result_offset=0):
    name, arity = export["function"], export["arity"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) or not 1 <= arity <= 4:
        raise Unsupported("interface outside bounded protocol")
    nodes, ops = export["nodes"], export["operations"]
    if len(nodes) > 4096 or len(ops) > 2048:
        raise Unsupported("P-code budget exceeded")
    returns = [o for o in ops if o["opcode"] == "RETURN"]
    if len(returns) != 1 or len(returns[0]["inputs"]) != 2:
        raise Unsupported("requires one single-value return")
    # Reject control flow/effects even if outside the return's backward slice.
    forbidden = {"BRANCH", "CBRANCH", "BRANCHIND", "CALL", "CALLIND", "CALLOTHER", "STORE", "INDIRECT"}
    if any(o["opcode"] in forbidden for o in ops):
        raise Unsupported("control flow, effects or unresolved call in high P-code")
    definitions = {}
    for op in ops:
        if "output" in op:
            if op["output"] in definitions:
                raise Unsupported("multiple definitions of a varnode")
            definitions[op["output"]] = op
    values, visiting, lines = {}, set(), []

    def width(i):
        size = nodes[i]["size"]
        if size not in (1, 2, 4):
            raise Unsupported(f"unsupported varnode width: {size} bytes")
        return size * 8

    def expression(i):
        if i in values:
            return values[i]
        if i in visiting or len(visiting) >= 128:
            raise Unsupported("cyclic graph or expression depth budget exceeded")
        bits = width(i)
        node = nodes[i]
        if "constant" in node:
            return str(int(node["constant"]) & ((1 << bits) - 1)) + "u"
        if "parameter" in node and node.get("input"):
            slot = node["parameter"]
            if bits != 32 or not 0 <= slot < arity:
                raise Unsupported("parameter storage does not match supplied u32 interface")
            return "p" + str(slot)
        if i not in definitions:
            raise Unsupported("unresolved non-parameter input")
        visiting.add(i)
        op = definitions[i]
        code, inputs = op["opcode"], op["inputs"]
        unary = {"COPY", "CAST", "INT_ZEXT", "INT_SEXT", "INT_NEGATE", "INT_2COMP", "BOOL_NEGATE"}
        binary = {"INT_ADD": "+", "INT_SUB": "-", "INT_MULT": "*", "INT_AND": "&",
                  "INT_OR": "|", "INT_XOR": "^", "INT_EQUAL": "==", "INT_NOTEQUAL": "!=",
                  "INT_LESS": "<", "INT_LESSEQUAL": "<="}
        if code not in unary | set(binary) | {"INT_LEFT", "INT_RIGHT", "SUBPIECE"}:
            raise Unsupported(f"unsupported P-code operation: {code}")
        if len(inputs) != (1 if code in unary else 2):
            raise Unsupported("unexpected operation arity")
        # Shift/subpiece count storage has its own width in P-code. Ghidra can
        # use an 8-byte constant count with a 4-byte payload. Interpret that
        # metadata exactly, without admitting/truncating a wide data value.
        counted = code in ("INT_LEFT", "INT_RIGHT", "SUBPIECE")
        args = [expression(v) for v in (inputs[:1] if counted else inputs)]
        a = args[0]
        if code in binary:
            if width(inputs[0]) != width(inputs[1]):
                raise Unsupported("binary input widths differ")
            if code in ("INT_EQUAL", "INT_NOTEQUAL", "INT_LESS", "INT_LESSEQUAL"):
                if bits != 8:
                    raise Unsupported("comparison output must be a P-code boolean byte")
            elif bits != width(inputs[0]):
                raise Unsupported("arithmetic output width differs from inputs")
            if code == "INT_MULT" and not any("constant" in nodes[v] for v in inputs):
                raise Unsupported("general multiplication outside source verifier")
            expr = f"({a} {binary[code]} {args[1]})"
        elif code in ("COPY", "CAST", "INT_ZEXT"):
            if code in ("COPY", "CAST") and width(inputs[0]) != bits:
                raise Unsupported("copy/cast widths differ")
            if code == "INT_ZEXT" and width(inputs[0]) > bits:
                raise Unsupported("invalid zero extension")
            expr = a
        elif code == "INT_SEXT":
            source_bits = width(inputs[0])
            if source_bits > bits:
                raise Unsupported("invalid sign extension")
            sign = str(1 << (source_bits - 1)) + "u"
            expr = f"(({a} ^ {sign}) - {sign})"
        elif code == "INT_NEGATE":
            expr = f"(~{a})"
        elif code == "INT_2COMP":
            expr = f"(0u - {a})"
        elif code == "BOOL_NEGATE":
            expr = f"({a} == 0u)"
        else:
            if "constant" not in nodes[inputs[1]]:
                raise Unsupported("nonconstant shift or subpiece offset")
            count = nodes[inputs[1]]
            if count["size"] not in (1, 2, 4, 8):
                raise Unsupported("unsupported constant count width")
            amount = int(count["constant"])
            if not 0 <= amount < (1 << (8 * count["size"])):
                raise Unsupported("constant count does not fit its storage width")
            shift = amount * (8 if code == "SUBPIECE" else 1)
            source_bits = width(inputs[0])
            if shift < 0:
                raise Unsupported("negative shift")
            expr = "0u" if shift >= source_bits else f"({a} {'<<' if code == 'INT_LEFT' else '>>'} {shift}u)"
        # Materialize comparisons first: C's comparison has int type. A subsequent
        # narrow mask must operate on an explicitly unsigned local.
        value = "v" + str(i)
        lines.append(f"    unsigned int {value} = {expr};")
        if bits < 32:
            lines.append(f"    {value} = {value} & {(1 << bits) - 1}u;")
        visiting.remove(i)
        values[i] = value
        return value

    result_id = returns[0]["inputs"][1]
    if width(result_id) != 32:
        raise Unsupported("return is not u32")
    result = expression(result_id)
    if result_offset:
        result = f"({result} + {result_offset & 0xffffffff}u)"
    # All parameters remain in the known ABI even when not read.
    for i in range(arity):
        lines.append(f"    (void)p{i};")
    parameters = ", ".join(f"unsigned int p{i}" for i in range(arity))
    return f"unsigned int {name}({parameters}) {{\n" + "\n".join(lines) + f"\n    return {result};\n}}\n"
