"""Exact circuit export, gate corruption, evidence and process controls.

ABC itself is optional. Tests of its text protocol use explicitly synthetic
messages, not fabricated reconstruction results.
"""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from effort_resources import measure
from verify_circuit import abc_status, check
import grade_saved_answers


class QueryCircuits(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.query = self.root / "query.smt2"
        self.query.write_text("(declare-const x Bool)\n(declare-const y Bool)\n(assert (xor x y))\n")
        self.serial = 0

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, mode, *inputs, succeeds=True):
        self.serial += 1
        directory = self.root / f"result-{self.serial}"
        result = subprocess.run([TOOL, mode, *map(str, inputs), str(directory)], capture_output=True, text=True, timeout=15)
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr)
        return directory, result

    def export(self):
        directory, _ = self.invoke("export", self.query)
        return directory / "circuit.blif"

    def test_boolean_and_bitvector_contracts_with_replay(self):
        queries = ["(assert false)", "(assert true)", self.query.read_text(),
                   "(declare-const a Bool)(declare-const b Bool)(declare-const c Bool)"
                   "(assert (= (ite a (and b c) (or b c)) (xor a (not b))))",
                   "(declare-const x (_ BitVec 32))(declare-const y (_ BitVec 32))"
                   "(assert (distinct (bvsub x y) (bvxor (bvadd x y) (bvlshr x (_ bv5 32)))))"]
        for query in queries:
            with self.subTest(query=query):
                self.query.write_text(query)
                circuit = self.export()
                directory, result = self.invoke("check", self.query, circuit)
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "circuit-validated")
                obligations = list(directory.glob("obligation-*.smt2"))
                self.assertEqual(len(obligations), report["obligations"])
                self.assertEqual(len((directory / "gate-checks.tsv").read_text().splitlines()) - 1, report["gates"])
                z3 = shutil.which("z3")
                if z3:
                    for obligation in obligations:
                        replay = subprocess.run([z3, "-T:2", str(obligation)], capture_output=True, text=True, timeout=3)
                        self.assertEqual((replay.returncode, replay.stdout.strip(), replay.stderr), (0, "unsat", ""))

    def test_actual_truth_table_mutations_rejected(self):
        circuit = self.export()
        valid = circuit.read_text()
        rows = "00 1\n11 1\n" if "00 1\n11 1\n" in valid else "01 1\n10 1\n"
        inverted = "01 1\n10 1\n" if rows.startswith("00") else "00 1\n11 1\n"
        mutants = [valid.replace(rows, inverted), valid.replace(rows, rows.splitlines()[0] + "\n"),
                   valid.replace("1 1\n.end", "0 1\n.end")]
        for mutant in mutants:
            self.assertNotEqual(mutant, valid)
            circuit.write_text(mutant)
            self.invoke("check", self.query, circuit, succeeds=False)

    def test_rewiring_and_bad_networks_rejected(self):
        circuit = self.export(); valid = circuit.read_text()
        names = next(line.split()[1:] for line in valid.splitlines() if line.startswith(".inputs"))
        self.assertEqual(len(names), 2)
        row = "00 1" if "00 1\n11 1" in valid else "01 1"
        header = next(line for line in valid.splitlines() if line.startswith(".names ") and len(line.split()) >= 3)
        fields = header.split()
        mutants = [valid.replace(".inputs " + " ".join(names), ".inputs " + " ".join(reversed(names))),
                   valid.replace(".inputs " + " ".join(names), ".inputs " + " ".join(names + [names[0]])),
                   valid.replace(row, "02 1"),
                   valid.replace(".end", ""), valid + ".names other\n1\n",
                   valid.replace(".outputs output", ".outputs output another"),
                   valid.replace(header, " ".join([fields[0], "output", *fields[2:]])),
                   valid.replace(header, " ".join([fields[0], "missing", *fields[2:]]))]
        for mutant in mutants:
            self.assertNotEqual(mutant, valid)
            circuit.write_text(mutant)
            self.invoke("check", self.query, circuit, succeeds=False)

    def test_original_query_binding(self):
        circuit = self.export()
        self.query.write_text(self.query.read_text().replace("xor", "or"))
        self.invoke("check", self.query, circuit, succeeds=False)

    def test_unsupported_queries(self):
        for text in ["(assert true)(assert false)",
                     "(assert (forall ((x Bool)) x))",
                     "(declare-const x Int)(assert (= x 1))",
                     "(declare-const x (_ BitVec 65))(assert (= x (_ bv1 65)))",
                     "(declare-fun f (Bool) Bool)(declare-const x Bool)(assert (f x))"]:
            self.query.write_text(text)
            self.invoke("export", self.query, succeeds=False)

    def test_does_not_overwrite_evidence(self):
        directory, _ = self.invoke("export", self.query)
        before = (directory / "circuit.blif").read_bytes()
        result = subprocess.run([TOOL, "export", str(self.query), str(directory)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((directory / "circuit.blif").read_bytes(), before)

    def test_abc_protocol_failures_never_prove(self):
        ok = {"status": "completed", "returncode": 0}
        positive = "Networks are equivalent.  Time = 0.10 sec\n"
        negative = "Networks are NOT EQUIVALENT.  Time = 0.10 sec\n"
        self.assertEqual(abc_status(ok, positive, ""), "unsat")
        self.assertEqual(abc_status(ok, negative, ""), "sat")
        for reason in ("different phase", "different PIs", "PI vs. constant"):
            trivial = f"Networks are NOT EQUIVALENT. Output 0 trivially differs ({reason}).  Time = 0.00 sec\n"
            self.assertEqual(abc_status(ok, trivial, ""), "sat")
            self.assertEqual(abc_status(ok, positive + trivial, ""), "inconclusive")
        for out, err, resource in [("", "", ok), (positive + negative, "", ok),
                                   (positive + positive, "", ok), ("command: " + positive, "", ok),
                                   (positive, "load error", ok), (positive, "", {"status": "wall-budget", "returncode": 0}),
                                   (positive, "", {"status": "completed", "returncode": 1})]:
            self.assertEqual(abc_status(resource, out, err), "inconclusive")

    def test_driver_launch_failure_and_bad_budgets(self):
        false = shutil.which("false")
        if false:
            report = check(self.query, TOOL, false, self.root / "failed")
            self.assertEqual(report["status"], "inconclusive")
            self.assertNotIn("solve", report["stages"])
        for solver, stage in [(0, 8), (5, 5), (5, float("nan")), (5, float("inf")), (0.5, 8)]:
            with self.assertRaises(ValueError):
                check(self.query, TOOL, TOOL, self.root / "invalid", solver, stage)

    def test_measure_working_directory_without_command_interpolation(self):
        cwd = self.root / 'path with spaces; $(no command)'
        cwd.mkdir()
        result = measure([sys.executable, "-c", "import os;print(os.getcwd())"], self.root / "cwd", wall_seconds=3, cwd=cwd)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((self.root / "cwd/stdout.txt").read_text().strip(), str(cwd.resolve()))

    def test_saved_C_and_query_bindings_reject_stale_evidence(self):
        previous = grade_saved_answers.ROOT
        grade_saved_answers.ROOT = self.root.resolve()
        try:
            trial = self.root.resolve() / "trial"
            section = trial / "grade"; (section / "measurement").mkdir(parents=True)
            reference, candidate = self.root / "reference.i", self.root / "candidate.c"
            reference.write_text("unsigned f(unsigned x){return x;}\n")
            candidate.write_bytes(reference.read_bytes())
            sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            text = "(assert false)\n"
            report = {"action": "verify", "model": "test-model", "target": "test-target", "solver": "test-version",
                      "source_sha256": sha(reference), "candidate_sha256": sha(candidate),
                      "functions": [{"function": "f", "verification": "inconclusive",
                                     "proof": {"smtlib": text, "obligation_sha256": hashlib.sha256(text.encode()).hexdigest()}}]}
            proof = section / "proof.json"; proof.write_text(json.dumps(report))
            command = section / "measurement/command.json"
            command.write_text(json.dumps({"argv": ["/work/tool", "verify", "/work/reference.i", "/work/candidate.c"]}))
            binding, actual = grade_saved_answers.bound_query(trial, "grade")
            self.assertEqual(actual, text)
            self.assertEqual(binding["files"][1]["sha256"], sha(candidate))
            candidate.write_text("unsigned f(unsigned x){return x+1u;}\n")
            with self.assertRaisesRegex(ValueError, "frozen C input mismatch"):
                grade_saved_answers.bound_query(trial, "grade")
            candidate.write_bytes(reference.read_bytes())
            report["functions"][0]["proof"]["smtlib"] = "(assert true)\n"
            proof.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "SMT hash mismatch"):
                grade_saved_answers.bound_query(trial, "grade")
        finally:
            grade_saved_answers.ROOT = previous


if __name__ == "__main__":
    unittest.main()
