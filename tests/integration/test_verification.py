"""Translation-validation controls: independent candidates and compiled counterexamples."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())


class Verification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original = self.root / "original.c"
        self.candidate = self.root / "candidate.c"
        self.report = self.root / "proof.json"

    def tearDown(self):
        self.temp.cleanup()

    def compare(self, original, candidate, code=0, extra=()):
        self.original.write_text("#include <stdint.h>\n" + original + "\n")
        self.candidate.write_text("#include <stdint.h>\n" + candidate + "\n")
        result = subprocess.run([TOOL, "verify", str(self.original), str(self.candidate),
                                 "--report", str(self.report), *extra], capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stderr)
        return json.loads(self.report.read_text())

    def test_all_input_proof_and_artifact_binding(self):
        data = self.compare("uint32_t f(uint32_t x,uint32_t y){return 3u*(x+y)+11u;}",
                            "uint32_t f(uint32_t a,uint32_t b){return a*3u+11u+b*3u;}")
        decision = data["functions"][0]
        self.assertEqual(decision["verification"], "proved-under-model")
        self.assertEqual(data["source_sha256"], hashlib.sha256(self.original.read_bytes()).hexdigest())
        self.assertEqual(data["candidate_sha256"], hashlib.sha256(self.candidate.read_bytes()).hexdigest())
        self.assertTrue(data["dependencies"])
        self.assertTrue(data["candidate_dependencies"])
        self.assertEqual(decision["proof"]["obligation_sha256"], hashlib.sha256(decision["proof"]["smtlib"].encode()).hexdigest())

    def test_counterexample_replays_in_compiled_c(self):
        data = self.compare("uint32_t f(uint32_t x,uint32_t y){return x*17u+y;}",
                            "uint32_t f(uint32_t x,uint32_t y){return x*19u+y;}", 3)
        proof = data["functions"][0]["proof"]
        self.assertEqual(proof["status"], "counterexample")
        self.assertNotEqual(proof["original_output"], proof["candidate_output"])
        compiler = shutil.which("clang") or shutil.which("cc")
        for name, source in [("original", self.original), ("candidate", self.candidate)]:
            subprocess.run([compiler, "-std=c11", f"-Df={name}", "-c", str(source), "-o", str(self.root / (name + ".o"))], check=True, capture_output=True)
        x, y = proof["inputs"]
        driver = self.root / "replay.c"
        driver.write_text(f"""#include <stdint.h>
uint32_t original(uint32_t,uint32_t); uint32_t candidate(uint32_t,uint32_t);
int main(void) {{ return original({x}u,{y}u)!={proof['original_output']}u ||
candidate({x}u,{y}u)!={proof['candidate_output']}u; }}
""")
        binary = self.root / "replay"
        subprocess.run([compiler, str(driver), str(self.root / "original.o"), str(self.root / "candidate.o"), "-o", str(binary)], check=True, capture_output=True)
        subprocess.run([str(binary)], check=True)

    def test_unsupported_arity_and_missing_functions(self):
        for candidate in ["uint32_t f(uint32_t x,uint32_t y){return x+y;}",
                          "uint32_t f(uint32_t x){return x*x;}",
                          "uint32_t g(uint32_t x){return x;}"]:
            with self.subTest(candidate=candidate):
                data = self.compare("uint32_t f(uint32_t x){return x;}", candidate, 3)
                self.assertEqual(data["functions"][0]["verification"], "unsupported")

    def test_selected_function(self):
        source = "uint32_t f(uint32_t x){return x;} int main(void){return 0;}"
        data = self.compare(source, source, extra=("--function", "f", "--timeout-ms", "1234"))
        self.assertEqual(len(data["functions"]), 1)
        self.assertEqual(data["timeout_ms"], 1234)

    def test_transform_proves_reparsed_artifact(self):
        self.original.write_text("#include <stdint.h>\nuint32_t f(uint32_t x){uint32_t a=x+1u; a=a*3u; return a-7u;}\n")
        p = subprocess.run([TOOL, "transform", str(self.original), "-o", str(self.candidate), "--seed", "42", "--report", str(self.report)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(self.report.read_text())
        self.assertEqual(data["functions"][0]["verification"], "proved-under-model")
        self.assertTrue(data["output_written"])
        self.assertEqual(data["candidate_sha256"], hashlib.sha256(self.candidate.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
