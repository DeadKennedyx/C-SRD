"""Real linked builds plus boundary tests for selection and observer inference."""
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
TOOL = str(Path(sys.argv.pop(1)).resolve())
from experiment_support import assembly_metrics, ir_structure, select_candidates, reconstruct
from observe_runtime import fit_affine, score_models


class Matrix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.compiler = next((shutil.which(p) for p in [
            os.environ.get("CSRD_MATRIX_CLANG", ""), "/opt/homebrew/opt/llvm/bin/clang",
            "clang-18", "clang"] if p and shutil.which(p)), None)
        self.objdump = next((shutil.which(p) for p in [
            os.environ.get("CSRD_OBJDUMP", ""), "/opt/homebrew/opt/llvm/bin/llvm-objdump",
            "llvm-objdump-18", "llvm-objdump"] if p and shutil.which(p)), None)
        if not self.compiler or not self.objdump:
            raise RuntimeError("Clang and llvm-objdump required")
        self.manifest = {"schema_version": 1, "cases": [
            {"id": "calculate", "source": "benchmarks/arithmetic/calculate.c",
             "family": "linear", "split": "development"}],
            "profiles": [{"id": "clang-O2", "compiler": "clang", "optimization": "O2",
                          "tiers": ["core"], "selection_required": True}]}

    def execute_matrix(self, name="run", expected=0, extra=()):
        manifest = self.root / (name + ".json")
        manifest.write_text(json.dumps(self.manifest))
        out = self.root / name
        result = subprocess.run([sys.executable, str(ROOT / "tools/run_matrix.py"),
                                 "--matrix", str(manifest), "--csrd", TOOL,
                                 "--compiler", "clang=" + self.compiler, "--objdump", self.objdump,
                                 "--strategies", "identity", "affine", "--inputs", "8",
                                 "--iterations", "10000", "--repetitions", "3",
                                 "--output-dir", str(out), *extra], text=True, capture_output=True, timeout=150)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads((out / "matrix.json").read_text())

    def test_linked_execution_and_identity_controls(self):
        report = self.execute_matrix()
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(report["records"]), 3)
        original, identity, affine = report["records"]
        self.assertEqual(original["execution"], identity["execution"])
        self.assertFalse(identity["comparison"]["instruction_sequences_differ_from_original"])
        self.assertTrue(affine["reconstruction"]["recovered_on_heldout"])
        for record in report["records"]:
            self.assertEqual(record["source_verification"], "proved-under-model")
            self.assertEqual(record["llvm_ir"]["status"], "measured")
            binding = json.loads(Path(record["validation"]).read_text())
            self.assertEqual(len(binding["configurations"][0]["build_validation"]), 2)

    def test_control_flow_selection_requires_its_own_contribution(self):
        # Different instructions from the original are insufficient when the same
        # encoding without the branch already gives that difference.
        record = {"case": "f", "split": "development", "variant": "identity-split-scale",
                  "profile": "p", "status": "completed", "strategy": "identity",
                  "control_flow": "split-scale", "split_scales": 1,
                  "comparison": {"instruction_sequences_differ_from_original": True,
                                 "instruction_sequences_differ_from_control_flow_control": False},
                  "timing": {"max_paired_ratio": 1.0}, "binary_size_ratio": 1.0}
        result = select_candidates([record], ["p"], 2.0, 2.0)
        self.assertFalse(result["decisions"][0]["eligible"])
        self.assertIn("control-flow-contribution-absent-or-unassessed", result["decisions"][0]["reasons"])

    def test_control_flow_matrix_has_matching_encoding_and_flow_controls(self):
        report = self.execute_matrix(extra=("--control-flows", "none", "split-scale"))
        self.assertEqual(len(report["records"]), 5)
        variant = next(r for r in report["records"] if r["variant"] == "affine-42-split-scale")
        self.assertEqual(variant["control"], "identity-split-scale")
        self.assertEqual(variant["control_flow_control"], "affine-42")
        self.assertEqual(variant["split_scales"], 1)
        self.assertIn("instruction_sequences_differ_from_control_flow_control", variant["comparison"])

    def test_preprocessor_counterexample_blocks_linking(self):
        source = self.root / "conditional.c"
        source.write_text("#include <stdint.h>\n#if defined(__OPTIMIZE__)\n"
                          "uint32_t f(uint32_t x){return x+2u;}\n#else\n"
                          "uint32_t f(uint32_t x){return x+1u;}\n#endif\n")
        self.manifest["cases"][0]["source"] = str(source)
        report = self.execute_matrix(expected=1)
        self.assertTrue(all(r["status"] == "failed" for r in report["records"]))
        self.assertTrue(all("binary" not in r for r in report["records"]))

    def test_missing_required_configuration_prevents_selection(self):
        self.manifest["profiles"].append({"id": "missing", "compiler": "uninstalled-compiler",
                                         "optimization": "O2", "tiers": ["core"], "selection_required": True})
        report = self.execute_matrix()
        self.assertEqual(report["status"], "completed-with-gaps")
        self.assertEqual(report["profiles"][1]["status"], "unavailable")
        self.assertTrue(all("missing-or-failed-required-profile" in d["reasons"]
                            for d in report["selection"]["decisions"]))

    def test_lto_compiles_and_executes_or_explicitly_unavailable(self):
        self.manifest["profiles"][0]["lto"] = "full"
        p = self.root / "probe.c"
        p.write_text("int main(void){return 0;}\n")
        available = subprocess.run([self.compiler, "-flto", str(p), "-o", str(self.root / "probe")],
                                   capture_output=True).returncode == 0
        report = self.execute_matrix(expected=0 if available else 1)
        if report["profiles"][0]["status"] == "unavailable":
            self.assertEqual(report["records"], [])
        else:
            self.assertEqual(len(report["records"]), 3)
            self.assertTrue(all(r["status"] == "completed" for r in report["records"]))

    @unittest.skipUnless(shutil.which("gdb"), "live observer requires GDB")
    def test_live_observer_recovers_and_step_limit_is_not_success(self):
        report = self.execute_matrix()
        common = [sys.executable, str(ROOT / "tools/observe_runtime.py"),
                  "--matrix-report", str(self.root / "run/matrix.json")]
        target = self.root / "trace"
        result = subprocess.run([*common, "--output-dir", str(target)],
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads((target / "observation.json").read_text())
        self.assertEqual(evidence["status"], "completed")
        for observation in evidence["observations"]:
            self.assertGreater(observation["recovery"]["validated_models"], 0)
            self.assertEqual(observation["negative_control"]["validated_models"], 0)
        limited = self.root / "limited"
        result = subprocess.run([*common, "--step-limit", "1", "--output-dir", str(limited)],
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads((limited / "observation.json").read_text())["status"], "failed")


class Inference(unittest.TestCase):
    def record(self):
        return {"case": "a", "variant": "planned", "split": "development", "profile": "p",
                "status": "completed", "comparison": {"instruction_sequences_differ_from_original": True},
                "timing": {"max_paired_ratio": 1.2}, "binary_size_ratio": 1.1}

    def test_selection_rejects_collapsed_expensive_and_missing(self):
        r = self.record()
        self.assertTrue(select_candidates([r], ["p"], 2, 2)["decisions"][0]["eligible"])
        collapsed = copy.deepcopy(r)
        collapsed["comparison"]["instruction_sequences_differ_from_original"] = False
        self.assertFalse(select_candidates([collapsed], ["p"], 2, 2)["decisions"][0]["eligible"])
        self.assertFalse(select_candidates([r], ["p"], 1.1, 2)["decisions"][0]["eligible"])
        self.assertFalse(select_candidates([r], ["p", "q"], 2, 2)["decisions"][0]["eligible"])

    def test_heldout_cannot_rerank(self):
        r = self.record()
        r["split"] = "heldout"
        with self.assertRaisesRegex(ValueError, "held-out"):
            select_candidates([r], ["p"], 2, 2)

    def test_nonfinite_budgets_are_invalid(self):
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                select_candidates([self.record()], ["p"], value, 2)

    def test_ssa_renaming_preserves_metric_but_operand_change_does_not(self):
        a = "define i32 @f(i32 %x) {\n %y = add i32 %x, 1\n ret i32 %y\n}\n"
        b = a.replace("%x", "%long_name").replace("%y", "%2")
        self.assertEqual(ir_structure(a, "f")["ssa_sha256"], ir_structure(b, "f")["ssa_sha256"])
        self.assertNotEqual(ir_structure(a, "f")["ssa_sha256"], ir_structure(b.replace(", 1", ", 2"), "f")["ssa_sha256"])

    def test_padding_is_not_instruction_diversity(self):
        a = "0000 <main>:\n 0: mov eax, eax\n 4: ret\n"
        b = a + " 8: nop\n c: nopl 0x0(%rax)\n"
        self.assertEqual(assembly_metrics(a, ["main"])["opcode_sha256"],
                         assembly_metrics(b, ["main"])["opcode_sha256"])

    def test_runtime_affine_recovery_and_negative_control(self):
        targets = [17, 20, 144, 11]
        def traces(values):
            return [{"samples": [{"offset": 4, "visit": 0, "values": {"reg:x1": (13*t+7) % 2**32}}]}
                    for t in values]
        models, searched = fit_affine(traces(targets), targets)
        self.assertEqual(searched, 1)
        self.assertEqual(len(models), 1)
        heldout = [2, 579, 0x80000012, 0xfffffffe]
        self.assertEqual(score_models(models, traces(heldout), heldout)["validated_models"], 1)
        negative, _ = fit_affine(traces(targets), targets[1:] + targets[:1])
        self.assertEqual(negative, [])
        wrong = traces(heldout)
        wrong[0]["samples"][0]["values"]["reg:x1"] ^= 1
        self.assertEqual(score_models(models, wrong, heldout)["false_models"], 1)

    def test_recovery_finds_affine_but_reports_rare_false_model(self):
        def command(args, input):
            return "".join(str((3*sum(map(int, l.split()))+11) % 2**32) + "\n" for l in input.splitlines())
        heldout = [(5, 8), (123, 456)]
        expected = [(3*sum(v)+11) % 2**32 for v in heldout]
        result = reconstruct(command, "unused", 2, heldout, expected)
        self.assertTrue(result["recovered_on_heldout"])
        expected[0] += 1
        result = reconstruct(command, "unused", 2, heldout, expected)
        self.assertFalse(result["recovered_on_heldout"])
        self.assertEqual(result["false_models"], 1)


if __name__ == "__main__":
    unittest.main()
