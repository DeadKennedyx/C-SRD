"""Validate actual 4/8-bit positional C and independent compiler executions."""
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = str(Path(sys.argv.pop(1)).resolve())
sys.path.insert(0, str(ROOT / "tests/differential"))
from run import execute, compilers, harness, EDGES


class Positional(unittest.TestCase):
    def check_proof_queries(self, node):
        if "smtlib" in node:
            self.assertEqual(hashlib.sha256(node["smtlib"].encode()).hexdigest(), node["obligation_sha256"])
            if shutil.which("z3"):
                p = subprocess.run(["z3", "-in", "-T:10"], input=node["smtlib"], text=True, capture_output=True, timeout=15)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout.strip(), "unsat")
        else:
            self.assertTrue(node.get("steps"), "proof without a query or checked composition")
        for step in node.get("steps", []):
            self.check_proof_queries(step)

    def test_all_operations_prove_and_execute(self):
        bodies = ["return x+y;", "return x-y;", "return ~x;", "return x&y;", "return x|y;", "return x^y;"]
        factors = [0, 1, 3, 15, 16, 17, 255, 256, 257, 65535, 65536, 65537, 0x80000001, 0xffffffff]
        factors += [random.Random(8991 + i).getrandbits(32) for i in range(4)]
        bodies += [f"return x*{k}u;" for k in factors]
        bodies += [f"return x {op} {n}u;" for op in ("<<", ">>") for n in range(32)]
        bodies += [f"return x {op} y;" for op in ("==", "!=", "<", "<=", ">", ">=")]
        bodies += ["return x ? y : 4294967295u;",
                   "const uint32_t t[4]={0u,255u,65536u,4294967295u}; return t[x&3u]+y;",
                   "for(uint32_t i=0u;i<3u;++i){x=(x+y)^17u;} return x;",
                   "uint32_t z=x+y; return (z*3u)^((z-y)>>17u);"]
        names = [f"f{i}" for i in range(len(bodies))]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "original.c"
            source.write_text("#include <stdint.h>\n" + "\n".join(
                f"uint32_t {name}(uint32_t x,uint32_t y){{(void)y;{body}}}" for name, body in zip(names, bodies)) + "\n")
            driver = root / "driver.c"
            edges = EDGES + [14, 15, 16, 17, 254, 255, 256, 257, 65534, 65535, 65536, 65537]
            driver.write_text(harness(names, edges))
            for bits in (8, 4):
                with self.subTest(bits=bits):
                    candidate, manifest = root / f"candidate{bits}.c", root / f"manifest{bits}.json"
                    p = execute([TOOL, "transform", source, "-o", candidate, "--strategy", f"limbs{bits}",
                                 "--timeout-ms", "10000", "--report", manifest])
                    functions = json.loads(manifest.read_text())["functions"]
                    self.assertEqual(len(functions), len(names), p.stderr)
                    self.assertTrue(all(f["verification"] == "proved-under-model" for f in functions))
                    self.assertEqual(sum(f["internal_conversions"] for f in functions), 1)
                    for f in functions:
                        self.assertFalse(f["seed_affects_representation"])
                        self.assertNotIn("a", f)
                        self.assertTrue(all(n["representation"] == f"limbs{bits}-u32" for n in f["graph"]))
                        proof = f["proof"]
                        self.assertIn("composition", proof)
                        width = proof["composition"]["piece_bits"]
                        if f["operations_transformed"]:
                            self.assertEqual(width, bits)
                        self.assertTrue(all(len(c["pieces"]) == 32 // width for c in proof["composition"]["checkpoints"]))
                        self.assertTrue(all(s["status"] == "proved-under-model" for s in proof["steps"]))
                    for compiler, _, _ in compilers():
                        for options in (["-O0"], ["-O2"], ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]):
                            flags = ["-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Wconversion", "-Werror", *options]
                            for prefix, path in (("original", source), ("variant", candidate)):
                                execute([compiler, *flags, *[f"-D{n}={prefix}_{n}" for n in names], "-c", path,
                                         "-o", root / (prefix + ".o")])
                            execute([compiler, *flags, driver, root / "original.o", root / "variant.o", "-o", root / "compare"])
                            execute([root / "compare"])

    def test_seed_collision_corruption_and_composition_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "original.c"
            source.write_text("#include <stdint.h>\n#define csrd_limb_0 1u\n"
                              "uint32_t f(uint32_t csrd_limb_1,uint32_t y){return csrd_limb_1-y;}\n")
            for bits in (8, 4):
                outputs = []
                for seed in (0, 42):
                    target = root / f"candidate{bits}-{seed}.c"
                    execute([TOOL, "transform", source, "-o", target, "--strategy", f"limbs{bits}", "--seed", seed])
                    outputs.append(target.read_text())
                self.assertEqual(*outputs)
                self.assertIn("unsigned int csrd_limb_2", outputs[0])
                mutant, report = root / "mutant.c", root / "proof.json"
                mask = (1 << bits) - 1
                mutant.write_text(outputs[0].replace(f" & {mask}u)", f" & {mask-1}u)", 1))
                p = subprocess.run([TOOL, "verify", source, mutant, "--report", report], capture_output=True, timeout=30)
                self.assertEqual(p.returncode, 3, p.stderr)
                self.assertEqual(json.loads(report.read_text())["functions"][0]["verification"], "counterexample")
                target = root / "unsupported.c"
                p = subprocess.run([TOOL, "transform", source, "-o", target, "--strategy", f"limbs{bits}",
                                    "--control-flow", "split-scale"], capture_output=True, timeout=30)
                self.assertNotEqual(p.returncode, 0)
                self.assertFalse(target.exists())

    def test_jenkins_uses_checked_width_and_rebound_declarations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = ROOT / "benchmarks/rich/development/jenkins_word.c"
            for bits in (8, 4):
                candidate, report = root / f"candidate{bits}.c", root / f"proof{bits}.json"
                execute([TOOL, "transform", source, "-o", candidate, "--strategy", f"limbs{bits}", "--report", report])
                proof = json.loads(report.read_text())["functions"][0]["proof"]
                self.assertEqual(proof["solver_strategy"], f"compositional-limbs{bits}")
                self.assertEqual(proof["composition"]["piece_bits"], bits)
                self.assertEqual(len(proof["steps"]), len(proof["composition"]["graph"]) + 2)
                self.check_proof_queries(proof)
                candidate.write_text(candidate.read_text().replace("csrd_limb_", "independent_name_")
                                     .replace("state", "arg_a").replace("word", "arg_b"))
                execute([TOOL, "verify", source, candidate, "--report", report])
                proof = json.loads(report.read_text())["functions"][0]["proof"]
                self.assertEqual(proof["solver_strategy"], f"compositional-limbs{bits}")
                self.assertTrue(all(n.startswith("independent_name_") for n in proof["composition"]["declarations"]))

    def test_dense_scale_microcontracts_replay_and_rebind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "original.c"
            # These constants exposed timeouts in the first full-word proof.
            for bits, factor in ((8, 3521782525), (4, 2186250713)):
                source.write_text(f"#include <stdint.h>\nuint32_t f(uint32_t x){{return x*{factor}u;}}\n")
                candidate, report = root / "candidate.c", root / "proof.json"
                execute([TOOL, "transform", source, "-o", candidate, "--strategy", f"limbs{bits}", "--report", report])
                proof = json.loads(report.read_text())["functions"][0]["proof"]
                self.assertEqual(proof["solver_strategy"], f"compositional-limbs{bits}")
                step = next(s for s in proof["steps"] if s["solver_strategy"] == "positional-scale-composition")
                self.assertEqual(len(step["steps"]), 32 // bits + 1)
                self.assertEqual(step["steps"][-1]["label"], "telescoping-word-bridge")
                self.check_proof_queries(proof)
                candidate.write_text(candidate.read_text().replace("csrd_limb_", "rebound_"))
                execute([TOOL, "verify", source, candidate, "--report", report])
                proof = json.loads(report.read_text())["functions"][0]["proof"]
                self.assertEqual(proof["solver_strategy"], f"compositional-limbs{bits}")
                carries = proof["composition"]["checkpoints"][-1]["scale_steps"]
                self.assertTrue(all(s["carry"]["declaration"].startswith("rebound_") for s in carries[:-1]))
                self.assertEqual(carries[-1]["carry"], {"constant": 0})

    def test_piece_range_is_not_assumed_from_equal_final_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "original.c"
            source.write_text("#include <stdint.h>\nuint32_t f(uint32_t x){return x;}\n")
            for bits in (8, 4):
                candidate, report = root / f"candidate{bits}.c", root / f"proof{bits}.json"
                execute([TOOL, "transform", source, "-o", candidate, "--strategy", f"limbs{bits}"])
                mask = (1 << bits) - 1
                candidate.write_text(candidate.read_text().replace(f"{mask}u", f"{2*mask+1}u", 1))
                execute([TOOL, "verify", source, candidate, "--report", report])
                proof = json.loads(report.read_text())["functions"][0]["proof"]
                self.assertEqual(proof["status"], "proved-under-model")
                self.assertNotEqual(proof["solver_strategy"], f"compositional-limbs{bits}")
                attempt = next(p for p in proof["prior_attempts"] if p["solver_strategy"] == f"compositional-limbs{bits}")
                self.assertEqual(attempt["steps"][-1]["status"], "local-counterexample")


if __name__ == "__main__":
    unittest.main()
