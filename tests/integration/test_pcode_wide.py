"""Independent SMT specifications versus Clang-modeled actual observer C.

An extra unconstrained reference parameter is tied to the independent expected
bit-vector expression. UNSAT of the saved C mismatch under that equality checks
every input, without parsing C in Python or trusting the emitter's expressions.
Compiled execution also uses an independent Python integer oracle.
"""
from contextlib import contextmanager
import copy
import itertools
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from pcode_values import Builder, Value, literal
from pcode_reconstruct import reconstruct, Unsupported

TOOL = str(Path(sys.argv.pop(1)).resolve()) if __name__ == "__main__" else None
MASK = 0xffffffff


@contextmanager
def directory(name):
    if os.environ.get("CSRD_PCODE_WIDE_EVIDENCE"):
        root = Path(os.environ["CSRD_PCODE_WIDE_EVIDENCE"]) / name
        root.mkdir(parents=True, exist_ok=False)
        yield root
    else:
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)


def specifications():
    cases = []
    for bits in range(8, 129, 8):
        for code in ("INT_ADD", "INT_SUB", "INT_AND", "INT_OR", "INT_XOR", "INT_EQUAL", "INT_NOTEQUAL", "INT_LESS", "INT_LESSEQUAL", "INT_NEGATE", "INT_2COMP", "COPY", "CAST"):
            cases.append((code, bits, bits, None))
        for code in ("INT_LEFT", "INT_RIGHT", "INT_SRIGHT"):
            for count in (0, 1, 31, 32, bits-1, bits, bits+1, (1 << 64)-1):
                cases.append((code, bits, bits, count))
        cases.append(("INT_MULT", bits, bits, 65537 & ((1 << bits)-1)))
    for high, low in ((8, 24), (24, 40), (40, 56), (64, 64), (120, 8)):
        cases.append(("PIECE", high, low, None))
    for small, big in ((8, 128), (24, 64), (40, 128)):
        for code in ("INT_ZEXT", "INT_SEXT"):
            cases.append((code, small, big, None))
    for size, result, offset in ((128, 24, 3), (128, 32, 7), (128, 64, 1), (120, 32, 11)):
        cases.append(("SUBPIECE", size, result, offset))
    return list(dict.fromkeys(cases))


def input_expression(bits, base):
    chunks = [f"((_ extract {min(31, bits-i-1)} 0) input_{base+i//32})" if bits-i < 32 else f"input_{base+i//32}"
              for i in range(0, bits, 32)]
    expr = chunks[-1]
    for chunk in reversed(chunks[:-1]):
        expr = f"(concat {expr} {chunk})"
    return expr


def specification(case):
    code, bits, other, count = case
    a, b = input_expression(bits, 0), input_expression(other, 4)
    binary = {"INT_ADD": "bvadd", "INT_SUB": "bvsub", "INT_AND": "bvand", "INT_OR": "bvor", "INT_XOR": "bvxor"}
    if code in binary: return f"({binary[code]} {a} {b})", bits
    if code in ("COPY", "CAST"): return a, bits
    if code in ("INT_NEGATE", "INT_2COMP"): return f"({'bvnot' if code == 'INT_NEGATE' else 'bvneg'} {a})", bits
    if code == "PIECE": return f"(concat {a} {b})", bits+other
    if code == "INT_MULT": return f"(bvmul {a} (_ bv{count} {bits}))", bits
    if code in ("INT_ZEXT", "INT_SEXT"):
        return f"((_ {'zero_extend' if code == 'INT_ZEXT' else 'sign_extend'} {other-bits}) {a})", other
    if code == "SUBPIECE": return f"((_ extract {8*count+other-1} {8*count}) {a})", other
    if code in ("INT_LEFT", "INT_RIGHT", "INT_SRIGHT"):
        op = {"INT_LEFT": "bvshl", "INT_RIGHT": "bvlshr", "INT_SRIGHT": "bvashr"}[code]
        # Saturate the count at the data width, preserving oversized semantics.
        return f"({op} {a} (_ bv{min(count,bits)} {bits}))", bits
    boolean = {"INT_EQUAL": f"(= {a} {b})", "INT_NOTEQUAL": f"(distinct {a} {b})",
               "INT_LESS": f"(bvult {a} {b})", "INT_LESSEQUAL": f"(bvule {a} {b})"}[code]
    return f"(ite {boolean} (_ bv1 8) (_ bv0 8))", 8


