import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import evaluate
import synthesize_rules
TOOL = str(Path(sys.argv.pop(1)).resolve())


class Evaluation(unittest.TestCase):
    def test_finite_fingerprints_have_explicit_false_matches(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); driver = root / "driver.c"; driver.write_text(evaluate.DRIVER)
            records = []
            cases = json.loads((ROOT / "benchmarks/corpus.json").read_text())["cases"]
            for index, case in enumerate(cases):
                binary = root / str(index)
                evaluate.command([compiler, "-std=c11", "-O2", ROOT / "benchmarks" / case["source"], driver, "-o", binary])
                records.append({**case, "discovery": evaluate.fingerprint(binary, evaluate.inputs(20261108, 64)),
                                "heldout": evaluate.fingerprint(binary, evaluate.inputs(20261109, 64, True))})
            discovery, heldout = evaluate.score(records, "discovery"), evaluate.score(records, "heldout")
            self.assertEqual(discovery["false_positive"], 2)
            self.assertEqual(discovery["false_negative"], 0)
            self.assertEqual(heldout["false_positive"], 0)
            self.assertEqual(heldout["false_negative"], 0)
            self.assertEqual(discovery["true_positive"], 3)

    def test_clang_metrics_report_control_flow(self):
        branch = evaluate.analyze(TOOL, ROOT / "benchmarks/algorithms/minimum.c")
        straight = evaluate.analyze(TOOL, ROOT / "benchmarks/arithmetic/linear.c")
        self.assertGreater(branch["cfg_blocks"], straight["cfg_blocks"])
        self.assertGreater(branch["cyclomatic"], straight["cyclomatic"])
        self.assertNotEqual(branch["ast_shape_sha256"], straight["ast_shape_sha256"])

    @unittest.skipUnless(shutil.which("z3"), "Z3 executable not installed")
    def test_synthesis_is_universally_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = synthesize_rules.run(shutil.which("z3"), Path(tmp) / "synthesis")
            for operation, expected in zip(report["results"], [(1, 1, -1), (1, -1, 1)]):
                self.assertEqual(operation["enumerated"], 27)
                self.assertEqual(len(operation["sample_survivors"]), 1)
                rule = operation["sample_survivors"][0]
                self.assertEqual(tuple(rule[k] for k in ("p", "q", "r")), expected)
                self.assertEqual(rule["status"], "proved-under-model")


if __name__ == "__main__":
    unittest.main()
