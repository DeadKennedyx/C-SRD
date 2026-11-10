"""Test reconstruction semantics and fail-closed controls without requiring Ghidra.

Set CSRD_GHIDRA_HEADLESS to run the real decompiler integration as well.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from pcode_reconstruct import reconstruct, Unsupported
from audit_decompiler import run_headless
from audit_protection import AuditError
TOOL = str(Path(sys.argv.pop(1)).resolve())


def graph(opcode="INT_MULT", constant=3):
    return {"function": "f", "arity": 1,
            "nodes": [{"size": 4, "input": True, "parameter": 0},
                      {"size": 4, "constant": str(constant)}, {"size": 4},
                      {"size": 8, "constant": "0"}],
            "operations": [{"opcode": opcode, "inputs": [0, 1], "output": 2},
                           {"opcode": "RETURN", "inputs": [3, 2]}]}


class Decompiler(unittest.TestCase):
    def test_timeout_is_retained_and_child_group_is_terminated(self):
        report = {"commands": []}
        with self.assertRaises(AuditError):
            run_headless(report, [sys.executable, "-c",
                         "import subprocess,time; print('started',flush=True); subprocess.Popen(['sleep','30']); time.sleep(30)"], 0.1)
        self.assertEqual(report["commands"][0]["status"], "timeout")
        self.assertIn("started", report["commands"][0]["stdout"])
        self.assertLess(report["commands"][0]["elapsed_seconds"], 5)

    def test_reconstructed_unsigned_rules_prove_and_mutations_fail(self):
        cases = [(graph(), "3u*x"), (graph("INT_ADD", 4294967295), "x-1u"),
                 (graph("INT_RIGHT", 32), "0u"), (graph("INT_LEFT", 31), "x<<31u")]
        comparison = graph("INT_LESS", 5)
        comparison["nodes"][2]["size"] = 1
        comparison["nodes"].append({"size": 4})
        comparison["operations"].insert(1, {"opcode": "INT_ZEXT", "inputs": [2], "output": 4})
        comparison["operations"][-1]["inputs"][1] = 4
        cases.append((comparison, "x<5u"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for export, expression in cases:
                (root / "recovered.c").write_text(reconstruct(export))
                (root / "reference.c").write_text(f"unsigned int f(unsigned int x){{(void)x;return {expression};}}\n")
                result = subprocess.run([TOOL, "verify", root / "reference.c", root / "recovered.c"], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            (root / "recovered.c").write_text(reconstruct(graph(constant=4)))
            (root / "reference.c").write_text("unsigned int f(unsigned int x){return 3u*x;}\n")
            result = subprocess.run([TOOL, "verify", root / "reference.c", root / "recovered.c",
                                     "--report", root / "proof.json"], capture_output=True)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(json.loads((root / "proof.json").read_text())["functions"][0]["verification"], "counterexample")

    def test_unsupported_is_never_reported_as_recovered(self):
        cases = []
        for opcode in ("LOAD", "MULTIEQUAL", "CALLOTHER"):
            cases.append(graph(opcode))
        cycle = graph(); cycle["operations"][0]["inputs"][0] = 2; cases.append(cycle)
        wide = graph(); wide["nodes"][0]["size"] = 8; cases.append(wide)
        side_effect = graph(); side_effect["operations"].append({"opcode": "STORE", "inputs": []}); cases.append(side_effect)
        for export in cases:
            with self.subTest(export=export), self.assertRaises(Unsupported):
                reconstruct(export)

    @unittest.skipUnless(os.environ.get("CSRD_GHIDRA_HEADLESS"), "live Ghidra not configured")
    def test_real_binary_reconstruction_and_missing_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {"schema_version": 1,
                        "cases": [{"id": "calculate", "source": "benchmarks/arithmetic/calculate.c",
                                   "family": "linear", "split": "development"}],
                        "profiles": [{"id": "clang-O2", "compiler": "clang", "optimization": "O2", "tiers": ["core"]}]}
            (root / "manifest.json").write_text(json.dumps(manifest))
            compiler = shutil.which("clang-18") or shutil.which("clang")
            objdump = shutil.which("llvm-objdump-18") or shutil.which("llvm-objdump") or "/opt/homebrew/opt/llvm/bin/llvm-objdump"
            subprocess.run([sys.executable, ROOT / "tools/run_matrix.py", "--matrix", root / "manifest.json",
                            "--csrd", TOOL, "--compiler", "clang=" + compiler, "--objdump", objdump,
                            "--strategies", "identity", "affine", "--inputs", "4", "--iterations", "1000",
                            "--repetitions", "3", "--output-dir", root / "matrix"], check=True, capture_output=True)
            argv = [sys.executable, ROOT / "tools/audit_decompiler.py", "--matrix-report", root / "matrix/matrix.json",
                    "--csrd", TOOL, "--headless", os.environ["CSRD_GHIDRA_HEADLESS"]]
            result = subprocess.run([*argv, "--output-dir", root / "audit"], capture_output=True, text=True, timeout=300)
            report = json.loads((root / "audit/decompiler.json").read_text())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr + str(report.get("summary")))
            self.assertEqual(report["summary"], {"recovered-under-source-model": 3})
            for record in report["observations"]:
                self.assertEqual(record["negative_control"]["verification"], "counterexample")
            matrix = json.loads((root / "matrix/matrix.json").read_text())
            matrix["cases"][0]["function"] = "absent_symbol"
            (root / "matrix/matrix.json").write_text(json.dumps(matrix))
            subprocess.run([*argv, "--variant", "original", "--output-dir", root / "missing"], check=True, capture_output=True, timeout=150)
            self.assertEqual(json.loads((root / "missing/decompiler.json").read_text())["summary"], {"missing-function": 1})


if __name__ == "__main__":
    unittest.main()