def concrete(case, inputs):
    code, bits, other, count = case
    a = sum(inputs[i] << (32*i) for i in range(4)) & ((1 << bits)-1)
    b = sum(inputs[i+4] << (32*i) for i in range(4)) & ((1 << other)-1)
    if code == "INT_ADD": value, width = a+b, bits
    elif code == "INT_SUB": value, width = a-b, bits
    elif code == "INT_MULT": value, width = a*count, bits
    elif code == "INT_AND": value, width = a & b, bits
    elif code == "INT_OR": value, width = a | b, bits
    elif code == "INT_XOR": value, width = a ^ b, bits
    elif code == "INT_EQUAL": value, width = int(a == b), 8
    elif code == "INT_NOTEQUAL": value, width = int(a != b), 8
    elif code == "INT_LESS": value, width = int(a < b), 8
    elif code == "INT_LESSEQUAL": value, width = int(a <= b), 8
    elif code == "INT_NEGATE": value, width = ~a, bits
    elif code == "INT_2COMP": value, width = -a, bits
    elif code in ("COPY", "CAST"): value, width = a, bits
    elif code == "INT_LEFT": value, width = a << min(count, bits), bits
    elif code == "INT_RIGHT": value, width = a >> min(count, bits), bits
    elif code == "INT_SRIGHT": value, width = (a-(1 << bits) if a >> (bits-1) else a) >> min(count, bits), bits
    elif code == "PIECE": value, width = (a << other) | b, bits+other
    elif code == "SUBPIECE": value, width = a >> (8*count), other
    elif code == "INT_ZEXT": value, width = a, other
    elif code == "INT_SEXT": value, width = a-(1 << bits) if a >> (bits-1) else a, other
    else: raise AssertionError(code)
    return value & ((1 << width)-1)


def generated(case):
    code, bits, other, count = case
    builder = Builder({"evaluated_operations": 0})
    def argument(width, base):
        components = []
        for start in range(0, width, 32):
            n = min(32, width-start)
            p = f"p{base+start//32}"
            components.append(Value(n, p) if n == 32 else builder.emit(n, p))
        return components[0] if width <= 32 else Value(width, "", None, tuple(components))
    a = argument(bits, 0)
    out = bits
    if code in ("INT_ZEXT", "INT_SEXT", "SUBPIECE"): out = other
    if code == "PIECE": out = bits+other
    if code in ("INT_EQUAL", "INT_NOTEQUAL", "INT_LESS", "INT_LESSEQUAL"): out = 8
    if code in ("COPY", "CAST", "INT_ZEXT", "INT_SEXT", "INT_NEGATE", "INT_2COMP"):
        args = [a]
    elif code in ("INT_LEFT", "INT_RIGHT", "INT_SRIGHT", "SUBPIECE"):
        args = [a, literal(64, count)]
    elif code == "INT_MULT": args = [a, literal(bits, count)]
    else: args = [a, argument(other, 4)]
    value = builder.operation(code, out, args)
    returns = value.parts if out > 32 else (value,)
    params = ",".join(f"unsigned int p{i}" for i in range(9))
    unused = "\n".join([*(f"(void)p{i};" for i in range(9)), *(f"(void)v{i};" for i in range(builder.serial))])
    prefix = f"unsigned int f({params}){{\n" + "\n".join(builder.lines) + "\n" + unused
    return [prefix + f"\nreturn {v.atom};\n}}\n" for v in returns], params


