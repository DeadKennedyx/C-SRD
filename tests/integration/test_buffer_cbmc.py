"""Optional independent C frontend checks, including invalid-result controls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL = str(Path(sys.argv.pop(1)).resolve())
ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "tools/verify_buffers_cbmc.py"


class BufferCBMC(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        if os.environ.get("CSRD_BUFFER_CBMC_EVIDENCE"):
            self.root = Path(os.environ["CSRD_BUFFER_CBMC_EVIDENCE"]).resolve() / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=False)
        else:
            self.root = Path(self.temp.name)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def compare(self, original, candidate, offsets="0", words=3, status="bounded-checked", extra=()):
        directory = self.root / str(self.counter); directory.mkdir(); self.counter += 1
        left = directory / "original.c"; right = directory / "candidate.c"
        left.write_text("#include <stdint.h>\n" + original)
        right.write_text("#include <stdint.h>\n" + candidate)
        output = directory / "proof"
        run = subprocess.run([sys.executable, str(ADAPTER), str(left), str(right), "--csrd", TOOL,
                              "--function", "f", "--offsets", offsets, "--words", str(words),
                              "--solver", "z3", "--timeout", "15", "--output-dir", str(output), *extra],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0 if status == "bounded-checked" else 3, run.stdout + run.stderr)
        result = json.loads((output / "report.json").read_text())
        self.assertEqual(result["status"], status, result)
        return result

    def test_unavailable_tool_is_explicit(self):
        self.compare("uint32_t f(uint32_t*p){return *p;}", "uint32_t f(uint32_t*p){return *p;}",
                     status="unavailable", extra=("--cbmc", "csrd-missing-cbmc-executable"))

    @unittest.skipUnless(shutil.which("cbmc") and shutil.which("z3"), "CBMC/Z3 unavailable")
    def test_actual_affine_artifacts_in_four_alias_layouts(self):
        source = ROOT / "tests/fixtures/buffers.c"
        candidate = self.root / "candidate.c"
        subprocess.run([TOOL, "transform", str(source), "-o", str(candidate), "--seed", "42"],
                       check=True, capture_output=True)
        for function in ("buffer_mix", "buffer_store", "buffer_snapshot", "buffer_boundary", "buffer_unused", "buffer_const"):
            for offsets in ("0,0", "0,1", "1,0", "0,16"):
                with self.subTest(function=function, offsets=offsets):
                    output = self.root / f"{function}-{offsets.replace(',', '-')}"
                    run = subprocess.run([sys.executable, str(ADAPTER), str(source), str(candidate), "--csrd", TOOL,
                                          "--function", function, "--offsets", offsets, "--words", "32",
                                          "--solver", "z3", "--timeout", "15", "--output-dir", str(output)],
                                         capture_output=True, text=True, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    result = json.loads((output / "report.json").read_text())
                    self.assertEqual(result["status"], "bounded-checked")
                    self.assertIn("--unwinding-assertions", result["command"])
                    self.assertGreaterEqual(sum(p.get("description", "").startswith("memory cell ")
                                                for p in result["properties"]), 32)

    @unittest.skipUnless(shutil.which("cbmc") and shutil.which("z3"), "CBMC/Z3 unavailable")
    def test_negative_store_and_untouched_cell(self):
        self.compare("uint32_t f(uint32_t*p,uint32_t x){*p=x+1u;return 7u;}",
                     "uint32_t f(uint32_t*p,uint32_t x){*p=x+2u;return 7u;}", status="counterexample")
        self.compare("uint32_t f(uint32_t*p,uint32_t x){uint32_t a=p[2];*p=x;return a;}",
                     "uint32_t f(uint32_t*p,uint32_t x){uint32_t a=p[2];*p=x;p[1]=x;return a;}",
                     status="counterexample")

    @unittest.skipUnless(shutil.which("cbmc") and shutil.which("z3"), "CBMC/Z3 unavailable")
    def test_alias_order_control_and_disjoint_positive(self):
        original = "uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){p[1]=x;return q[0];}"
        candidate = "uint32_t f(uint32_t*p,uint32_t*q,uint32_t x){uint32_t v=q[0];p[1]=x;return v;}"
        self.compare(original, candidate, offsets="0,1", status="counterexample")
        self.compare(original, candidate, offsets="0,2")

    @unittest.skipUnless(shutil.which("cbmc") and shutil.which("z3"), "CBMC/Z3 unavailable")
    def test_layout_and_footprint_controls(self):
        source = "uint32_t f(uint32_t*p){return p[1];}"
        self.compare(source, source, offsets="2", words=3, status="error")
        self.compare(source, "uint32_t f(uint32_t*p){return p[2];}", status="error")

    @unittest.skipUnless(shutil.which("cbmc"), "CBMC unavailable")
    def test_default_sat_backend_positive_and_negative(self):
        source = "uint32_t f(uint32_t*p,uint32_t x){p[0]=x;return x;}"
        self.compare(source, source, extra=("--solver", "sat"))
        self.compare(source, "uint32_t f(uint32_t*p,uint32_t x){p[0]=x+1u;return x;}",
                     status="counterexample", extra=("--solver", "sat"))

    @unittest.skipUnless(shutil.which("cbmc") and shutil.which("z3"), "CBMC/Z3 unavailable")
    def test_insufficient_unwinding_cannot_pass(self):
        source = self.root / "unwind.c"
        source.write_text('int main(void){unsigned int i=0;while(i<3u){++i;}__CPROVER_assert(i==3u,"finished");return 0;}')
        command = [shutil.which("cbmc"), str(source), "--unwind", "1", "--unwinding-assertions", "--z3", "--json-ui"]
        run = subprocess.run(command, capture_output=True, text=True, timeout=20)
        (self.root / "unwind-output.json").write_text(run.stdout)
        (self.root / "command.json").write_text(json.dumps(command))
        self.assertEqual(run.returncode, 10, run.stdout + run.stderr)
        properties = [p for item in json.loads(run.stdout) for p in item.get("result", [])]
        self.assertTrue(any("unwind" in p["property"] and p["status"] == "FAILURE" for p in properties))


if __name__ == "__main__":
    unittest.main()
