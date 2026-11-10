"""Independent small CFG oracles, full-domain C checks and rejection controls."""
import copy
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from pcode_reconstruct import reconstruct, Unsupported

TOOL = str(Path(sys.argv.pop(1)).resolve())
MASK = 0xffffffff


class Fixture:
    def __init__(self):
        self.export = {"schema_version": 2, "function": "f", "arity": 2, "entry_block": 0,
                       "nodes": [], "operations": [], "blocks": []}
        self.x = self.node(parameter=0, input=True)
        self.y = self.node(parameter=1, input=True)
        self.target = self.node(size=8, constant="0")

    def node(self, size=4, **fields):
        result = len(self.export["nodes"])
        self.export["nodes"].append({"size": size, **fields})
        return result

    def block(self):
        bid = len(self.export["blocks"])
        self.export["blocks"].append({"id": bid, "operations": [], "incoming": [], "outgoing": []})
        return bid

    def op(self, block, opcode, inputs, output=None):
        op = {"block": block, "opcode": opcode, "inputs": inputs}
        if output is not None:
            op["output"] = output
        self.export["blocks"][block]["operations"].append(len(self.export["operations"]))
        self.export["operations"].append(op)

    def edge(self, source, dest):
        a, b = self.export["blocks"][source], self.export["blocks"][dest]
        oi, ii = len(a["outgoing"]), len(b["incoming"])
        a["outgoing"].append({"block": dest, "reverse_index": ii})
        b["incoming"].append({"block": source, "reverse_index": oi})


def diamond(a=3, b=5):
    g = Fixture()
    entry, no, yes, join = [g.block() for _ in range(4)]
    ca, cb = g.node(constant=str(a)), g.node(constant=str(b))
    condition, nv, yv, result = g.node(size=1), g.node(), g.node(), g.node()
    g.op(entry, "INT_LESS", [g.x, g.y], condition)
    g.op(entry, "CBRANCH", [g.target, condition])
    g.op(no, "INT_SUB", [g.y, cb], nv); g.op(no, "BRANCH", [g.target])
    g.op(yes, "INT_ADD", [g.x, ca], yv); g.op(yes, "BRANCH", [g.target])
    g.op(join, "MULTIEQUAL", [nv, yv], result)
    g.op(join, "RETURN", [g.target, result])
    for source, dest in ((entry, no), (entry, yes), (no, join), (yes, join)):
        g.edge(source, dest)
    return g.export, f"x<y ? x+{a}u : y-{b}u"


def swap_loop(count=4, dynamic=False):
    g = Fixture()
    entry, loop, end = [g.block() for _ in range(3)]
    n, minus, zero, scale = [g.node(constant=str(v)) for v in (count, MASK, 0, 3)]
    a, b, c, next_c, scaled, result = [g.node() for _ in range(6)]
    condition = g.node(size=1)
    g.op(entry, "BRANCH", [g.target])
    g.op(loop, "MULTIEQUAL", [g.x, b], a)
    g.op(loop, "MULTIEQUAL", [g.y, a], b)
    g.op(loop, "MULTIEQUAL", [g.y if dynamic else n, next_c], c)
    g.op(loop, "INT_ADD", [c, minus], next_c)
    g.op(loop, "INT_NOTEQUAL", [next_c, zero], condition)
    g.op(loop, "CBRANCH", [g.target, condition])
    g.op(end, "INT_MULT", [a, scale], scaled)
    g.op(end, "INT_ADD", [scaled, b], result)
    g.op(end, "RETURN", [g.target, result])
    g.edge(entry, loop); g.edge(loop, end); g.edge(loop, loop)
    return g.export, "3u*x+y" if count % 2 else "3u*y+x"


def parallel_edges():
    g = Fixture()
    entry, join = g.block(), g.block()
    cond, result = g.node(size=1), g.node()
    g.op(entry, "INT_LESS", [g.x, g.y], cond)
    g.op(entry, "CBRANCH", [g.target, cond])
    g.op(join, "MULTIEQUAL", [g.x, g.y], result)
    g.op(join, "RETURN", [g.target, result])
    g.edge(entry, join); g.edge(entry, join)
    return g.export, "x<y ? y : x"


