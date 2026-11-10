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
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from pcode_reconstruct import reconstruct, Unsupported
from audit_decompiler import run_headless, scoring_reference, run as run_audit
from audit_protection import AuditError, file_hash
TOOL = str(Path(sys.argv.pop(1)).resolve())


def graph(opcode="INT_MULT", constant=3):
    return {"function": "f", "arity": 1,
            "nodes": [{"size": 4, "input": True, "parameter": 0},
                      {"size": 4, "constant": str(constant)}, {"size": 4},
                      {"size": 8, "constant": "0"}],
            "operations": [{"opcode": opcode, "inputs": [0, 1], "output": 2},
                           {"opcode": "RETURN", "inputs": [3, 2]}]}


class Decompiler(unittest.TestCase):
    def test_changed_frontend_is_rejected_before_decompilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix = root / "matrix.json"
            matrix.write_text(json.dumps({"status": "completed", "tools": {"csrd": {"sha256": "wrong"}}}))
            args = SimpleNamespace(matrix_report=str(matrix), headless=sys.executable, csrd=TOOL,
                                   analysis_seconds=1, decompile_seconds=1, process_seconds=1, timeout_ms=1000)
            result = run_audit(args, root)
            self.assertEqual(result["status"], "failed")
            self.assertIn("frontend/model", result["error"])
            self.assertEqual(result["commands"], [])

    def test_scoring_binds_the_original_frozen_build_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = root / "function.i"
            frozen.write_text("unsigned int f(unsigned int x){return x+1u;}\n")
            original = {"case": "f", "profile": "p", "variant": "original", "status": "completed",
                        "binary": str(root / "program"), "preprocessed_sha256": file_hash(frozen)}
            matrix = {"records": [original]}
            self.assertEqual(scoring_reference(matrix, original), (frozen, file_hash(frozen)))
            frozen.write_text("unsigned int f(unsigned int x){return x+2u;}\n")
            with self.assertRaisesRegex(ValueError, "preprocessed input changed"):
                scoring_reference(matrix, original)

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
                 (graph("INT_SUB", 5), "x-5u"), (graph("INT_AND", 255), "x&255u"),
                 (graph("INT_OR", 255), "x|255u"), (graph("INT_XOR", 255), "x^255u"),
                 (graph("INT_RIGHT", 32), "0u"), (graph("INT_LEFT", 31), "x<<31u")]
        for opcode, count, expected in (("INT_RIGHT", 8, "x>>8u"), ("INT_LEFT", 31, "x<<31u"),
                                        ("INT_RIGHT", 32, "0u"), ("INT_LEFT", 0x100000001, "0u"),
                                        ("INT_RIGHT", 0xffffffffffffffff, "0u")):
            wide_count = graph(opcode, count)
            wide_count["nodes"][1]["size"] = 8
            cases.append((wide_count, expected))
        for code, symbol in (("INT_LESS", "<"), ("INT_LESSEQUAL", "<="),
                             ("INT_EQUAL", "=="), ("INT_NOTEQUAL", "!=")):
            comparison = graph(code, 5)
            comparison["nodes"][2]["size"] = 1
            comparison["nodes"].append({"size": 4})
            comparison["operations"].insert(1, {"opcode": "INT_ZEXT", "inputs": [2], "output": 4})
            comparison["operations"][-1]["inputs"][1] = 4
            cases.append((comparison, f"x{symbol}5u"))
        for code, expected in (("COPY", "x"), ("CAST", "x"), ("INT_NEGATE", "~x"), ("INT_2COMP", "0u-x")):
            unary = graph(code); unary["operations"][0]["inputs"] = [0]
            cases.append((unary, expected))
        for extension, expected in (("INT_ZEXT", "x&255u"), ("INT_SEXT", "((x&255u)^128u)-128u")):
            narrow = graph("SUBPIECE", 0)
            narrow["nodes"][1]["size"] = 8
            narrow["nodes"][2]["size"] = 1
            narrow["nodes"].append({"size": 4})
            narrow["operations"].insert(1, {"opcode": extension, "inputs": [2], "output": 4})
            narrow["operations"][-1]["inputs"][1] = 4
            cases.append((narrow, expected))
        boolean = graph("INT_LESS", 5)
        boolean["nodes"][2]["size"] = 1
        boolean["nodes"] += [{"size": 1}, {"size": 4}]
        boolean["operations"].insert(1, {"opcode": "BOOL_NEGATE", "inputs": [2], "output": 4})
        boolean["operations"].insert(2, {"opcode": "INT_ZEXT", "inputs": [4], "output": 5})
        boolean["operations"][-1]["inputs"][1] = 5
        cases.append((boolean, "x>=5u"))
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
            wrong_count = graph("INT_RIGHT", 9); wrong_count["nodes"][1]["size"] = 8
            (root / "recovered.c").write_text(reconstruct(wrong_count))
            (root / "reference.c").write_text("unsigned int f(unsigned int x){return x>>8u;}\n")
            result = subprocess.run([TOOL, "verify", root / "reference.c", root / "recovered.c",
                                     "--report", root / "wrong-count.json"], capture_output=True)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(json.loads((root / "wrong-count.json").read_text())["functions"][0]["verification"], "counterexample")

    def test_unsupported_is_never_reported_as_recovered(self):
        cases = []
        for opcode in ("LOAD", "MULTIEQUAL", "CALLOTHER"):
            cases.append(graph(opcode))
        cycle = graph(); cycle["operations"][0]["inputs"][0] = 2; cases.append(cycle)
        wide = graph(); wide["nodes"][0]["size"] = 8; cases.append(wide)
        for amount, size in ((-1, 8), (1 << 64, 8), (256, 1), (1, 16)):
            count = graph("INT_RIGHT", amount); count["nodes"][1]["size"] = size; cases.append(count)
        dynamic = graph("INT_RIGHT"); dynamic["operations"][0]["inputs"][1] = 0; cases.append(dynamic)
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
                proof = json.loads((Path(record["export"]["path"]).parent / "verification.json").read_text())
                self.assertEqual(proof["source_sha256"], record["reference_preprocessed_sha256"])
            matrix = json.loads((root / "matrix/matrix.json").read_text())
            matrix["cases"][0]["function"] = "absent_symbol"
            (root / "matrix/matrix.json").write_text(json.dumps(matrix))
            subprocess.run([*argv, "--variant", "original", "--output-dir", root / "missing"], check=True, capture_output=True, timeout=150)
            self.assertEqual(json.loads((root / "missing/decompiler.json").read_text())["summary"], {"missing-function": 1})


if __name__ == "__main__":
    unittest.main()
