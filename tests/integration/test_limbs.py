"""Reparse and prove emitted limb C, then execute it under real C compilers."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = str(Path(sys.argv.pop(1)).resolve())
sys.path.insert(0, str(ROOT / "tests/differential"))
from run import execute, compilers, harness


class Limbs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_all_operations_reparse_prove_and_execute(self):
        bodies = ["return x+y;", "return x-y;", "return ~x;", "return x&y;", "return x|y;", "return x^y;"]
        bodies += [f"return x*{k}u;" for k in (0, 1, 3, 65535, 65536, 65537, 0x80000001, 0xffffffff)]
        bodies += [f"return x {op} {n}u;" for op in ("<<", ">>") for n in range(32)]
        bodies += [f"return x {op} y;" for op in ("==", "!=", "<", "<=", ">", ">=")]
        bodies += ["return x ? y : 4294967295u;",
                   "const uint32_t t[4]={0u,65535u,65536u,4294967295u}; return t[x&3u]+y;",
                   "for(uint32_t i=0u;i<3u;++i){x=(x+y)^17u;} return x;",
                   "uint32_t z=x+y; return (z*3u)^((z-y)>>17u);"]
        names = [f"f{i}" for i in range(len(bodies))]
        source = self.root / "original.c"
        source.write_text("#include <stdint.h>\n" + "\n".join(
            f"uint32_t {name}(uint32_t x,uint32_t y){{(void)y;{body}}}" for name, body in zip(names, bodies)) + "\n")
        candidate, manifest = self.root / "candidate.c", self.root / "manifest.json"
        execute([TOOL, "transform", source, "-o", candidate, "--strategy", "limbs16",
                 "--timeout-ms", "10000", "--report", manifest])
        functions = json.loads(manifest.read_text())["functions"]
        self.assertEqual(len(functions), len(names))
        self.assertTrue(all(f["verification"] == "proved-under-model" for f in functions))
        self.assertTrue(all(f["planner_status"] == "fixed-representation" for f in functions))
        self.assertEqual(sum(f["internal_conversions"] for f in functions), 1)
        for f in functions:
            self.assertFalse(f["seed_affects_representation"])
            self.assertNotIn("a", f)
            self.assertTrue(all(n["representation"] == "limbs16-u32" for n in f["graph"]))
        driver = self.root / "driver.c"; driver.write_text(harness(names))
        for compiler, _, _ in compilers():
            for options in (["-O0"], ["-O2"], ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]):
                flags = ["-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Wconversion", "-Werror", *options]
                for prefix, path in (("original", source), ("variant", candidate)):
                    execute([compiler, *flags, *[f"-D{n}={prefix}_{n}" for n in names], "-c", path,
                             "-o", self.root / (prefix + ".o")])
                execute([compiler, *flags, driver, self.root / "original.o", self.root / "variant.o",
                         "-o", self.root / "compare"])
                execute([self.root / "compare"])

    def test_seed_independence_names_and_unsupported_composition(self):
        source = self.root / "original.c"
        source.write_text("#include <stdint.h>\n#define csrd_limb_0 1u\n"
                          "uint32_t f(uint32_t csrd_limb_1,uint32_t y){return csrd_limb_1+y;}\n")
        outputs = []
        for seed in (0, 42):
            target = self.root / f"out{seed}.c"
            execute([TOOL, "transform", source, "-o", target, "--strategy", "limbs16", "--seed", str(seed)])
            outputs.append(target.read_text())
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("unsigned int csrd_limb_2", outputs[0])
        mutant, report = self.root / "mutant.c", self.root / "mutant.json"
        mutant.write_text(outputs[0].replace(" & 65535u)", " & 65534u)", 1))
        subprocess.run([TOOL, "verify", str(source), str(mutant), "--report", str(report)],
                       text=True, capture_output=True, timeout=30)
        self.assertEqual(json.loads(report.read_text())["functions"][0]["verification"], "counterexample")
        target = self.root / "unsupported.c"
        result = subprocess.run([TOOL, "transform", str(source), "-o", str(target), "--strategy", "limbs16",
                                 "--control-flow", "split-scale"], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --control-flow none", result.stderr)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