def nested():
    g = Fixture()
    entry, no, test, less, more = [g.block() for _ in range(5)]
    threshold = g.node(constant="5")
    outer, inner = g.node(size=1), g.node(size=1)
    g.op(entry, "INT_LESS", [g.x, g.y], outer)
    g.op(entry, "CBRANCH", [g.target, outer])
    g.op(no, "RETURN", [g.target, g.y])
    g.op(test, "INT_LESS", [g.x, threshold], inner)
    g.op(test, "CBRANCH", [g.target, inner])
    g.op(less, "RETURN", [g.target, threshold])
    g.op(more, "RETURN", [g.target, g.x])
    for a, b in ((entry, no), (entry, test), (test, more), (test, less)):
        g.edge(a, b)
    return g.export, "x<y ? (x<5u ? 5u : x) : y"


def interpret(export, arguments):
    """Concrete edge interpreter; does not use adapter validation/value rules."""
    nodes, ops = export["nodes"], export["operations"]
    env = {i: int(n["constant"]) if "constant" in n else arguments[n["parameter"]]
           for i, n in enumerate(nodes) if "constant" in n or "parameter" in n}
    blocks = {b["id"]: b for b in export["blocks"]}
    current, edge = export["entry_block"], None
    for _ in range(10000):
        block = blocks[current]
        phi = {}
        for oi in block["operations"]:
            op = ops[oi]
            if op["opcode"] == "MULTIEQUAL":
                phi[op["output"]] = env[op["inputs"][edge]]
        env.update(phi)
        successor = 0
        for oi in block["operations"]:
            op = ops[oi]; code = op["opcode"]
            if code == "MULTIEQUAL" or code == "BRANCH":
                continue
            if code == "RETURN":
                return env[op["inputs"][1]]
            if code == "CBRANCH":
                successor = int(env[op["inputs"][1]] != 0)
                continue
            args = [env[v] for v in op["inputs"]]
            if code == "INT_ADD": value = args[0] + args[1]
            elif code == "INT_SUB": value = args[0] - args[1]
            elif code == "INT_MULT": value = args[0] * args[1]
            elif code == "INT_LESS": value = int(args[0] < args[1])
            elif code == "INT_NOTEQUAL": value = int(args[0] != args[1])
            else: raise AssertionError("test oracle does not support " + code)
            env[op["output"]] = value & ((1 << (8 * nodes[op["output"]]["size"])) - 1)
        outgoing = block["outgoing"][successor]
        current, edge = outgoing["block"], outgoing["reverse_index"]
    raise AssertionError("concrete interpreter budget exceeded")


