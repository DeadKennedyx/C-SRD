"""Real resource accounting, observer grading and bounded session measurement tests."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
TOOL = str(Path(sys.argv.pop(1)).resolve())
from audit_protection import file_hash
from effort_resources import measure, save
from effort_statistics import summarize
from effort_worker import blackbox, model_source
from human_effort import start, event
from summarize_query_recovery import paired_trials, summarize as summarize_queries


class Resources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_cpu_and_peak_memory_include_waited_child(self):
        program = "import time; a=bytearray(32*1024*1024); t=time.process_time();\nwhile time.process_time()-t<0.18: pass\ntime.sleep(0.04)"
        result = measure([sys.executable, "-c", "import subprocess,sys; subprocess.run([sys.executable,'-c'," +
                          repr(program) + "],check=True)"], self.root / "cpu", wall_seconds=10)
        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["cpu_seconds"], 0.15)
        self.assertGreater(result["peak_process_rss_bytes"], 32*1024*1024)
        if sys.platform.startswith("linux"):
            self.assertGreater(result["peak_sampled_tree_rss_bytes"], 32*1024*1024)
            self.assertGreaterEqual(result["sampled_processes"], 2)
            self.assertTrue(result["subreaper"])
        else:
            self.assertIsNone(result["peak_sampled_tree_rss_bytes"])

    def test_launch_failure_is_not_zero_cost_success(self):
        result = measure(["/no-such-csrd-tool"], self.root / "missing", wall_seconds=1)
        self.assertEqual(result["status"], "launch-error")
        self.assertNotIn("cpu_seconds", result)

    def test_wall_budget_kills_child_group(self):
        result = measure([sys.executable, "-c", "import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(30)"],
                         self.root / "wall", wall_seconds=0.15)
        self.assertEqual(result["status"], "wall-budget")
        self.assertLess(result["wall_seconds"], 4)
        if sys.platform.startswith("linux"):
            self.assertGreaterEqual(result["reaped_children"], 2)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux sampled resource budgets")
    def test_cpu_and_memory_budgets_and_orphan_accounting(self):
        for name, program, budgets in [
            ("cpu", "while True: pass", {"cpu_seconds": .08}),
            ("memory", "import time; a=bytearray(64*1024*1024); time.sleep(30)", {"memory_bytes": 40*1024*1024})]:
            result = measure([sys.executable, "-c", program], self.root / name, wall_seconds=5, **budgets)
            self.assertEqual(result["status"], name + "-budget")
        result = measure([sys.executable, "-c", "import os,time; p=os.fork();\n"
                          "if p: os._exit(0)\nos.setsid(); t=time.process_time()\n"
                          "while time.process_time()-t<0.15: pass"], self.root / "orphan", wall_seconds=5)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reaped_children"], 2)
        self.assertGreater(result["cpu_seconds"], .14)


class Statistics(unittest.TestCase):
    def test_matching_wrong_hypotheses_and_missing_transcripts_are_not_recovery(self):
        base = {"case":"f", "profile":"p", "budget_id":0, "budget":{"query_budget":3},
                "warmup":False, "repetition":0, "status":"wrong-candidate", "id":0,
                "variant":"original", "candidate_sha256":"same-candidate",
                "resources":{"cpu_seconds":1}, "answer":{"training_queries":3,"model":{"kind":"wrong"}}}
        rows = [base, {**base,"id":1,"variant":"candidate"}]
        transcript = {"inputs":[[0],[1],[2]],"outputs":[0,1,4]}
        pairs = paired_trials(rows,{0:transcript,1:transcript})
        candidate = next(r for r in summarize_queries(pairs) if r["variant"]=="candidate")
        self.assertEqual(candidate["comparisons"]["models_identical"],{"compared":1,"identical":1})
        self.assertEqual(candidate["paired_recovery_query_ratio"]["n"],0)
        self.assertEqual(candidate["paired_recovery_cpu_ratio"]["n"],0)
        rows[0]["status"] = rows[1]["status"] = "recovered-under-source-model"
        pairs = paired_trials(rows,{0:transcript})
        self.assertIsNone(pairs[1]["inputs_identical"])
        self.assertIsNone(pairs[1]["outputs_identical"])
        self.assertIsNone(pairs[1]["recovery_query_ratio"])
        self.assertEqual(pairs[0]["recovery_query_ratio"],1)

    def test_identical_binary_control_flags_even_large_measured_cost_differences(self):
        base = {"case": "f", "profile": "p", "budget_id": 0, "warmup": False, "repetition": 0,
                "status": "recovered-under-source-model", "binary_sha256": "same-artifact",
                "resources": {"cpu_seconds": 1}}
        rows = [{**base, "variant": "original"}, {**base, "variant": "encoded", "resources": {"cpu_seconds": 4}}]
        group = next(g for g in summarize(rows)["groups"] if g["variant"] == "encoded")
        self.assertTrue(group["binary_identity_control"]["all_paired_binaries_identical"])
        self.assertEqual(group["paired_successful_ratios"]["cpu_seconds"]["median"], 4)
        rows[1].pop("binary_sha256")
        group = next(g for g in summarize(rows)["groups"] if g["variant"] == "encoded")
        self.assertIsNone(group["binary_identity_control"]["all_paired_binaries_identical"])

    def test_only_paired_successes_have_cost_ratios_and_gaps_stay_visible(self):
        base = {"case": "f", "profile": "p", "budget_id": 0, "warmup": False,
                "status": "recovered-under-source-model", "resources": {"wall_seconds": 2, "cpu_seconds": 1}}
        rows = [{**base, "variant": "original", "repetition": i} for i in range(5)]
        rows += [{**base, "variant": "encoded", "repetition": i,
                  "resources": {"wall_seconds": 6, "cpu_seconds": 4}} for i in range(5)]
        rows[7]["status"] = "wall-budget"
        rows[7]["answer"] = None  # A killed worker cannot necessarily write an answer.
        rows[8]["status"] = "unsupported-reconstruction"
        rows[9]["status"] = "wrong-candidate"
        rows.append({**base, "variant": "encoded", "repetition": -1, "warmup": True})
        result = next(g for g in summarize(rows)["groups"] if g["variant"] == "encoded")
        self.assertEqual(result["attempts"], 5)
        self.assertEqual(result["success_fraction_all_attempts"], .4)
        self.assertEqual(result["coverage_gaps"], 1)
        self.assertEqual(result["correct_fraction_decidable_submissions"], 2/3)
        self.assertEqual(result["paired_successful_ratios"]["cpu_seconds"]["median"], 4)
        self.assertEqual(result["paired_successful_ratios"]["wall_seconds"]["n"], 2)
        self.assertIsNone(result["paired_successful_ratios"]["cpu_seconds"]["bootstrap_95_interval"])


class HumanRecorder(unittest.TestCase):
    def test_pauses_freeze_active_time_submissions_are_snapshots_and_clocks_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "program").write_bytes(b"test-only packet, not participant data")
            save(root / "task.json", {"task_id": "synthetic", "binary": "program",
                                       "binary_sha256": file_hash(root / "program"), "budget_seconds": 12})
            def clock(t):
                return {"utc": "synthetic", "unix_seconds": 1000+t, "monotonic_seconds": t}
            with patch("human_effort.timestamp", return_value=clock(0)):
                start(root / "task.json", root / "session", "test fixture", "no")
            with patch("human_effort.timestamp", return_value=clock(5)):
                event(root / "session", "pause")
            with patch("human_effort.timestamp", return_value=clock(50)):
                event(root / "session", "resume")
            (root / "answer.c").write_text("first")
            with patch("human_effort.timestamp", return_value=clock(58)):
                state = event(root / "session", "submit", root / "answer.c")
            self.assertEqual(state["active_seconds"], 13)
            self.assertFalse(state["submissions"][0]["within_budget"])
            (root / "answer.c").write_text("changed")
            self.assertEqual(Path(state["submissions"][0]["path"]).read_text(), "first")
            with patch("human_effort.timestamp", return_value=clock(1)), self.assertRaisesRegex(ValueError, "discontinuity"):
                event(root / "session", "finish")
            with patch("human_effort.timestamp", return_value=clock(60)):
                event(root / "session", "finish")
            with self.assertRaisesRegex(ValueError, "finished"):
                event(root / "session", "resume")


class EffortIntegration(unittest.TestCase):
    def test_real_matrix_query_sweep_and_human_grading(self):
        compiler = next((shutil.which(p) for p in ["/opt/homebrew/opt/llvm/bin/clang", "clang-18", "clang"] if shutil.which(p)), None)
        objdump = next((shutil.which(p) for p in ["/opt/homebrew/opt/llvm/bin/llvm-objdump", "llvm-objdump-18", "llvm-objdump"] if shutil.which(p)), None)
        self.assertIsNotNone(compiler); self.assertIsNotNone(objdump)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root / "manifest.json", {"schema_version": 1, "cases": [
                {"id": "calculate", "source": "benchmarks/arithmetic/calculate.c", "family": "linear", "split": "development"},
                {"id": "xor", "source": "benchmarks/bitwise/xor.c", "family": "xor", "split": "development"}],
                "profiles": [{"id": "clang-O2", "compiler": "clang", "optimization": "O2", "tiers": ["core"]}]})
            def run(arguments, code=0):
                process = subprocess.run([sys.executable, *map(str, arguments)], capture_output=True, text=True, timeout=150)
                self.assertEqual(process.returncode, code, process.stdout[-4000:] + process.stderr[-4000:])
            run([ROOT / "tools/run_matrix.py", "--matrix", root / "manifest.json", "--csrd", TOOL,
                 "--compiler", "clang=" + compiler, "--objdump", objdump, "--strategies", "identity", "affine",
                 "--inputs", "4", "--iterations", "1000", "--repetitions", "3", "--output-dir", root / "matrix"])
            matrix_path = root / "matrix/matrix.json"
            common = [ROOT / "tools/measure_effort.py", "--matrix-report", matrix_path, "--csrd", TOOL,
                      "--observer", "blackbox", "--case", "calculate", "--case", "xor", "--profile", "clang-O2",
                      "--variant", "original", "--variant", "affine-42", "--query-budgets", "3", "12",
                      "--repetitions", "1", "--warmups", "0"]
            run([*common, "--output-dir", root / "effort"])
            report = json.loads((root / "effort/effort.json").read_text())
            self.assertEqual(len(report["trials"]), 8)
            for trial in report["trials"]:
                expected = "wrong-candidate" if trial["case"] == "xor" and trial["budget_id"] == 0 else "recovered-under-source-model"
                self.assertEqual(trial["status"], expected, trial)
                self.assertEqual(trial["negative_control"]["status"], "counterexample")
                self.assertGreater(trial["resources"]["cpu_seconds"], 0)
            bitlinear = [ROOT / "tools/measure_effort.py", "--matrix-report", matrix_path, "--csrd", TOOL,
                         "--observer", "bitlinear", "--case", "calculate", "--case", "xor", "--profile", "clang-O2",
                         "--variant", "original", "--query-budgets", "3", "65", "128",
                         "--repetitions", "1", "--warmups", "0", "--output-dir", root / "bitlinear"]
            run(bitlinear)
            linear = json.loads((root / "bitlinear/effort.json").read_text())
            for trial in linear["trials"]:
                expected = ("no-candidate" if trial["budget_id"] == 0 else
                            "recovered-under-source-model" if trial["case"] == "xor" else
                            "wrong-candidate" if trial["budget_id"] == 1 else "no-candidate")
                self.assertEqual(trial["status"], expected, trial)
                self.assertEqual(trial["query_accounting"]["completed"], trial["budget"]["query_budget"])
            run([ROOT/"tools/summarize_query_recovery.py","--effort-report",root/"bitlinear/effort.json",
                 "--output-dir",root/"query-summary"])
            query_summary=json.loads((root/"query-summary/summary.json").read_text())
            self.assertEqual(query_summary["trial_pairs"],6)
            self.assertEqual(query_summary["outcomes"],{"no-candidate":3,"wrong-candidate":1,"recovered-under-source-model":2})
            trial_path=root/"bitlinear/trial-00000/trial.json"
            original_trial=trial_path.read_bytes()
            trial_path.write_text('{}')
            run([ROOT/"tools/summarize_query_recovery.py","--effort-report",root/"bitlinear/effort.json",
                 "--output-dir",root/"tampered-query-summary"],code=1)
            self.assertFalse((root/"tampered-query-summary/summary.json").exists())
            trial_path.write_bytes(original_trial)
            config_path=root/"bitlinear/trial-00000/observer/config.json"
            original_config=config_path.read_bytes()
            config=json.loads(original_config);config["function"]="wrong_interface"
            config_path.write_text(json.dumps(config))
            run([ROOT/"tools/summarize_query_recovery.py","--effort-report",root/"bitlinear/effort.json",
                 "--output-dir",root/"wrong-interface-summary"],code=1)
            self.assertFalse((root/"wrong-interface-summary/summary.json").exists())
            config_path.write_bytes(original_config)
            # A partial matrix is opt-in and never authorizes failed cells.
            original_matrix = json.loads(matrix_path.read_text())
            partial = copy.deepcopy(original_matrix)
            partial["status"] = "failed"
            partial["summary"]["failed"] = 1
            save(matrix_path, partial)
            run([*common, "--output-dir", root / "partial-denied"], code=1)
            run([*common, "--allow-partial-matrix", "--output-dir", root / "partial-allowed"])
            partial["records"][0]["status"] = "failed"
            save(matrix_path, partial)
            run([*common, "--allow-partial-matrix", "--output-dir", root / "failed-cell-denied"], code=1)
            save(matrix_path, original_matrix)
            run([ROOT / "tools/measure_effort.py", "--matrix-report", matrix_path, "--csrd", TOOL,
                 "--observer", "blackbox", "--case", "calculate", "--profile", "clang-O2", "--variant", "original",
                 "--wall-budgets", "0.001", "--repetitions", "1", "--warmups", "0", "--output-dir", root / "timeout"])
            timed = json.loads((root / "timeout/effort.json").read_text())
            self.assertTrue(all(t["status"] == "wall-budget" for t in timed["trials"]))
            self.assertTrue(all(g["success_fraction_all_attempts"] == 0 for g in timed["summary"]["groups"]))
            run([ROOT / "tools/human_effort.py", "prepare", "--matrix-report", matrix_path, "--case", "calculate",
                 "--profile", "clang-O2", "--variant", "affine-42", "--participants", "2", "--output-dir", root / "study"])
            task = next((root / "study/packets/p001").glob("*/task.json"))
            run([ROOT / "tools/human_effort.py", "start", "--task", task, "--session-dir", root / "synthetic-session",
                 "--experience", "automated test, not human data", "--prior-exposure", "yes"])
            run([ROOT / "tools/human_effort.py", "submit", "--session-dir", root / "synthetic-session", "--candidate",
                 ROOT / "benchmarks/arithmetic/calculate.c"])
            run([ROOT / "tools/human_effort.py", "finish", "--session-dir", root / "synthetic-session"])
            run([ROOT / "tools/human_effort.py", "score", "--session-dir", root / "synthetic-session", "--private-key",
                 root / "study/private-key.json", "--csrd", TOOL])
            scoring = json.loads((root / "synthetic-session/grading/score.json").read_text())
            self.assertTrue(scoring["success_within_budget"])
            if shutil.which("gdb"):
                run([ROOT / "tools/measure_effort.py", "--matrix-report", matrix_path, "--csrd", TOOL,
                     "--observer", "runtime", "--case", "calculate", "--profile", "clang-O2",
                     "--variant", "original", "--query-budgets", "4", "--step-budgets", "1", "64",
                     "--repetitions", "1", "--warmups", "0", "--output-dir", root / "runtime"])
                runtime = json.loads((root / "runtime/effort.json").read_text())
                self.assertEqual(runtime["trials"][0]["status"], "no-candidate")
                self.assertEqual(runtime["trials"][1]["status"], "recovered-on-heldout")
                self.assertEqual(runtime["trials"][1]["negative_control"]["validated_models"], 0)
            if os.environ.get("CSRD_GHIDRA_HEADLESS"):
                run([ROOT / "tools/measure_effort.py", "--matrix-report", matrix_path, "--csrd", TOOL,
                     "--observer", "ghidra", "--case", "calculate", "--profile", "clang-O2",
                     "--variant", "original", "--repetitions", "1", "--warmups", "0",
                     "--output-dir", root / "ghidra"])
                ghidra = json.loads((root / "ghidra/effort.json").read_text())
                self.assertEqual(ghidra["trials"][0]["status"], "recovered-under-source-model")
                self.assertGreater(ghidra["trials"][0]["answer"]["export"]["decompile_seconds"], 0)
            matrix = json.loads(matrix_path.read_text())
            Path(matrix["records"][0]["binary"]).write_bytes(b"changed")
            run([*common, "--output-dir", root / "changed"], code=1)
            self.assertIn("changed binary", (root / "changed/failure.json").read_text())


if __name__ == "__main__":
    unittest.main()