class Wide(unittest.TestCase):
    def test_actual_c_against_independent_smt(self):
        solver = shutil.which("z3")
        self.assertTrue(solver, "Z3 CLI required")
        with directory("proofs") as root:
            records = []
            for index, case in enumerate(specifications()):
                expected, bits = specification(case)
                sources, params = generated(case)
                for part, source in enumerate(sources):
                    folder = root / f"case-{index}-{part}"; folder.mkdir()
                    (folder / "actual.c").write_text(source)
                    (folder / "reference.c").write_text(f"unsigned int f({params}){{return p8;}}\n")
                    p = subprocess.run([TOOL, "verify", folder / "reference.c", folder / "actual.c", "--report", folder / "model.json"], capture_output=True)
                    self.assertIn(p.returncode, (0, 3), p.stderr)
                    proof = json.loads((folder / "model.json").read_text())["functions"][0]["proof"]
                    width = min(32, bits-32*part)
                    oracle = f"((_ extract {32*part+width-1} {32*part}) {expected})"
                    if width < 32: oracle = f"((_ zero_extend {32-width}) {oracle})"
                    # Some inputs unused by the actual C model may be absent in the query.
                    query = proof["smtlib"]
                    declarations = "".join(f"(declare-fun input_{i} () (_ BitVec 32))\n" for i in range(9)
                                           if f"(declare-fun input_{i} " not in query)
                    query = declarations + query.replace("(check-sat)", f"(assert (= input_8 {oracle}))\n(check-sat)")
                    (folder / "obligation.smt2").write_text(query)
                    result = subprocess.run([solver, "-T:10", folder / "obligation.smt2"], capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.stdout.strip(), "unsat", (case, part, result.stdout, result.stderr))
                    records.append({"case": case, "part": part, "status": "unsat"})
            (root / "summary.json").write_text(json.dumps(records, indent=2)+"\n")
            print("wide actual-C universal obligations:", len(records), flush=True)

    def test_compiled_against_independent_integer_oracle(self):
        cases = specifications()
        rng = random.Random(731003)
        edges = (0, 1, 255, 65535, 0x7fffffff, 0x80000000, MASK)
        vectors = [[x]*4+[y]*4+[0] for x, y in itertools.product(edges, repeat=2)]
        vectors += [[rng.getrandbits(32) for _ in range(8)]+[0] for _ in range(64)]
        functions, checks = [], []
        for case in cases:
            sources, params = generated(case)
            for part, source in enumerate(sources):
                name = "f" + str(len(functions))
                functions.append(source.replace("unsigned int f(", f"unsigned int {name}(", 1))
                values = [concrete(case, v) >> (32*part) & MASK for v in vectors]
                checks.append((name, values))
        source = "#include <stdio.h>\n" + "\n".join(functions)
        source += "\nstatic const unsigned int inputs[][9]={" + ",".join("{"+",".join(str(x)+"u" for x in v)+"}" for v in vectors) + "};\nint main(void){\n"
        for name, values in checks:
            source += "{const unsigned int expected[]={"+",".join(str(x)+"u" for x in values)+"};\n"
            source += f"for(unsigned int i=0;i<{len(vectors)}u;++i){{const unsigned int *p=inputs[i];if({name}(p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],p[8])!=expected[i]){{puts(\"{name}\");return 1;}}}}}}\n"
        source += "return 0;}\n"
        compilers = [shutil.which("gcc-16") or shutil.which("gcc"), shutil.which("clang-18") or shutil.which("clang")]
        self.assertTrue(all(compilers))
        with directory("compiled") as root:
            (root / "check.c").write_text(source)
            configs = [(c, [o]) for c in compilers for o in ("-O0", "-O2")]
            configs.append((compilers[1], ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]))
            for i, (compiler, flags) in enumerate(configs):
                p = subprocess.run([compiler, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", *flags,
                                    root / "check.c", "-o", root / f"check-{i}"], capture_output=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                p = subprocess.run([root / f"check-{i}"], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
            print("wide compiled checks:", len(checks), "outputs x", len(vectors), "vectors x", len(configs), "builds", flush=True)

    def test_graph_shapes_and_corruption_controls(self):
        export = {"function": "f", "arity": 2, "nodes": [{"size":4,"input":True,"parameter":0},
                  {"size":4,"input":True,"parameter":1}, {"size":8}, {"size":8,"constant":"3"},
                  {"size":4}, {"size":8,"constant":"0"}], "operations": [
                  {"opcode":"PIECE","inputs":[0,1],"output":2},
                  {"opcode":"SUBPIECE","inputs":[2,3],"output":4}, {"opcode":"RETURN","inputs":[5,4]}]}
        with directory("controls") as root:
            (root / "reference.c").write_text("unsigned int f(unsigned int x,unsigned int y){return (x<<8u)|(y>>24u);}\n")
            for wrong in (False, True):
                candidate = copy.deepcopy(export)
                if wrong: candidate["operations"][0]["inputs"].reverse()
                (root / "candidate.c").write_text(reconstruct(candidate))
                result = subprocess.run([TOOL, "verify", root / "reference.c", root / "candidate.c"], capture_output=True)
                self.assertEqual(result.returncode, 3 if wrong else 0, result.stderr)
        for size in (3, 7, 9, 17):
            bad = copy.deepcopy(export); bad["nodes"][2]["size"] = size
            with self.assertRaises(Unsupported): reconstruct(bad)
        for opcode in ("CALLOTHER", "LOAD", "STORE"):
            bad = copy.deepcopy(export); bad["operations"][0]["opcode"] = opcode
            with self.assertRaises(Unsupported): reconstruct(bad)
        bad = copy.deepcopy(export); bad["nodes"][3]["constant"] = "7"
        with self.assertRaises(Unsupported): reconstruct(bad)

    def test_wide_merges_and_signed_shift_controls(self):
        # Parallel edges deliberately distinguish phi slots from predecessor IDs.
        nodes = [{"size":4,"input":True,"parameter":0}, {"size":4,"input":True,"parameter":1},
                 {"size":8}, {"size":8}, {"size":1}, {"size":8},
                 {"size":8,"constant":"4"}, {"size":4}, {"size":8,"constant":"0"}]
        operations = [{"block":0,"opcode":"PIECE","inputs":[0,1],"output":2},
                      {"block":0,"opcode":"PIECE","inputs":[1,0],"output":3},
                      {"block":0,"opcode":"INT_LESS","inputs":[0,1],"output":4},
                      {"block":0,"opcode":"CBRANCH","inputs":[8,4]},
                      {"block":1,"opcode":"MULTIEQUAL","inputs":[2,3],"output":5},
                      {"block":1,"opcode":"SUBPIECE","inputs":[5,6],"output":7},
                      {"block":1,"opcode":"RETURN","inputs":[8,7]}]
        graph = {"schema_version":2,"function":"f","arity":2,"entry_block":0,"nodes":nodes,"operations":operations,
                 "blocks":[{"id":0,"operations":[0,1,2,3],"incoming":[],
                            "outgoing":[{"block":1,"reverse_index":0},{"block":1,"reverse_index":1}]},
                           {"id":1,"operations":[4,5,6],"incoming":[{"block":0,"reverse_index":0},{"block":0,"reverse_index":1}],"outgoing":[]}]}
        with directory("wide-graph-controls") as root:
            reference = root / "reference.c"; candidate = root / "candidate.c"
            reference.write_text("unsigned int f(unsigned int x,unsigned int y){return x<y?y:x;}\n")
            for wrong in (False, True):
                g = copy.deepcopy(graph)
                if wrong: g["operations"][4]["inputs"].reverse()
                candidate.write_text(reconstruct(g))
                p = subprocess.run([TOOL,"verify",reference,candidate],capture_output=True)
                self.assertEqual(p.returncode,3 if wrong else 0,p.stderr)
            signed = {"function":"f","arity":2,"nodes":[nodes[0],nodes[1],{"size":8},
                      {"size":8,"constant":"64"},{"size":8},{"size":8,"constant":"0"},{"size":4}],
                      "operations":[{"opcode":"PIECE","inputs":[0,1],"output":2},
                                    {"opcode":"INT_SRIGHT","inputs":[2,3],"output":4},
                                    {"opcode":"SUBPIECE","inputs":[4,5],"output":6},
                                    {"opcode":"RETURN","inputs":[5,6]}]}
            reference.write_text("unsigned int f(unsigned int x,unsigned int y){(void)y;return 0u-(x>>31u);}\n")
            for wrong in (False, True):
                g=copy.deepcopy(signed)
                if wrong:g["operations"][1]["opcode"]="INT_RIGHT"
                candidate.write_text(reconstruct(g))
                p=subprocess.run([TOOL,"verify",reference,candidate],capture_output=True)
                self.assertEqual(p.returncode,3 if wrong else 0,p.stderr)


if __name__ == "__main__":
    unittest.main()