class CFG(unittest.TestCase):
    def fixtures(self):
        return [diamond(), diamond(MASK, MASK), parallel_edges(), nested(),
                swap_loop(1), swap_loop(4), swap_loop(7)]

    def test_full_domain_reconstruction_and_corruption_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for export, expression in self.fixtures():
                with self.subTest(expression=expression):
                    reference, candidate = root / "reference.c", root / "candidate.c"
                    reference.write_text(f"unsigned int f(unsigned int x,unsigned int y){{return {expression};}}\n")
                    candidate.write_text(reconstruct(export))
                    p = subprocess.run([TOOL, "verify", reference, candidate], capture_output=True)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    candidate.write_text(reconstruct(export, result_offset=1))
                    p = subprocess.run([TOOL, "verify", reference, candidate, "--report", root / "proof.json"], capture_output=True)
                    self.assertEqual(p.returncode, 3, p.stderr)
                    self.assertEqual(json.loads((root / "proof.json").read_text())["functions"][0]["verification"], "counterexample")

    def test_compiled_results_match_independent_concrete_interpreter(self):
        fixtures = self.fixtures()
        rng = random.Random(819001)
        values = [0, 1, 4, 5, 255, 65535, 0x7fffffff, 0x80000000, MASK]
        vectors = [(x, y) for x in values for y in values] + [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(128)]
        sources = []
        expected = []
        for i, (export, _) in enumerate(fixtures):
            export = copy.deepcopy(export); export["function"] = "f" + str(i)
            sources.append(reconstruct(export))
            expected.extend(interpret(export, args) for args in vectors)
        calls = "\n".join(f'printf("%u\\n", f{i}({x}u,{y}u));' for i in range(len(fixtures)) for x, y in vectors)
        source = '#include <stdio.h>\n' + "\n".join(sources) + "\nint main(void){\n" + calls + "\nreturn 0;}\n"
        compilers = [shutil.which("gcc-16") or shutil.which("gcc"),
                     shutil.which("clang-18") or shutil.which("clang")]
        self.assertTrue(all(compilers), "GCC and Clang required for CFG output validation")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "check.c").write_text(source)
            configs = [(c, [o]) for c in compilers for o in ("-O0", "-O2")]
            configs.append((compilers[1], ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]))
            for compiler, flags in configs:
                with self.subTest(compiler=compiler, flags=flags):
                    p = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                                        root / "check.c", "-o", root / "check"], capture_output=True)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    p = subprocess.run([root / "check"], capture_output=True, text=True, timeout=10)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual([int(line) for line in p.stdout.splitlines()], expected)

    def test_parallel_edge_mutation_is_not_equivalent(self):
        export, _ = parallel_edges()
        mutant = copy.deepcopy(export)
        mutant["operations"][2]["inputs"].reverse()
        self.assertNotEqual(interpret(export, (1, 8)), interpret(mutant, (1, 8)))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.c").write_text(reconstruct(export))
            (root / "b.c").write_text(reconstruct(mutant))
            p = subprocess.run([TOOL, "verify", root / "a.c", root / "b.c"], capture_output=True)
            self.assertEqual(p.returncode, 3, p.stderr)

    def test_merge_simultaneity_and_expansion_metrics(self):
        export, _ = swap_loop(4)
        metrics = {}
        reconstruct(export, metrics=metrics)
        self.assertEqual(metrics["block_expansions"], 6)
        self.assertEqual(metrics["constant_branches"], 4)
        self.assertEqual(metrics["terminal_paths"], 1)
        export["blocks"][1]["operations"][:2] = reversed(export["blocks"][1]["operations"][:2])
        self.assertEqual(reconstruct(export), reconstruct(swap_loop(4)[0]))
        reconstruct(nested()[0], metrics=metrics)
        self.assertEqual(metrics["terminal_paths"], 3)
        self.assertEqual(metrics["symbolic_branches"], 2)

    def test_nontermination_and_unknown_loop_exhaustion_reject_whole_answer(self):
        for count, dynamic in ((0, False), (65, False), (4, True)):
            with self.subTest(count=count, dynamic=dynamic), self.assertRaisesRegex(Unsupported, "budget"):
                reconstruct(swap_loop(count, dynamic)[0])

    def test_bad_metadata_and_semantics_fail_closed(self):
        original, _ = diamond()
        changes = [
            lambda e: e.pop("blocks"),
            lambda e: e.update(schema_version=1),
            lambda e: e.update(entry_block=-1),
            lambda e: e["blocks"][0]["outgoing"][0].update(reverse_index=-1),
            lambda e: e["blocks"][0]["outgoing"][0].update(block=999),
            lambda e: e["blocks"][1]["incoming"][0].update(reverse_index=1),
            lambda e: e["blocks"][3]["operations"].reverse(),
            lambda e: e["blocks"][0]["operations"].append(2),
            lambda e: e["blocks"].append(copy.deepcopy(e["blocks"][1])),
            lambda e: e["operations"][0]["inputs"].__setitem__(0, -1),
            lambda e: e["operations"][0].update(output=0),
            lambda e: e["operations"][2].update(output=4),
            lambda e: e["operations"][0].update(opcode="CALL"),
            lambda e: e["operations"][2].update(opcode="LOAD"),
            lambda e: e["operations"][2]["inputs"].__setitem__(0, e["operations"][4]["output"]),
            lambda e: e["operations"][6]["inputs"].reverse(),
            lambda e: e["operations"][6]["inputs"].pop(),
            lambda e: e["nodes"][0].update(parameter=-1),
            lambda e: e["nodes"][3].update(constant="4294967296"),
            lambda e: e["nodes"][5].update(size=4),
            lambda e: e["operations"][0].update(opcode="INT_NEGATE"),
        ]
        for i, change in enumerate(changes):
            export = copy.deepcopy(original); change(export)
            with self.subTest(control=i), self.assertRaises(Unsupported):
                reconstruct(export)
        # Even a syntactically unreachable operation with an effect is rejected.
        export = copy.deepcopy(original)
        export["operations"].append({"opcode": "STORE", "inputs": []})
        with self.assertRaises(Unsupported): reconstruct(export)


if __name__ == "__main__":
    unittest.main()
