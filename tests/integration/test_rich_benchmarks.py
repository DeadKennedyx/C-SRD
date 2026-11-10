"""Execute the independent corpus grader and exercise its failure controls."""
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
TOOL = str(Path(sys.argv.pop(1)).resolve())


class RichBenchmarks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clang = next((shutil.which(p) for p in [os.environ.get("CSRD_MATRIX_CLANG", ""),
            "/opt/homebrew/opt/llvm/bin/clang", "clang-18", "clang"] if p and shutil.which(p)), None)
        self.gcc = next((shutil.which(p) for p in [os.environ.get("CSRD_GCC", ""),
            "gcc-16", "gcc-14", "gcc-13", "gcc"] if p and shutil.which(p)), None)
        if not self.clang or not self.gcc:
            raise RuntimeError("GCC and Clang are required for corpus validation")
        self.manifest = json.loads((ROOT / "experiments/rich-benchmarks.json").read_text())

    def validate(self, manifest=None, expected=0, extra=()):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest or self.manifest))
        result = subprocess.run([sys.executable, str(ROOT / "tools/validate_benchmarks.py"),
            "--manifest", str(path), "--csrd", TOOL, "--compiler", "clang=" + self.clang,
            "--compiler", "gcc=" + self.gcc, "--inputs", "16", "--output-dir", str(self.root / "out"),
            *extra], text=True, capture_output=True, timeout=240)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_full_corpus_controls_and_rare_false_fingerprints(self):
        self.validate()
        report = json.loads((self.root / "out/validation.json").read_text())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["records"]), 52)
        self.assertEqual(len(report["proofs"]), 5)
        self.assertEqual({p["result"]["verification"] for p in report["proofs"]},
                         {"proved-under-model", "counterexample"})
        self.assertTrue(all(r["oracle_mismatches"] == 0 for r in report["records"] if r["relation"] == "equivalent"))
        self.assertTrue(all(r["oracle_mismatches"] > 0 for r in report["records"] if r["relation"] == "different"))
        self.assertEqual(report["fingerprint_confusion"],
                         {"false-positive": 8, "true-positive": 12, "true-negative": 148})
        before = (self.root / "out/validation.json").read_bytes()
        self.validate(expected=2)
        self.assertEqual(before, (self.root / "out/validation.json").read_bytes())
        self.assertFalse((self.root / "out/failure.json").exists())

    def test_oracle_detects_fault_in_original_before_any_candidate(self):
        manifest = copy.deepcopy(self.manifest)
        case = next(c for c in manifest["cases"] if c["id"] == "crc32_byte")
        case["source"] = "benchmarks/rich/controls/crc32_wrong_polynomial.c"
        case["controls"] = []
        result = self.validate(manifest, expected=1, extra=("--case", "crc32_byte"))
        self.assertIn("oracle mismatch", result.stderr)

    def test_declared_negative_witness_must_really_differ(self):
        manifest = copy.deepcopy(self.manifest)
        case = next(c for c in manifest["cases"] if c["id"] == "rgb_luma8")
        case["controls"] = [next(c for c in case["controls"] if c["relation"] == "different")]
        case["controls"][0]["witness"] = [0]
        result = self.validate(manifest, expected=1, extra=("--case", "rgb_luma8"))
        self.assertIn("negative control lacks its declared compiled counterexample", result.stderr)


if __name__ == "__main__":
    unittest.main()
