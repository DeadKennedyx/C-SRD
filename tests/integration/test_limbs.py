"""Reparse and prove emitted limb C, then execute it under real C compilers."""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = str(Path(sys.argv.pop(1)).resolve())
sys.path.insert(0, str(ROOT / "tests/differential"))
from run import execute, compilers, harness, EDGES


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
        self.assertTrue(all(f["proof"]["solver_strategy"] == "compositional-limbs16" for f in functions),
                        [(f["function"], f["proof"]["solver_strategy"]) for f in functions
                         if f["proof"]["solver_strategy"] != "compositional-limbs16"])
        self.assertTrue(all(f["planner_status"] == "fixed-representation" for f in functions))
        self.assertEqual(sum(f["internal_conversions"] for f in functions), 1)
        for f in functions:
            self.assertFalse(f["seed_affects_representation"])
            self.assertNotIn("a", f)
            self.assertTrue(all(n["representation"] == "limbs16-u32" for n in f["graph"]))
        driver = self.root / "driver.c"
        driver.write_text(harness(names, EDGES + [65534, 65535, 65536, 65537]))
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

    def test_jenkins_composes_and_independent_verifier_rebinds_locals(self):
        source = ROOT / "benchmarks/rich/development/jenkins_word.c"
        candidate, manifest = self.root / "candidate.c", self.root / "transform.json"
        execute([TOOL, "transform", source, "-o", candidate, "--strategy", "limbs16",
                 "--timeout-ms", "10000", "--report", manifest])
        proof = json.loads(manifest.read_text())["functions"][0]["proof"]
        self.assertEqual(proof["solver_strategy"], "compositional-limbs16")
        self.assertEqual(proof["steps"][0]["label"], "source-to-graph")
        self.assertEqual(proof["steps"][-1]["label"], "emitted-return")
        self.assertEqual(len(proof["steps"]), len(proof["composition"]["graph"]) + 2)
        self.assertTrue(all(s["status"] == "proved-under-model" for s in proof["steps"]))
        for step in proof["steps"]:
            self.assertEqual(step["obligation_sha256"], hashlib.sha256(step["smtlib"].encode()).hexdigest())
            if shutil.which("z3"):
                result = subprocess.run(["z3", "-in", "-T:10"], input=step["smtlib"],
                                        text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "unsat")
        # Candidate identifiers and parameter spellings are not trusted hints.
        candidate.write_text(candidate.read_text().replace("csrd_limb_", "renamed_piece_")
                             .replace("state", "arg_a").replace("word", "arg_b"))
        independent = self.root / "independent.json"
        execute([TOOL, "verify", source, candidate, "--timeout-ms", "10000", "--report", independent])
        report = json.loads(independent.read_text())
        self.assertEqual(report["functions"][0]["proof"]["solver_strategy"], "compositional-limbs16")
        self.assertEqual(report["candidate_sha256"], hashlib.sha256(candidate.read_bytes()).hexdigest())
        self.assertTrue(all(n.startswith("renamed_piece_") for n in
                            report["functions"][0]["proof"]["composition"]["declarations"]))
        driver = self.root / "driver.c"
        driver.write_text(harness(["kernel"], EDGES + [65534, 65535, 65536, 65537]))
        for compiler, _, _ in compilers():
            for flags in (["-O0"], ["-O2"], ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]):
                common = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags]
                for prefix, path in (("original", source), ("variant", candidate)):
                    execute([*common, f"-Dkernel={prefix}_kernel", "-c", path, "-o", self.root / (prefix + ".o")])
                execute([*common, driver, self.root / "original.o", self.root / "variant.o", "-o", self.root / "compare"])
                execute([self.root / "compare"])

    def test_equal_decode_does_not_establish_piece_range(self):
        source, candidate, report = self.root / "original.c", self.root / "candidate.c", self.root / "proof.json"
        source.write_text("#include <stdint.h>\nuint32_t f(uint32_t x){return x;}\n")
        execute([TOOL, "transform", source, "-o", candidate, "--strategy", "limbs16"])
        # The extra bit overlaps the high half at the return: the full function
        # is still equal, but a local proof must NOT assume this piece is u16.
        candidate.write_text(candidate.read_text().replace("65535u", "131071u", 1))
        execute([TOOL, "verify", source, candidate, "--report", report])
        proof = json.loads(report.read_text())["functions"][0]["proof"]
        self.assertEqual(proof["status"], "proved-under-model")  # independent whole-function fallback
        self.assertNotEqual(proof["solver_strategy"], "compositional-limbs16")
        attempt = proof["prior_attempts"][0]
        self.assertEqual(attempt["status"], "inconclusive")
        self.assertEqual(attempt["steps"][-1]["status"], "local-counterexample")
        self.assertIn("x", attempt["steps"][-1]["local_countermodel"])


if __name__ == "__main__":
    unittest.main()
